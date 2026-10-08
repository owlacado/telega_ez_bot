"""All dispatch creation paths re-fetch the audited projection and share one enqueue."""

from datetime import datetime, time, timedelta

from fastapi import HTTPException
from sqlalchemy import select

from hub.audit.service import audit
from hub.auth.security import now
from hub.calendar_events.domain import calendar_zone
from hub.calendar_events.service import read_schedule, snapshot
from hub.google_calendar.service import mutation_lock
from hub.integrations.models import TelegramBinding
from hub.schedule_delivery.domain import cipher, from_schedule, source_version
from hub.schedule_delivery.models import (
    ScheduleAutoDecision,
    ScheduleDeliverySetting,
    ScheduleDispatch,
)
from hub.schedule_delivery.schemas import DispatchRead, ScheduleDeliveryRead
from hub.telegram.common import can_deliver, lock_technician
from hub.telegram.locks import advisory_guard


def destination(binding, bot_id):
    if binding is None:
        return None
    if can_deliver(binding, "WORK_GROUP", bot_id):
        return "WORK_GROUP"
    return None


def fail(code):
    raise HTTPException(409, code)


async def create_dispatch(
    request,
    technician_id,
    body=None,
    *,
    automatic=False,
    daily_binding=None,
    daily_request_key=None,
):
    config = request.app.state.settings
    if automatic and (not config.schedule_timed_auto_enabled or config.app_env == "pilot"):
        fail("AUTO_DISABLED")
    if daily_binding is not None and daily_request_key is None:
        fail("DAILY_UPDATE_REQUIRED")
    if daily_request_key is not None:
        async with request.app.state.session_factory() as db:
            replay = await db.scalar(
                select(ScheduleDispatch).where(
                    ScheduleDispatch.bot_id == config.telegram_expected_bot_id,
                    ScheduleDispatch.daily_request_key == daily_request_key,
                    ScheduleDispatch.technician_id == technician_id,
                )
            )
            if replay:
                return DispatchRead.model_validate(replay)
    internal = automatic or daily_binding is not None
    try:
        encryption = cipher(config)
    except ValueError:
        fail("DELIVERY_DISABLED")
    projection = await read_schedule(request, technician_id, preview=True, worker=internal)
    if projection.state != "READY":
        fail(projection.state)
    payload = from_schedule(projection)
    if body and (
        body.target_date != payload.target_date or body.fingerprint != payload.fingerprint
    ):
        fail("SCHEDULE_CHANGED")
    try:
        payload.render()
    except ValueError:
        fail("SCHEDULE_TOO_LARGE")
    factory = request.app.state.session_factory
    async with advisory_guard(request.app.state.google_lock_engine, "technician", technician_id):
        async with factory() as db, db.begin():
            await mutation_lock(db)
            await lock_technician(db, technician_id)
            fresh, identity, _ = await snapshot(
                request,
                technician_id,
                preview=True,
                worker=internal,
                session=db,
                target_date=payload.target_date,
            )
            if (
                fresh.state != "READY"
                or identity != projection._source_identity
                or (await snapshot(request, technician_id, worker=internal, session=db))[
                    0
                ].operational_date
                != projection._resolved_on
            ):
                fail("SCHEDULE_CHANGED")
            setting = await db.get(ScheduleDeliverySetting, technician_id)
            if automatic:
                from hub.schedule_delivery.scheduler import in_window

                if (
                    not setting
                    or not setting.enabled
                    or not in_window(now(), fresh.timezone, config)
                ):
                    fail("AUTO_NOT_DUE")
            binding = await db.get(TelegramBinding, technician_id)
            if daily_binding is not None and (
                not binding
                or (
                    binding.telegram_user_id,
                    binding.private_generation,
                    binding.group_generation,
                    binding.telegram_group_chat_id,
                )
                != daily_binding
            ):
                fail("TELEGRAM_UNAVAILABLE")
            chosen = destination(binding, config.telegram_expected_bot_id)
            if not chosen:
                fail("TELEGRAM_UNAVAILABLE")
            previous = list(
                (
                    await db.scalars(
                        select(ScheduleDispatch)
                        .where(
                            ScheduleDispatch.technician_id == technician_id,
                            ScheduleDispatch.target_date == payload.target_date,
                        )
                        .order_by(ScheduleDispatch.created_at.desc())
                    )
                ).all()
            )
            if automatic and any(
                d.status in {"SENT", "AMBIGUOUS", "PENDING", "PROCESSING"}
                or d.trigger == "AUTOMATIC"
                for d in previous
            ):
                fail("AUTO_SUPPRESSED")
            parent = None
            if body and body.resend_of_id:
                parent = next((d for d in previous if d.id == body.resend_of_id), None)
                if not parent or parent.status not in {"SENT", "FAILED", "AMBIGUOUS", "CANCELLED"}:
                    fail("RESEND_UNAVAILABLE")
                if not body.confirm_duplicate_risk:
                    fail("DUPLICATE_RISK_CONFIRMATION_REQUIRED")
                existing = next((d for d in previous if d.resend_of_id == parent.id), None)
                if existing:
                    return DispatchRead.model_validate(existing)
            elif any(d.status == "AMBIGUOUS" for d in previous):
                fail("AMBIGUOUS_REQUIRES_RESEND")
            elif any(d.status == "SENT" and d.fingerprint == payload.fingerprint for d in previous):
                fail("ALREADY_SENT")
            active = next((d for d in previous if d.status in {"PENDING", "PROCESSING"}), None)
            if active:
                if active.fingerprint == payload.fingerprint and not parent:
                    return DispatchRead.model_validate(active)
                fail("DELIVERY_IN_PROGRESS")
            from hub.schedule_delivery.delivery import clock

            stamp = await clock(db)
            actor = request.state.manager_id
            item = ScheduleDispatch(
                technician_id=technician_id,
                calendar_id=fresh.calendar.id,
                target_date=payload.target_date,
                trigger="AUTOMATIC" if automatic else "MANUAL_RESEND" if parent else "MANUAL",
                trigger_source=None
                if automatic
                else "TECHNICIAN_DAILY"
                if daily_binding is not None
                else "MANAGER_MANUAL",
                daily_request_key=daily_request_key,
                destination=chosen,
                requested_destination=chosen,
                fingerprint=payload.fingerprint,
                source_version=source_version(identity),
                job_count=len(payload.jobs),
                encrypted_payload=encryption.encrypt(payload.canonical()),
                payload_expires_at=stamp + timedelta(days=7),
                available_at=stamp,
                delivery_deadline=(
                    datetime.combine(
                        now().astimezone(calendar_zone(fresh.timezone)).date(),
                        time(23),
                        calendar_zone(fresh.timezone),
                    )
                    if automatic
                    else stamp + timedelta(hours=1)
                ),
                created_by=actor,
                resend_of_id=parent.id if parent else None,
                bot_id=config.telegram_expected_bot_id,
                telegram_user_id=binding.telegram_user_id,
                chat_id=binding.telegram_group_chat_id
                if chosen == "WORK_GROUP"
                else binding.telegram_user_id,
                private_generation=binding.private_generation,
                group_generation=binding.group_generation,
            )
            # Same technician lock as ACK: a new accepted dispatch supersedes every
            # older dispatch for this work date, even if its send later fails.
            for older in previous:
                if older.superseded_at is None:
                    older.superseded_at = stamp
            db.add(item)
            await db.flush()
            if not automatic:
                audit(
                    db,
                    "schedule.daily_queued"
                    if daily_binding is not None
                    else "schedule.resend_queued"
                    if parent
                    else "schedule.manual_queued",
                    item.id,
                    actor_id=actor,
                    actor_kind="TELEGRAM_WORKER" if daily_binding is not None else "MANAGER",
                )
                if parent and parent.status == "AMBIGUOUS":
                    audit(db, "schedule.ambiguous_resend_confirmed", parent.id, actor_id=actor)
            return DispatchRead.model_validate(item)


async def read_delivery(request, technician_id):
    config = request.app.state.settings
    async with request.app.state.session_factory() as db:
        tech = await lock_technician(db, technician_id, active=False)
        setting = await db.get(ScheduleDeliverySetting, technician_id)
        binding = await db.get(TelegramBinding, technician_id)
        chosen = (
            destination(binding, config.telegram_expected_bot_id)
            if tech.status == "ACTIVE"
            else None
        )
        history = (
            await db.scalars(
                select(ScheduleDispatch)
                .where(ScheduleDispatch.technician_id == technician_id)
                .order_by(ScheduleDispatch.created_at.desc(), ScheduleDispatch.id.desc())
                .limit(20)
            )
        ).all()
        decision = await db.scalar(
            select(ScheduleAutoDecision)
            .where(ScheduleAutoDecision.technician_id == technician_id)
            .order_by(ScheduleAutoDecision.target_date.desc())
            .limit(1)
        )
        return ScheduleDeliveryRead(
            enabled=bool(setting and setting.enabled),
            timed_auto_available=config.schedule_timed_auto_enabled and config.app_env != "pilot",
            available=config.schedule_delivery_enabled,
            destination=chosen,
            local_time=config.schedule_auto_delivery_local_time,
            history=[DispatchRead.model_validate(d) for d in history],
            automatic_state=decision.state if decision else None,
            automatic_error=decision.error_code if decision else None,
        )


async def set_enabled(request, technician_id, enabled):
    config = request.app.state.settings
    if enabled and (not config.schedule_timed_auto_enabled or config.app_env == "pilot"):
        fail("AUTO_DISABLED")
    async with advisory_guard(request.app.state.google_lock_engine, "technician", technician_id):
        async with request.app.state.session_factory() as db, db.begin():
            await lock_technician(db, technician_id, active=enabled)
            await snapshot(request, technician_id, session=db)
            setting = await db.get(ScheduleDeliverySetting, technician_id)
            if not setting:
                setting = ScheduleDeliverySetting(technician_id=technician_id, enabled=False)
                db.add(setting)
            if setting.enabled != enabled:
                setting.enabled = enabled
                audit(
                    db,
                    "schedule.auto_enabled" if enabled else "schedule.auto_disabled",
                    technician_id,
                    actor_id=request.state.manager_id,
                )
    return await read_delivery(request, technician_id)
