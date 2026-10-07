from datetime import timedelta

from sqlalchemy import delete, func, select, text, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession

from hub.accounting_mirrors.models import (
    AccountingMirrorRefresh,
    AccountingMirrorWorkerState,
)
from hub.auth.models import RateBucket
from hub.core.config import Settings
from hub.core.migrations import ReleaseMigrationError, release_migration_head
from hub.google_calendar.models import GoogleOAuthAttempt
from hub.ops.schemas import CleanupResult, ComponentHealth, OperationsHealth, QueueCounts
from hub.schedule_delivery.models import ScheduleDispatch, ScheduleWorkerState
from hub.telegram.models import TelegramOutbox, TelegramProcessedUpdate, TelegramWorkerState
from hub.work_reports.models import TechnicianFormSession

FRESH_SECONDS = 120


def _worker_component(status: str | None, fresh: bool, *, disabled: bool) -> ComponentHealth:
    if disabled:
        return ComponentHealth(state="DISABLED", message="Feature is intentionally disabled.")
    if status is None:
        return ComponentHealth(state="MISSING", message="No worker heartbeat is recorded.")
    if not fresh:
        return ComponentHealth(state="STALE", message="Worker heartbeat is stale.")
    if status in {"RUNNING", "STARTING"}:
        return ComponentHealth(state="RUNNING", message="Worker heartbeat is current.")
    if status == "STOPPED":
        return ComponentHealth(state="STOPPED", message="Worker stopped cleanly.")
    return ComponentHealth(state="ERROR", message="Worker reported an operational error.")


async def _latest_worker(db: AsyncSession, model, heartbeat_column, status_column):
    row = await db.scalar(select(model).order_by(heartbeat_column.desc()).limit(1))
    if row is None:
        return None, False
    stamp = await db.scalar(select(func.clock_timestamp()))
    heartbeat = getattr(row, heartbeat_column.key)
    return getattr(row, status_column), bool(
        heartbeat and stamp - heartbeat <= timedelta(seconds=FRESH_SECONDS)
    )


async def _queue_counts(db: AsyncSession, model, status_column, mappings) -> QueueCounts:
    values = {}
    for output, states in mappings.items():
        if not states:
            values[output] = 0
            continue
        values[output] = int(
            await db.scalar(
                select(func.count()).select_from(model).where(status_column.in_(states))
            )
            or 0
        )
    return QueueCounts(**values)


async def migration_health(db: AsyncSession) -> ComponentHealth:
    try:
        expected = release_migration_head()
    except ReleaseMigrationError:
        return ComponentHealth(
            state="BLOCK", message="Release migration graph must have exactly one valid head."
        )
    heads = list((await db.scalars(text("SELECT version_num FROM alembic_version"))).all())
    matches = heads == [expected]
    return ComponentHealth(
        state="PASS" if matches else "BLOCK",
        message=(
            f"Database schema is at {expected}."
            if matches
            else "Database schema does not match this release's single migration head."
        ),
    )


async def operations_health(db: AsyncSession, settings: Settings) -> OperationsHealth:
    await db.execute(select(1))
    migration = await migration_health(db)
    telegram_status, telegram_fresh = await _latest_worker(
        db, TelegramWorkerState, TelegramWorkerState.heartbeat_at, "status"
    )
    schedule_status, schedule_fresh = await _latest_worker(
        db, ScheduleWorkerState, ScheduleWorkerState.heartbeat_at, "status"
    )
    mirror_status, mirror_fresh = await _latest_worker(
        db, AccountingMirrorWorkerState, AccountingMirrorWorkerState.heartbeat_at, "status"
    )
    telegram = _worker_component(
        telegram_status, telegram_fresh, disabled=settings.telegram_mode == "disabled"
    )
    schedule = _worker_component(
        schedule_status, schedule_fresh, disabled=not settings.schedule_delivery_enabled
    )
    mirror = _worker_component(
        mirror_status, mirror_fresh, disabled=settings.google_mode == "disabled"
    )
    google = ComponentHealth(
        state="PASS" if settings.google_mode == "real" else "DISABLED",
        message=(
            "Google provider configuration is present; connectivity is not probed."
            if settings.google_mode == "real"
            else "Google provider is intentionally disabled."
        ),
    )
    queues = {
        "telegram": await _queue_counts(
            db,
            TelegramOutbox,
            TelegramOutbox.state,
            {
                "pending": ["QUEUED"],
                "processing": ["PROCESSING"],
                "failed": ["FAILED"],
                "ambiguous": ["UNKNOWN"],
            },
        ),
        "schedule": await _queue_counts(
            db,
            ScheduleDispatch,
            ScheduleDispatch.status,
            {
                "pending": ["PENDING"],
                "processing": ["PROCESSING"],
                "failed": ["FAILED"],
                "ambiguous": ["AMBIGUOUS"],
            },
        ),
        "mirror": await _queue_counts(
            db,
            AccountingMirrorRefresh,
            AccountingMirrorRefresh.status,
            {
                "pending": ["PENDING"],
                "processing": ["PROCESSING"],
                "failed": ["FAILED"],
                "ambiguous": [],
            },
        ),
    }
    required_workers = [
        component
        for component, enabled in [
            (telegram, settings.telegram_mode != "disabled"),
            (schedule, settings.schedule_delivery_enabled),
            (mirror, settings.google_mode != "disabled"),
        ]
        if enabled
    ]
    status = "PASS"
    if migration.state == "BLOCK":
        status = "BLOCK"
    elif any(component.state != "RUNNING" for component in required_workers) or any(
        queue.failed or queue.ambiguous for queue in queues.values()
    ):
        status = "WARN"
    return OperationsHealth(
        status=status,
        app_version=settings.app_version,
        release_commit=settings.release_commit,
        database=ComponentHealth(state="PASS", message="PostgreSQL query succeeded."),
        migration=migration,
        telegram_worker=telegram,
        schedule_worker=schedule,
        mirror_worker=mirror,
        google_configuration=google,
        queues=queues,
    )


async def cleanup_expired(
    db: AsyncSession,
    *,
    apply: bool = False,
    batch_size: int = 100,
    settings: Settings | None = None,
) -> CleanupResult:
    settings = settings or Settings()
    batch_size = min(max(batch_size, 1), 1000)
    stamp = await db.scalar(select(func.clock_timestamp()))
    form_ids = (
        await db.scalars(
            select(TechnicianFormSession.id)
            .where(
                TechnicianFormSession.expires_at <= stamp,
                TechnicianFormSession.status == "OPEN",
                (TechnicianFormSession.choices.is_not(None))
                | (TechnicianFormSession.selected.is_not(None)),
            )
            .order_by(TechnicianFormSession.expires_at, TechnicianFormSession.id)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
    ).all()
    oauth_ids = (
        await db.scalars(
            select(GoogleOAuthAttempt.id)
            .where(
                GoogleOAuthAttempt.encrypted_verifier.is_not(None),
                (GoogleOAuthAttempt.expires_at <= stamp)
                | (GoogleOAuthAttempt.consumed_at.is_not(None)),
            )
            .order_by(GoogleOAuthAttempt.expires_at, GoogleOAuthAttempt.id)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
    ).all()
    payload_query = (
        select(ScheduleDispatch.id)
        .where(
            ScheduleDispatch.payload_expires_at <= stamp,
            ScheduleDispatch.encrypted_payload.is_not(None),
            ScheduleDispatch.status.in_(["FAILED", "AMBIGUOUS", "CANCELLED"]),
        )
        .order_by(ScheduleDispatch.payload_expires_at, ScheduleDispatch.id)
        .limit(batch_size)
        .with_for_update(skip_locked=True)
    )
    payload_ids = (await db.scalars(payload_query)).all()
    oauth_metadata_ids = (
        await db.scalars(
            select(GoogleOAuthAttempt.id)
            .where(
                GoogleOAuthAttempt.encrypted_verifier.is_(None),
                GoogleOAuthAttempt.created_at
                <= stamp - timedelta(days=settings.google_oauth_attempt_retention_days),
            )
            .order_by(GoogleOAuthAttempt.created_at, GoogleOAuthAttempt.id)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
    ).all()
    processed_ids = (
        await db.execute(
            select(TelegramProcessedUpdate.bot_id, TelegramProcessedUpdate.update_id)
            .join(
                TelegramWorkerState,
                TelegramWorkerState.bot_id == TelegramProcessedUpdate.bot_id,
            )
            .where(
                TelegramProcessedUpdate.processed_at
                <= stamp - timedelta(days=settings.telegram_processed_update_retention_days),
                TelegramWorkerState.next_update_id.is_not(None),
                TelegramProcessedUpdate.update_id < TelegramWorkerState.next_update_id,
            )
            .order_by(
                TelegramProcessedUpdate.processed_at,
                TelegramProcessedUpdate.bot_id,
                TelegramProcessedUpdate.update_id,
            )
            .limit(batch_size)
            .with_for_update(of=TelegramProcessedUpdate, skip_locked=True)
        )
    ).all()
    rate_bucket_ids = (
        await db.scalars(
            select(RateBucket.key_hash)
            .where(RateBucket.window_start <= stamp - timedelta(days=7))
            .order_by(RateBucket.window_start, RateBucket.key_hash)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
    ).all()
    if apply:
        if form_ids:
            await db.execute(
                update(TechnicianFormSession)
                .where(TechnicianFormSession.id.in_(form_ids))
                .values(status="EXPIRED", choices=None, selected=None)
            )
        if oauth_ids:
            await db.execute(
                update(GoogleOAuthAttempt)
                .where(GoogleOAuthAttempt.id.in_(oauth_ids))
                .values(encrypted_verifier=None)
            )
        if payload_ids:
            await db.execute(
                update(ScheduleDispatch)
                .where(ScheduleDispatch.id.in_(payload_ids))
                .values(encrypted_payload=None)
            )
        if oauth_metadata_ids:
            await db.execute(
                delete(GoogleOAuthAttempt).where(GoogleOAuthAttempt.id.in_(oauth_metadata_ids))
            )
        if processed_ids:
            await db.execute(
                delete(TelegramProcessedUpdate).where(
                    tuple_(
                        TelegramProcessedUpdate.bot_id,
                        TelegramProcessedUpdate.update_id,
                    ).in_(processed_ids)
                )
            )
        if rate_bucket_ids:
            await db.execute(delete(RateBucket).where(RateBucket.key_hash.in_(rate_bucket_ids)))
    return CleanupResult(
        dry_run=not apply,
        expired_form_snapshots=len(form_ids),
        expired_oauth_verifiers=len(oauth_ids),
        expired_schedule_payloads=len(payload_ids),
        expired_oauth_attempt_metadata=len(oauth_metadata_ids),
        expired_telegram_processed_updates=len(processed_ids),
        expired_rate_buckets=len(rate_bucket_ids),
    )
