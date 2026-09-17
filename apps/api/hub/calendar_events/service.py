"""On-demand projection; short SQL snapshots bracket external provider requests."""

import logging
from datetime import UTC, datetime, timedelta
from time import monotonic

from fastapi import HTTPException
from sqlalchemy import select

from hub.audit.service import audit
from hub.auth.models import Manager, ManagerSession
from hub.auth.security import now
from hub.calendar_events.domain import (
    build_technician_schedule,
    calendar_zone,
    next_schedule_date,
    operational_window,
)
from hub.calendar_events.schemas import ScheduleCalendar, ScheduleRead, ScheduleTechnician
from hub.calendars.models import Calendar, CalendarAssignment
from hub.google_calendar import service as google
from hub.google_calendar.types import EVENT_SCOPE, SCOPE, ProviderError
from hub.technicians.models import Technician
from hub.telegram.locks import advisory_guard

logger = logging.getLogger(__name__)


async def snapshot(request, technician_id, preview=False):
    async with request.app.state.session_factory() as db:
        active = await db.scalar(
            select(ManagerSession.id)
            .join(Manager)
            .where(
                ManagerSession.id == request.state.session_id,
                ManagerSession.manager_id == request.state.manager_id,
                ManagerSession.revoked_at.is_(None),
                ManagerSession.expires_at > now(),
                Manager.is_active.is_(True),
            )
        )
        if active is None:
            raise HTTPException(401, "Authentication required.")
        tech = (
            await db.execute(
                select(Technician.id, Technician.first_name, Technician.last_name).where(
                    Technician.id == technician_id
                )
            )
        ).first()
        if tech is None:
            raise HTTPException(404, "Technician not found.")
        result = ScheduleRead(
            technician=ScheduleTechnician(
                id=tech.id, first_name=tech.first_name, last_name=tech.last_name
            ),
            state="NO_CALENDAR",
        )
        row = (
            await db.execute(
                select(Calendar, CalendarAssignment.id)
                .join(CalendarAssignment, CalendarAssignment.calendar_id == Calendar.id)
                .where(
                    CalendarAssignment.technician_id == technician_id,
                    CalendarAssignment.is_active.is_(True),
                )
            )
        ).first()
        if row is None:
            return result, None, None
        cal, assignment_id = row
        result.calendar = ScheduleCalendar(id=cal.id, name=cal.name)
        result.timezone = cal.timezone
        connection = await google.current(db)
        identity = (
            assignment_id,
            cal.id,
            cal.timezone,
            cal.excluded_at,
            cal.availability,
            connection.id if connection else None,
            connection.generation if connection else None,
            tuple(connection.granted_scopes) if connection else (),
        )
        # Determine date even for scope/error states so preview labels remain operational.
        try:
            today = now().astimezone(calendar_zone(cal.timezone)).date()
            result.next_schedule_date = next_schedule_date(today)
            result.operational_date = result.next_schedule_date if preview else today
        except ProviderError:
            pass
        if connection is not None and connection.status in {"REAUTH_REQUIRED", "DISCONNECTED"}:
            result.state = "REAUTH_REQUIRED"
        elif (
            cal.source != "GOOGLE"
            or not connection
            or connection.id != cal.provider_connection_id
            or cal.availability != "AVAILABLE"
            or cal.excluded_at
        ):
            result.state = "CALENDAR_UNAVAILABLE"
        elif EVENT_SCOPE not in connection.granted_scopes:
            result.state = "EVENT_SCOPE_REQUIRED"
        elif connection.retry_at and connection.retry_at > now():
            result.state, result.error_code, result.retry_at = (
                "PROVIDER_ERROR",
                connection.last_error_code,
                connection.retry_at,
            )
        elif result.operational_date is None:
            result.state = "TIMEZONE_REQUIRED"
        else:
            result.state = "READY"
        return result, identity, (connection, cal)


async def remember_failure(request, connection_id, generation, exc):
    async with request.app.state.session_factory() as db:
        await google.mutation_lock(db)
        connection = await google.current(db)
        google.expected(connection, connection_id, generation)
        code = exc.code
        if code == "EVENT_SCOPE_REQUIRED":
            connection.granted_scopes = [s for s in connection.granted_scopes if s != EVENT_SCOPE]
        elif code in {"REAUTH_REQUIRED", "SCOPE_REQUIRED"}:
            connection.status = "REAUTH_REQUIRED"
            await google.unavailable(db, connection_id)
        elif code not in {"CALENDAR_UNAVAILABLE", "TIMEZONE_REQUIRED"}:
            try:
                connection.retry_at = now() + timedelta(seconds=exc.retry_after)
            except OverflowError:
                connection.retry_at = datetime(9999, 12, 30, tzinfo=UTC)
        connection.last_error_code = code
        if code in {"REAUTH_REQUIRED", "SCOPE_REQUIRED", "EVENT_SCOPE_REQUIRED"}:
            audit(
                db,
                "google.events.access_required",
                connection_id,
                actor_id=request.state.manager_id,
                outcome="FAILED",
            )
        await db.commit()


async def read_schedule(request, technician_id, preview=False):
    started = monotonic()
    result, identity, context = await snapshot(request, technician_id, preview)
    if result.state != "READY":
        return result
    connection, calendar = context
    factory = request.app.state.session_factory
    identifier, generation = connection.id, connection.generation
    try:
        async with advisory_guard(
            request.app.state.google_lock_engine, "google-events", technician_id, wait=False
        ):
            adapter, cipher = google.provider(request), google.cipher(request)
            try:
                async with advisory_guard(
                    request.app.state.google_lock_engine, "google-lifecycle", 0
                ):
                    latest_result, latest_identity, latest_context = await snapshot(
                        request, technician_id, preview
                    )
                    if latest_identity != identity or latest_result.state != "READY":
                        latest_result.state = "CHANGED"
                        result = latest_result
                        return result
                    token = cipher.decrypt(latest_context[0].encrypted_refresh_token)
                    grant = await adapter.refresh_credentials(
                        token, scopes=tuple(connection.granted_scopes)
                    )
                    # Save token rotation before events pagination, even if scope was lost.
                    async with factory() as db:
                        await google.mutation_lock(db)
                        latest = await google.current(db)
                        google.expected(latest, identifier, generation)
                        if grant.refresh_token and grant.refresh_token != token:
                            latest.encrypted_refresh_token = cipher.encrypt(grant.refresh_token)
                        await db.commit()
                    if SCOPE not in grant.scopes:
                        raise ProviderError("SCOPE_REQUIRED")
                    if EVENT_SCOPE not in grant.scopes:
                        raise ProviderError("EVENT_SCOPE_REQUIRED")
                time_min, time_max = operational_window(result.operational_date, calendar.timezone)
                events = await adapter.list_events(
                    grant.access_token,
                    calendar.provider_calendar_id,
                    time_min,
                    time_max,
                    calendar.timezone,
                )
            except Exception as failure:
                if isinstance(failure, HTTPException):
                    raise
                exc = (
                    failure
                    if isinstance(failure, ProviderError)
                    else ProviderError(
                        "REAUTH_REQUIRED"
                        if isinstance(failure, ValueError)
                        else "PROVIDER_TEMPORARY_ERROR"
                    )
                )
                fresh, fresh_identity, _ = await snapshot(request, technician_id, preview)
                if fresh_identity != identity:
                    fresh.state = "CHANGED"
                    result = fresh
                    return result
                await remember_failure(request, identifier, generation, exc)
                fresh.state = (
                    "EVENT_SCOPE_REQUIRED"
                    if exc.code == "EVENT_SCOPE_REQUIRED"
                    else "REAUTH_REQUIRED"
                    if exc.code in {"REAUTH_REQUIRED", "SCOPE_REQUIRED"}
                    else "CALENDAR_UNAVAILABLE"
                    if exc.code == "CALENDAR_UNAVAILABLE"
                    else "PROVIDER_ERROR"
                )
                fresh.error_code = exc.code
                if fresh.state == "PROVIDER_ERROR":
                    fresh.retry_at = (await snapshot(request, technician_id, preview))[0].retry_at
                result = fresh
                return result
            fresh, fresh_identity, _ = await snapshot(request, technician_id, preview)
            if (
                fresh_identity != identity
                or fresh.state != "READY"
                or fresh.operational_date != result.operational_date
            ):
                fresh.state = "CHANGED"
                result = fresh
                return result
            fresh.jobs, fresh.warnings = build_technician_schedule(
                calendar.id, result.operational_date, calendar.timezone, events
            )
            fresh.last_fetched_at = now()
            result = fresh
            return result
    except RuntimeError as exc:
        if str(exc) != "POLLER_ALREADY_RUNNING":
            raise
        result.state = "BUSY"
        return result
    finally:
        logger.info(
            "calendar_events operation=%s technician=%s calendar=%s "
            "duration_ms=%d result=%s count=%d",
            "next_schedule" if preview else "today",
            technician_id,
            calendar.id,
            int((monotonic() - started) * 1000),
            result.state,
            len(result.jobs),
        )
