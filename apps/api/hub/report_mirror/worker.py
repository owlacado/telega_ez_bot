"""Bounded report projection lane in the existing Google mirror worker.

Every attempt refetches the source and conditionally replaces one managed block.
A crash/timeout is safe to reconcile; nothing ever blindly appends on retry.
"""

from datetime import timedelta
from uuid import uuid4

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from hub.calendars.models import Calendar
from hub.core.secrets import SecretCipher
from hub.google_calendar.models import CalendarConnection
from hub.google_calendar.types import REPORT_WRITE_SCOPE, ProviderError
from hub.report_mirror.models import ReportCalendarMirror
from hub.report_mirror.presentation import merge, render
from hub.telegram.locks import advisory_guard
from hub.work_reports.models import WorkReport, WorkReportRevision


async def claim(factory):
    async with factory() as db, db.begin():
        stamp = await db.scalar(select(func.clock_timestamp()))
        row = await db.scalar(
            select(ReportCalendarMirror)
            .where(
                or_(
                    ReportCalendarMirror.status.in_(["PENDING", "BLOCKED"]),
                    (ReportCalendarMirror.status == "PROCESSING")
                    & (ReportCalendarMirror.lease_until < stamp),
                ),
                ReportCalendarMirror.available_at <= stamp,
            )
            .order_by(ReportCalendarMirror.available_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if not row:
            return None
        row.status, row.claim_token, row.lease_until = (
            "PROCESSING",
            uuid4(),
            stamp + timedelta(minutes=5),
        )
        row.attempts += 1
        return row


async def finish(factory, claim, error=None, revision=None):
    async with factory() as db, db.begin():
        row = await db.get(ReportCalendarMirror, claim.report_id, with_for_update=True)
        if not row or row.claim_token != claim.claim_token or row.status != "PROCESSING":
            return
        stamp = await db.scalar(select(func.clock_timestamp()))
        row.claim_token, row.lease_until = None, None
        row.error_code = error
        if error:
            row.status = "BLOCKED"
            row.available_at = stamp + timedelta(minutes=5)
        else:
            row.synced_revision, row.synced_at = revision, stamp
            row.status = "SYNCED" if row.requested_revision == revision else "PENDING"
            row.available_at = stamp


async def snapshot(factory, current):
    async with factory() as db:
        row = await db.get(ReportCalendarMirror, current.report_id)
        stamp = await db.scalar(select(func.clock_timestamp()))
        if (
            not row
            or row.claim_token != current.claim_token
            or row.status != "PROCESSING"
            or row.lease_until <= stamp
        ):
            raise ValueError("CLAIM_LOST")
        report = await db.get(WorkReport, current.report_id)
        revision = await db.scalar(
            select(WorkReportRevision).where(
                WorkReportRevision.report_id == report.id,
                WorkReportRevision.revision_number == report.current_revision_number,
            )
        )
        calendar = await db.get(Calendar, current.calendar_id)
        connection = await db.get(CalendarConnection, current.connection_id)
        if (
            not connection
            or not connection.is_current
            or connection.status != "CONNECTED"
            or not connection.encrypted_refresh_token
            or not calendar
            or calendar.excluded_at
            or calendar.availability != "AVAILABLE"
            or calendar.access_role not in {"writer", "owner"}
            or calendar.provider_connection_id != current.connection_id
            or calendar.provider_calendar_id != current.provider_calendar_id
            or report.calendar_id != current.calendar_id
            or not revision
            or revision.provider_event_id != current.provider_event_id
        ):
            raise ValueError("SOURCE_UNAVAILABLE")
        if REPORT_WRITE_SCOPE not in connection.granted_scopes:
            raise ValueError("REPORT_WRITE_SCOPE_REQUIRED")
        duplicates = await db.scalar(
            select(func.count())
            .select_from(ReportCalendarMirror)
            .where(
                ReportCalendarMirror.connection_id == current.connection_id,
                ReportCalendarMirror.provider_calendar_id == current.provider_calendar_id,
                ReportCalendarMirror.provider_event_id == current.provider_event_id,
            )
        )
        if duplicates != 1:
            raise ValueError("SOURCE_REPORT_CONFLICT")
        return connection, revision


async def process(factory, settings, provider, current, locks):
    try:
        # Same lifecycle guard as reconnect/switch/disconnect; no business transaction during I/O.
        async with advisory_guard(locks, "google-lifecycle", 0):
            async with advisory_guard(
                locks, "google-report:" + current.provider_calendar_id, current.provider_event_id
            ):
                connection, revision = await snapshot(factory, current)
                cipher = SecretCipher(
                    settings.google_calendar_credential_encryption_key.get_secret_value()
                )
                refresh = cipher.decrypt(connection.encrypted_refresh_token)
                grant = await provider.refresh_credentials(
                    refresh, scopes=tuple(connection.granted_scopes)
                )
                if grant.refresh_token and grant.refresh_token != refresh:
                    async with factory() as db, db.begin():
                        latest = await db.get(
                            CalendarConnection, connection.id, with_for_update=True
                        )
                        latest.encrypted_refresh_token = cipher.encrypt(grant.refresh_token)
                if REPORT_WRITE_SCOPE not in grant.scopes:
                    raise ValueError("REPORT_WRITE_SCOPE_REQUIRED")
                event = await provider.get_report_event(
                    grant.access_token, current.provider_calendar_id, current.provider_event_id
                )
                if (
                    event.get("id") != current.provider_event_id
                    or event.get("status") == "cancelled"
                    or not isinstance(event.get("etag"), str)
                    or not event["etag"]
                    or not isinstance(event.get("description", ""), str)
                    or event.get("recurringEventId") != revision.recurring_event_id
                ):
                    raise ValueError("SOURCE_EVENT_CHANGED")
                # Recheck current canonical revision after read; an intervening revision is retried.
                _, latest_revision = await snapshot(factory, current)
                if latest_revision.id != revision.id:
                    raise ValueError("REVISION_CHANGED")
                description = event.get("description", "")
                updated = merge(description, render(revision))
                if updated != description:
                    await provider.patch_report_description(
                        grant.access_token,
                        current.provider_calendar_id,
                        current.provider_event_id,
                        event["etag"],
                        updated,
                    )
                await finish(factory, current, revision=revision.revision_number)
    except Exception as exc:
        safe = {
            "CLAIM_LOST",
            "SOURCE_UNAVAILABLE",
            "REPORT_WRITE_SCOPE_REQUIRED",
            "SOURCE_REPORT_CONFLICT",
            "SOURCE_EVENT_CHANGED",
            "REVISION_CHANGED",
            "MANAGED_BLOCK_MALFORMED",
        }
        code = (
            str(exc)
            if isinstance(exc, ValueError) and str(exc) in safe
            else (exc.code if isinstance(exc, ProviderError) else "PROVIDER_TEMPORARY_ERROR")
        )
        await finish(factory, current, error=code)


async def run_once(factory, settings, provider, *, limit=10):
    if settings.google_mode == "disabled":
        return []
    locks = create_async_engine(factory.kw["bind"].url, poolclass=NullPool, hide_parameters=True)
    results = []
    try:
        for _ in range(limit):
            current = await claim(factory)
            if current is None:
                break
            await process(factory, settings, provider, current, locks)
            results.append(True)
        return results
    finally:
        await locks.dispose()
