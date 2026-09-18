"""Calendar-local evening decisions, serialized per technician across workers."""

from datetime import time, timedelta

from fastapi import HTTPException
from sqlalchemy import select

from hub.auth.security import now
from hub.calendar_events.domain import calendar_zone, next_schedule_date
from hub.calendars.models import Calendar, CalendarAssignment
from hub.schedule_delivery.models import ScheduleAutoDecision, ScheduleDeliverySetting
from hub.schedule_delivery.service import create_dispatch
from hub.telegram.locks import advisory_guard


def in_window(stamp, timezone, settings):
    local = stamp.astimezone(calendar_zone(timezone))
    start = time.fromisoformat(settings.schedule_auto_delivery_local_time)
    return start <= local.time().replace(tzinfo=None) < time(23)


async def evaluate(request):
    factory, settings = request.app.state.session_factory, request.app.state.settings
    async with factory() as db:
        candidates = (
            await db.execute(
                select(ScheduleDeliverySetting.technician_id, Calendar.timezone)
                .join(
                    CalendarAssignment,
                    CalendarAssignment.technician_id == ScheduleDeliverySetting.technician_id,
                )
                .join(Calendar, Calendar.id == CalendarAssignment.calendar_id)
                .where(
                    ScheduleDeliverySetting.enabled.is_(True),
                    CalendarAssignment.is_active.is_(True),
                )
            )
        ).all()
    for technician_id, timezone in candidates:
        try:
            local = now().astimezone(calendar_zone(timezone))
        except Exception:
            continue
        if local.time().replace(tzinfo=None) < time.fromisoformat(
            settings.schedule_auto_delivery_local_time
        ):
            continue
        target = next_schedule_date(local.date())
        try:
            async with advisory_guard(
                request.app.state.google_lock_engine, "schedule-auto", technician_id, wait=False
            ):
                async with factory() as db, db.begin():
                    decision = await db.get(ScheduleAutoDecision, (technician_id, target))
                    if decision and (
                        decision.state in {"QUEUED", "SUPPRESSED", "MISSED"}
                        or decision.retry_at
                        and decision.retry_at > now()
                    ):
                        continue
                    if not decision:
                        decision = ScheduleAutoDecision(
                            technician_id=technician_id,
                            target_date=target,
                            source_date=local.date(),
                            state="DUE",
                        )
                        db.add(decision)
                    if not in_window(now(), timezone, settings):
                        decision.state, decision.error_code, decision.retry_at = (
                            "MISSED",
                            "DELIVERY_WINDOW_EXPIRED",
                            None,
                        )
                        continue
                try:
                    await create_dispatch(request, technician_id, automatic=True)
                    state, error = "QUEUED", None
                except HTTPException as exc:
                    state, error = (
                        ("SUPPRESSED", "AUTO_SUPPRESSED")
                        if exc.detail == "AUTO_SUPPRESSED"
                        else ("RETRY", str(exc.detail))
                    )
                except Exception:
                    state, error = "RETRY", "PROCESSING_FAILED"
                async with factory() as db, db.begin():
                    decision = await db.get(
                        ScheduleAutoDecision, (technician_id, target), with_for_update=True
                    )
                    if decision:
                        decision.state, decision.error_code = state, error
                        decision.retry_at = (
                            now() + timedelta(minutes=5) if state == "RETRY" else None
                        )
        except RuntimeError as exc:
            if str(exc) != "POLLER_ALREADY_RUNNING":
                raise
