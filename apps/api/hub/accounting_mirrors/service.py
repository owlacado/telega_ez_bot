import re
from datetime import date, timedelta
from urllib.parse import urlparse
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import case, delete, func, select
from sqlalchemy.dialects.postgresql import insert

from hub.accounting.domain import monday, shift
from hub.accounting_mirrors.models import (
    AccountingMirrorRefresh,
    AccountingMirrorTarget,
    AccountingMirrorWorkerState,
)
from hub.accounting_mirrors.provider import SHEETS_SCOPE
from hub.accounting_mirrors.schemas import MirrorStatusRead
from hub.audit.service import audit
from hub.google_calendar.models import CalendarConnection
from hub.technicians.models import Technician

SPREADSHEET_ID = re.compile(r"[A-Za-z0-9_-]{10,200}")


def normalize_spreadsheet_id(value: str) -> str:
    value = value.strip()
    if "://" in value:
        try:
            parsed = urlparse(value)
            hostname, port = parsed.hostname, parsed.port
        except ValueError:
            raise HTTPException(
                422, "Enter a Google Spreadsheet ID or Google Sheets URL."
            ) from None
        parts = [part for part in parsed.path.split("/") if part]
        if (
            parsed.scheme != "https"
            or hostname != "docs.google.com"
            or len(parts) < 3
            or parts[:2] != ["spreadsheets", "d"]
            or parsed.username
            or port not in {None, 443}
        ):
            raise HTTPException(422, "Enter a Google Spreadsheet ID or Google Sheets URL.")
        value = parts[2]
    if not SPREADSHEET_ID.fullmatch(value):
        raise HTTPException(422, "Enter a valid Google Spreadsheet ID.")
    return value


def open_url(identifier: str) -> str:
    return f"https://docs.google.com/spreadsheets/d/{identifier}"


def validate_week(start: date) -> None:
    if start.weekday() != 0 or shift(start, 6) is None:
        raise HTTPException(422, "week_start must be a Monday with seven representable dates.")


async def current_connection(db):
    return await db.scalar(
        select(CalendarConnection).where(CalendarConnection.is_current.is_(True))
    )


def target_filter(kind: str, technician_id: UUID | None):
    return (
        AccountingMirrorTarget.kind == kind,
        AccountingMirrorTarget.technician_id == technician_id,
    )


async def get_target(db, kind: str, technician_id: UUID | None, *, lock=False):
    statement = select(AccountingMirrorTarget).where(*target_filter(kind, technician_id))
    if lock:
        statement = statement.with_for_update()
    return await db.scalar(statement)


async def enqueue_target(db, target_id: UUID, week_start: date) -> None:
    validate_week(week_start)
    table = AccountingMirrorRefresh.__table__
    statement = insert(table).values(
        target_id=target_id,
        week_start=week_start,
        requested_generation=1,
        completed_generation=0,
        status="PENDING",
    )
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=[table.c.target_id, table.c.week_start],
            set_={
                "requested_generation": table.c.requested_generation + 1,
                "status": case((table.c.status == "PROCESSING", "PROCESSING"), else_="PENDING"),
                "retry_at": None,
                "last_error_code": None,
                "updated_at": func.clock_timestamp(),
            },
        )
    )


async def enqueue_for_business_change(db, technician_id: UUID, business_date: date) -> None:
    start = monday(business_date)
    targets = (
        await db.scalars(
            select(AccountingMirrorTarget.id).where(
                AccountingMirrorTarget.enabled.is_(True),
                (
                    (AccountingMirrorTarget.kind == "ALL_TECH")
                    | (
                        (AccountingMirrorTarget.kind == "INDIVIDUAL")
                        & (AccountingMirrorTarget.technician_id == technician_id)
                    )
                ),
            )
        )
    ).all()
    for target_id in targets:
        await enqueue_target(db, target_id, start)


async def configure(
    db,
    *,
    kind: str,
    technician_id: UUID | None,
    spreadsheet: str,
    replace: bool,
    manager_id: UUID,
) -> AccountingMirrorTarget:
    identifier = normalize_spreadsheet_id(spreadsheet)
    if technician_id and not await db.get(Technician, technician_id):
        raise HTTPException(404, "Technician not found.")
    connection = await db.scalar(
        select(CalendarConnection).where(CalendarConnection.is_current.is_(True)).with_for_update()
    )
    if not connection or connection.status == "DISCONNECTED":
        raise HTTPException(409, "Connect Google before configuring a mirror.")
    target = await get_target(db, kind, technician_id, lock=True)
    conflict_query = select(AccountingMirrorTarget.id).where(
        AccountingMirrorTarget.spreadsheet_id == identifier
    )
    if target:
        conflict_query = conflict_query.where(AccountingMirrorTarget.id != target.id)
    conflict = await db.scalar(conflict_query)
    if conflict:
        raise HTTPException(
            409,
            "This Spreadsheet is already assigned to another accounting mirror.",
        )
    if target is None:
        target = AccountingMirrorTarget(
            kind=kind,
            technician_id=technician_id,
            google_connection_id=connection.id,
            spreadsheet_id=identifier,
            enabled=True,
        )
        db.add(target)
        action = "accounting_mirror.configured"
    else:
        changed = (
            target.spreadsheet_id != identifier or target.google_connection_id != connection.id
        )
        if changed and not replace:
            raise HTTPException(409, "Confirm replacement of the configured Spreadsheet.")
        if changed:
            target.spreadsheet_id = identifier
            target.google_connection_id = connection.id
            target.generation += 1
            await db.execute(
                delete(AccountingMirrorRefresh).where(
                    AccountingMirrorRefresh.target_id == target.id
                )
            )
            action = "accounting_mirror.replaced"
        else:
            action = "accounting_mirror.configured"
        target.enabled = True
    await db.flush()
    audit(db, action, target.id, actor_id=manager_id)
    return target


async def action(
    db,
    *,
    kind: str,
    technician_id: UUID | None,
    week_start: date,
    requested_action: str,
    expected_generation: int,
    manager_id: UUID,
) -> None:
    validate_week(week_start)
    target = await get_target(db, kind, technician_id, lock=True)
    if not target:
        raise HTTPException(404, "Mirror is not configured.")
    if target.generation != expected_generation:
        raise HTTPException(409, "Mirror configuration changed. Refresh and try again.")
    if requested_action == "REMOVE":
        identifier = target.id
        await db.delete(target)
        audit(db, "accounting_mirror.removed", identifier, actor_id=manager_id)
        return
    if requested_action == "DISABLE":
        target.enabled = False
        target.generation += 1
        audit(db, "accounting_mirror.disabled", target.id, actor_id=manager_id)
        return
    if requested_action == "ENABLE":
        target.enabled = True
        target.generation += 1
        audit(db, "accounting_mirror.enabled", target.id, actor_id=manager_id)
        return
    if not target.enabled:
        raise HTTPException(409, "Enable the mirror before syncing.")
    await enqueue_target(db, target.id, week_start)
    audit(db, "accounting_mirror.sync_requested", target.id, actor_id=manager_id)


async def worker_state(db) -> str:
    cutoff = func.clock_timestamp() - timedelta(seconds=120)
    running = await db.scalar(
        select(func.count())
        .select_from(AccountingMirrorWorkerState)
        .where(
            AccountingMirrorWorkerState.status == "RUNNING",
            AccountingMirrorWorkerState.heartbeat_at >= cutoff,
        )
    )
    if running:
        return "RUNNING"
    latest = await db.scalar(
        select(AccountingMirrorWorkerState).order_by(
            AccountingMirrorWorkerState.heartbeat_at.desc()
        )
    )
    if latest is None:
        return "MISSING"
    if latest.status in {"STOPPED", "ERROR"}:
        return latest.status
    return "STALE"


async def status(
    db, *, kind: str, technician_id: UUID | None, week_start: date
) -> MirrorStatusRead:
    validate_week(week_start)
    if kind == "INDIVIDUAL" and not await db.get(Technician, technician_id):
        raise HTTPException(404, "Technician not found.")
    target = await get_target(db, kind, technician_id)
    connection = await current_connection(db)
    if not connection:
        auth_state = "NOT_CONNECTED"
    elif target and target.google_connection_id != connection.id:
        auth_state = "NEEDS_AUTH"
    elif connection.status != "CONNECTED":
        auth_state = "NEEDS_AUTH"
    elif SHEETS_SCOPE not in connection.granted_scopes:
        auth_state = "NEEDS_PERMISSION"
    else:
        auth_state = "READY"
    refresh = None
    if target:
        refresh = await db.scalar(
            select(AccountingMirrorRefresh).where(
                AccountingMirrorRefresh.target_id == target.id,
                AccountingMirrorRefresh.week_start == week_start,
            )
        )
    if not target:
        state = "NOT_CONFIGURED"
    elif auth_state in {"NEEDS_AUTH", "NOT_CONNECTED"}:
        state = "NEEDS_AUTH"
    elif auth_state == "NEEDS_PERMISSION":
        state = "NEEDS_PERMISSION"
    elif not target.enabled:
        state = "DISABLED"
    elif refresh is None:
        state = "READY"
    elif refresh.status == "PROCESSING":
        state = "SYNCING"
    elif refresh.requested_generation > refresh.completed_generation:
        state = "FAILED" if refresh.status == "FAILED" else "PENDING"
    elif (
        refresh.status == "SUCCEEDED"
        and refresh.successful_target_generation == target.generation
        and refresh.successful_connection_generation == connection.generation
    ):
        state = "SYNCED"
    else:
        state = "READY"
    return MirrorStatusRead(
        kind=kind,
        technician_id=technician_id,
        week_start=week_start,
        week_end=shift(week_start, 6),
        configured=target is not None,
        enabled=bool(target and target.enabled),
        target_id=target.id if target else None,
        target_generation=target.generation if target else None,
        spreadsheet_id=target.spreadsheet_id if target else None,
        open_url=open_url(target.spreadsheet_id) if target else None,
        auth_state=auth_state,
        state=state,
        requested_generation=refresh.requested_generation if refresh else None,
        completed_generation=refresh.completed_generation if refresh else None,
        pending_newer_generation=bool(
            refresh and refresh.requested_generation > refresh.completed_generation
        ),
        last_success_at=refresh.last_success_at if refresh else None,
        last_attempt_at=refresh.provider_attempted_at if refresh else None,
        last_error_code=refresh.last_error_code if refresh else None,
        google_sheet_id=refresh.google_sheet_id if refresh else None,
        worker_state=await worker_state(db),
    )
