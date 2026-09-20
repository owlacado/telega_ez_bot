import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import hub.models  # noqa: F401
from hub.accounting.service import calculate, calculate_all_weekly
from hub.accounting.xlsx import WeeklyAccountingXlsxModel
from hub.accounting_mirrors.models import (
    AccountingMirrorRefresh,
    AccountingMirrorTarget,
    AccountingMirrorWorkerState,
)
from hub.accounting_mirrors.presentation import all_tech_payload, individual_payload
from hub.accounting_mirrors.provider import (
    SHEETS_SCOPE,
    SheetMetadata,
    SheetsProviderError,
)
from hub.core.config import Settings
from hub.core.secrets import SecretCipher
from hub.google_calendar.models import CalendarConnection
from hub.google_calendar.types import ProviderError

logger = logging.getLogger(__name__)
LEASE = timedelta(minutes=15)
LEASE_RENEW_INTERVAL_SECONDS = 60


@dataclass(frozen=True)
class Claim:
    refresh_id: UUID
    claim_token: UUID
    requested_generation: int
    claimed_from_status: str
    attempt_count: int
    kind: str
    technician_id: UUID | None
    target_id: UUID
    target_generation: int
    spreadsheet_id: str
    connection_id: UUID
    connection_generation: int
    encrypted_refresh_token: str | None
    granted_scopes: tuple[str, ...]
    week_start: date
    google_sheet_id: int | None
    owned_rows: int
    owned_columns: int
    last_fingerprint: str | None
    last_success_at: datetime | None
    successful_target_generation: int | None
    successful_connection_generation: int | None


async def claim(factory) -> Claim | None:
    async with factory() as db, db.begin():
        stamp = await db.scalar(select(func.clock_timestamp()))
        row = (
            await db.execute(
                select(AccountingMirrorRefresh, AccountingMirrorTarget, CalendarConnection)
                .join(
                    AccountingMirrorTarget,
                    AccountingMirrorTarget.id == AccountingMirrorRefresh.target_id,
                )
                .join(
                    CalendarConnection,
                    CalendarConnection.id == AccountingMirrorTarget.google_connection_id,
                )
                .where(
                    AccountingMirrorTarget.enabled.is_(True),
                    or_(
                        AccountingMirrorRefresh.status == "PENDING",
                        and_(
                            AccountingMirrorRefresh.status == "FAILED",
                            AccountingMirrorRefresh.retry_at.is_not(None),
                            AccountingMirrorRefresh.retry_at <= stamp,
                        ),
                        and_(
                            AccountingMirrorRefresh.status == "PROCESSING",
                            AccountingMirrorRefresh.lease_until < stamp,
                        ),
                    ),
                )
                .order_by(AccountingMirrorRefresh.updated_at, AccountingMirrorRefresh.id)
                .limit(1)
                .with_for_update(skip_locked=True, of=AccountingMirrorRefresh)
            )
        ).first()
        if not row:
            return None
        refresh, target, connection = row
        claimed_from_status = refresh.status
        token = uuid4()
        refresh.status = "PROCESSING"
        refresh.claim_token = token
        refresh.claimed_at = stamp
        refresh.lease_until = stamp + LEASE
        refresh.attempt_count += 1
        refresh.provider_attempted_at = None
        refresh.last_error_code = None
        refresh.retry_at = None
        return Claim(
            refresh_id=refresh.id,
            claim_token=token,
            requested_generation=refresh.requested_generation,
            claimed_from_status=claimed_from_status,
            attempt_count=refresh.attempt_count,
            kind=target.kind,
            technician_id=target.technician_id,
            target_id=target.id,
            target_generation=target.generation,
            spreadsheet_id=target.spreadsheet_id,
            connection_id=connection.id,
            connection_generation=connection.generation,
            encrypted_refresh_token=connection.encrypted_refresh_token,
            granted_scopes=tuple(connection.granted_scopes),
            week_start=refresh.week_start,
            google_sheet_id=refresh.google_sheet_id,
            owned_rows=refresh.owned_rows,
            owned_columns=refresh.owned_columns,
            last_fingerprint=refresh.last_successful_fingerprint,
            last_success_at=refresh.last_success_at,
            successful_target_generation=refresh.successful_target_generation,
            successful_connection_generation=refresh.successful_connection_generation,
        )


async def build_payload(factory, current: Claim):
    async with factory() as db, db.begin():
        if current.kind == "INDIVIDUAL":
            accounting = await calculate(db, current.technician_id, "weekly", current.week_start)
            return individual_payload(WeeklyAccountingXlsxModel.from_accounting(accounting))
        accounting = await calculate_all_weekly(db, current.week_start)
        models = tuple(WeeklyAccountingXlsxModel.from_accounting(item) for item in accounting)
        return all_tech_payload(models, current.week_start)


async def mark_provider_attempt(factory, current: Claim) -> bool:
    async with factory() as db, db.begin():
        refresh = await db.get(AccountingMirrorRefresh, current.refresh_id, with_for_update=True)
        if (
            not refresh
            or refresh.status != "PROCESSING"
            or refresh.claim_token != current.claim_token
        ):
            return False
        refresh.provider_attempted_at = await db.scalar(select(func.clock_timestamp()))
        return True


async def renew_claim_lease(factory, current: Claim) -> bool:
    """Extend only the active owner's lease using the database clock."""
    async with factory() as db, db.begin():
        refresh = await db.get(AccountingMirrorRefresh, current.refresh_id, with_for_update=True)
        if (
            not refresh
            or refresh.status != "PROCESSING"
            or refresh.claim_token != current.claim_token
        ):
            return False
        stamp = await db.scalar(select(func.clock_timestamp()))
        refresh.lease_until = stamp + LEASE
        return True


async def maintain_claim_lease(factory, current: Claim, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), LEASE_RENEW_INTERVAL_SECONDS)
            break
        except TimeoutError:
            pass
        try:
            if not await renew_claim_lease(factory, current):
                return
        except Exception:
            logger.warning(
                "accounting_mirror target_id=%s week_start=%s lease=RENEWAL_UNAVAILABLE",
                current.target_id,
                current.week_start,
            )


def choose_sheet(metadata: tuple[SheetMetadata, ...], current: Claim, title: str):
    if current.google_sheet_id is not None:
        found = next((item for item in metadata if item.sheet_id == current.google_sheet_id), None)
        if found:
            return found
    return next((item for item in metadata if item.title == title), None)


async def persist_rotated_credential(factory, settings, current: Claim, old_token: str, grant):
    if not grant.refresh_token or grant.refresh_token == old_token:
        return
    cipher = SecretCipher(settings.google_calendar_credential_encryption_key.get_secret_value())
    async with factory() as db, db.begin():
        connection = await db.get(CalendarConnection, current.connection_id, with_for_update=True)
        if connection and connection.generation == current.connection_generation:
            connection.encrypted_refresh_token = cipher.encrypt(grant.refresh_token)
            connection.granted_scopes = list(grant.scopes)


async def finalize_success(factory, current: Claim, payload, sheet: SheetMetadata) -> None:
    async with factory() as db, db.begin():
        refresh = await db.get(AccountingMirrorRefresh, current.refresh_id, with_for_update=True)
        if (
            not refresh
            or refresh.status != "PROCESSING"
            or refresh.claim_token != current.claim_token
        ):
            return
        target = await db.get(AccountingMirrorTarget, current.target_id)
        connection = await db.get(CalendarConnection, current.connection_id)
        valid = bool(
            target
            and target.enabled
            and target.generation == current.target_generation
            and target.spreadsheet_id == current.spreadsheet_id
            and connection
            and connection.generation == current.connection_generation
            and connection.is_current
        )
        refresh.completed_generation = max(
            refresh.completed_generation, current.requested_generation
        )
        refresh.google_sheet_id = sheet.sheet_id
        refresh.owned_rows = payload.row_count
        refresh.owned_columns = payload.column_count
        refresh.last_successful_fingerprint = payload.fingerprint
        refresh.successful_target_generation = current.target_generation
        refresh.successful_connection_generation = current.connection_generation
        refresh.last_success_at = await db.scalar(select(func.clock_timestamp()))
        refresh.last_error_code = None
        refresh.retry_at = None
        refresh.status = (
            "SUCCEEDED"
            if valid and refresh.requested_generation <= current.requested_generation
            else "PENDING"
        )
        refresh.claim_token = refresh.claimed_at = refresh.lease_until = None


async def finalize_failure(
    factory, current: Claim, code: str, *, retryable: bool, retry_after: int = 60
) -> None:
    async with factory() as db, db.begin():
        refresh = await db.get(AccountingMirrorRefresh, current.refresh_id, with_for_update=True)
        if (
            not refresh
            or refresh.status != "PROCESSING"
            or refresh.claim_token != current.claim_token
        ):
            return
        stamp = await db.scalar(select(func.clock_timestamp()))
        refresh.status = "FAILED"
        refresh.last_error_code = code
        refresh.retry_at = (
            stamp
            + timedelta(
                seconds=max(retry_after, min(1800, 30 * 2 ** min(current.attempt_count, 6)))
            )
            if retryable
            else None
        )
        refresh.claim_token = refresh.claimed_at = refresh.lease_until = None


async def process_claim(factory, settings, google_provider, current: Claim) -> bool:
    lease_stop = asyncio.Event()
    lease_task = asyncio.create_task(maintain_claim_lease(factory, current, lease_stop))
    try:
        if (
            not current.encrypted_refresh_token
            or SHEETS_SCOPE not in current.granted_scopes
            or google_provider is None
        ):
            raise SheetsProviderError("SHEETS_PERMISSION_REQUIRED")
        payload = await build_payload(factory, current)
        if not await mark_provider_attempt(factory, current):
            return False
        cipher = SecretCipher(settings.google_calendar_credential_encryption_key.get_secret_value())
        refresh_token = cipher.decrypt(current.encrypted_refresh_token)
        grant = await google_provider.refresh_credentials(
            refresh_token, scopes=current.granted_scopes
        )
        if SHEETS_SCOPE not in grant.scopes:
            raise SheetsProviderError("SHEETS_PERMISSION_REQUIRED")
        await persist_rotated_credential(factory, settings, current, refresh_token, grant)
        metadata = await google_provider.get_spreadsheet_metadata(
            grant.access_token, current.spreadsheet_id
        )
        sheet = choose_sheet(metadata, current, payload.title)
        if sheet is None:
            sheet = await google_provider.add_sheet(
                grant.access_token,
                current.spreadsheet_id,
                payload.title,
                payload.row_count,
                payload.column_count,
            )
        known_current = (
            current.claimed_from_status != "FAILED"
            and current.last_success_at is not None
            and current.last_fingerprint == payload.fingerprint
            and current.successful_target_generation == current.target_generation
            and current.successful_connection_generation == current.connection_generation
            and current.google_sheet_id == sheet.sheet_id
        )
        if not known_current:
            await google_provider.clear_owned_range(
                grant.access_token,
                current.spreadsheet_id,
                sheet.sheet_id,
                max(current.owned_rows, payload.row_count),
                max(current.owned_columns, payload.column_count),
            )
            await google_provider.write_values(
                grant.access_token,
                current.spreadsheet_id,
                sheet.title,
                payload.values,
            )
            await google_provider.batch_update_formatting(
                grant.access_token,
                current.spreadsheet_id,
                sheet.sheet_id,
                payload,
                sheet.rows,
                sheet.columns,
            )
        await finalize_success(factory, current, payload, sheet)
        logger.info(
            "accounting_mirror target_id=%s week_start=%s generation=%d result=SUCCESS",
            current.target_id,
            current.week_start,
            current.requested_generation,
        )
        return True
    except SheetsProviderError as exc:
        await finalize_failure(
            factory,
            current,
            exc.code,
            retryable=exc.retryable,
            retry_after=exc.retry_after,
        )
    except ProviderError as exc:
        await finalize_failure(
            factory,
            current,
            "SHEETS_PERMISSION_REQUIRED"
            if exc.code in {"REAUTH_REQUIRED", "SCOPE_REQUIRED"}
            else "PROVIDER_TEMPORARY_ERROR",
            retryable=exc.code not in {"REAUTH_REQUIRED", "SCOPE_REQUIRED", "CONFIGURATION_ERROR"},
            retry_after=exc.retry_after,
        )
    except Exception:
        await finalize_failure(factory, current, "PROVIDER_TEMPORARY_ERROR", retryable=True)
    finally:
        lease_stop.set()
        lease_task.cancel()
        try:
            await lease_task
        except asyncio.CancelledError:
            pass
    logger.warning(
        "accounting_mirror target_id=%s week_start=%s generation=%d result=FAILED",
        current.target_id,
        current.week_start,
        current.requested_generation,
    )
    return False


async def run_once(factory, settings, google_provider, *, limit: int = 100) -> list[bool]:
    results = []
    for _ in range(limit):
        current = await claim(factory)
        if current is None:
            break
        results.append(await process_claim(factory, settings, google_provider, current))
    return results


class Worker:
    def __init__(self, factory, settings, provider):
        self.factory = factory
        self.settings = settings
        self.provider = provider
        self.id = uuid4()
        self.stop = asyncio.Event()

    async def beat(self, status="RUNNING", error=None):
        async with self.factory() as db, db.begin():
            statement = insert(AccountingMirrorWorkerState).values(
                worker_id=self.id,
                status=status,
                heartbeat_at=func.clock_timestamp(),
                last_error_code=error,
            )
            await db.execute(
                statement.on_conflict_do_update(
                    index_elements=[AccountingMirrorWorkerState.worker_id],
                    set_={
                        "status": status,
                        "heartbeat_at": func.clock_timestamp(),
                        "last_error_code": error,
                    },
                )
            )

    async def heartbeat(self):
        while not self.stop.is_set():
            try:
                await self.beat()
            except Exception:
                logger.warning("accounting_mirror_worker heartbeat=UNAVAILABLE")
            try:
                await asyncio.wait_for(self.stop.wait(), 30)
            except TimeoutError:
                pass

    async def run(self):
        await self.beat("STARTING")
        heartbeat = asyncio.create_task(self.heartbeat())
        try:
            while not self.stop.is_set():
                await self.beat()
                results = await run_once(self.factory, self.settings, self.provider)
                if not results:
                    try:
                        await asyncio.wait_for(self.stop.wait(), 5)
                    except TimeoutError:
                        pass
        finally:
            self.stop.set()
            heartbeat.cancel()
            try:
                await heartbeat
            except asyncio.CancelledError:
                pass
            await self.beat("STOPPED")


async def main():
    settings = Settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True, hide_parameters=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    provider = None
    if settings.google_mode == "real":
        from hub.google_calendar.provider import GoogleCalendarProvider

        provider = GoogleCalendarProvider(settings)
    elif settings.google_mode == "fake":
        from hub.google_calendar.fake import FakeCalendarProvider

        provider = FakeCalendarProvider()
    try:
        await Worker(factory, settings, provider).run()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
