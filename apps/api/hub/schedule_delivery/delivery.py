"""Leased claims and a durable pre-provider marker: unknown acceptance never retries."""

import logging
import secrets
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import func, select

from hub.integrations.models import TelegramBinding
from hub.schedule_delivery.domain import Payload, cipher, source_version, token_hash
from hub.schedule_delivery.models import ScheduleDeliverySetting, ScheduleDispatch
from hub.technicians.models import Technician
from hub.telegram.common import can_deliver
from hub.telegram.locks import advisory_guard
from hub.telegram.types import ProviderError

logger = logging.getLogger(__name__)
LEASE = timedelta(seconds=90)


async def clock(db):
    return await db.scalar(select(func.clock_timestamp()))


def terminal(row, status, code, stamp):
    row.status, row.error_code, row.finished_at = status, code, stamp
    row.claim_owner = row.claim_expires_at = None
    if status in {"CANCELLED", "FAILED"}:
        row.encrypted_payload = None


async def claim(factory, bot_id):
    async with factory() as db, db.begin():
        stamp = await clock(db)
        # Recover expired history across bot rotations; live claims stay bot-scoped.
        expired = (
            await db.scalars(
                select(ScheduleDispatch)
                .where(
                    ScheduleDispatch.status == "PROCESSING",
                    ScheduleDispatch.claim_expires_at <= stamp,
                )
                .with_for_update(skip_locked=True)
                .limit(100)
            )
        ).all()
        for row in expired:
            if row.provider_started_at:
                terminal(row, "AMBIGUOUS", "ACCEPTANCE_UNKNOWN", stamp)
            else:
                row.status, row.claim_owner, row.claim_expires_at = "PENDING", None, None
        await db.flush()
        # Expired rows must not stop the drain or hide live work behind a backlog.
        expired_pending = (
            await db.scalars(
                select(ScheduleDispatch)
                .where(
                    ScheduleDispatch.status == "PENDING",
                    ScheduleDispatch.delivery_deadline <= stamp,
                )
                .with_for_update(skip_locked=True)
                .limit(100)
            )
        ).all()
        for pending in expired_pending:
            terminal(pending, "CANCELLED", "DELIVERY_WINDOW_EXPIRED", stamp)
        await db.flush()
        row = await db.scalar(
            select(ScheduleDispatch)
            .where(
                ScheduleDispatch.bot_id == bot_id,
                ScheduleDispatch.status == "PENDING",
                ScheduleDispatch.available_at <= stamp,
                ScheduleDispatch.delivery_deadline > stamp,
            )
            .order_by(ScheduleDispatch.available_at, ScheduleDispatch.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not row:
            return None
        row.status, row.claim_owner, row.claim_expires_at = "PROCESSING", uuid4(), stamp + LEASE
        return row.id, row.technician_id, row.claim_owner


async def owned(db, identifier, owner):
    row = await db.get(ScheduleDispatch, identifier, with_for_update=True)
    stamp = await clock(db)
    if (
        not row
        or row.status != "PROCESSING"
        or row.claim_owner != owner
        or row.claim_expires_at <= stamp
    ):
        return None, stamp
    return row, stamp


async def prepare(factory, identifier, owner, settings, *, group_available=True):
    async with factory() as db, db.begin():
        row, stamp = await owned(db, identifier, owner)
        if row is None:
            return None
        from hub.google_calendar.service import mutation_lock

        # Calendar assignment takes global mutation -> technician. Keep that order.
        await mutation_lock(db)
        tech = await db.get(Technician, row.technician_id, with_for_update=True)
        binding = await db.get(TelegramBinding, row.technician_id)
        # Row/global-lock waits can outlive the ownership check performed above.
        stamp = await clock(db)
        if row.claim_expires_at <= stamp:
            return None
        if (
            not tech
            or tech.status != "ACTIVE"
            or not binding
            or binding.bot_id != row.bot_id
            or binding.telegram_user_id != row.telegram_user_id
            or binding.private_generation != row.private_generation
            or not can_deliver(binding, "PRIVATE_TELEGRAM", row.bot_id)
        ):
            terminal(row, "CANCELLED", "BINDING_CHANGED", stamp)
            return None
        if row.delivery_deadline <= stamp:
            terminal(row, "CANCELLED", "DELIVERY_WINDOW_EXPIRED", stamp)
            return None
        from hub.calendar_events.service import snapshot

        request = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(session_factory=factory))
        )
        fresh, identity, _ = await snapshot(
            request, row.technician_id, preview=True, worker=True, session=db
        )
        if fresh.state != "READY" or source_version(identity) != row.source_version:
            terminal(row, "CANCELLED", "SOURCE_CHANGED", stamp)
            return None
        setting = await db.get(ScheduleDeliverySetting, row.technician_id)
        if row.trigger == "AUTOMATIC" and (not setting or not setting.enabled):
            terminal(row, "CANCELLED", "AUTO_DISABLED", stamp)
            return None
        if row.destination == "WORK_GROUP" and (
            not group_available
            or binding.group_generation != row.group_generation
            or binding.telegram_group_chat_id != row.chat_id
            or not can_deliver(binding, "WORK_GROUP", row.bot_id)
        ):
            if row.trigger_source is not None:
                terminal(row, "CANCELLED", "GROUP_UNAVAILABLE", stamp)
                return None
            row.destination, row.chat_id = "PRIVATE", row.telegram_user_id
            row.fallback_reason = "GROUP_UNAVAILABLE_BEFORE_SEND"
        try:
            payload = Payload.model_validate_json(cipher(settings).decrypt(row.encrypted_payload))
            if (
                payload.fingerprint != row.fingerprint
                or payload.target_date != row.target_date
                or len(payload.jobs) != row.job_count
            ):
                raise ValueError("SNAPSHOT_INVALID")
            message = payload.render()
        except Exception:
            terminal(row, "FAILED", "SNAPSHOT_UNREADABLE", stamp)
            return None
        token = secrets.token_urlsafe(32)
        row.ack_token_hash, row.ack_expires_at = token_hash(token), stamp + timedelta(days=7)
        row.provider_started_at = stamp
        row.attempt_count += 1
        row.claim_expires_at = stamp + LEASE
        return row.chat_id, message, "sch:" + token


async def finish(factory, identifier, owner, *, message_id=None, failure=None):
    async with factory() as db, db.begin():
        row, stamp = await owned(db, identifier, owner)
        if row is None:
            return False
        if failure is None:
            if not isinstance(message_id, int) or isinstance(message_id, bool) or message_id <= 0:
                failure = ProviderError("NETWORK_UNCERTAIN")
            else:
                terminal(row, "SENT", None, stamp)
                row.sent_at, row.message_id, row.ack_status = stamp, message_id, "PENDING"
                row.encrypted_payload = None
                return False
        code = failure.code
        if (
            code in {"ACCESS_DENIED", "CHAT_UNAVAILABLE"}
            and row.destination == "WORK_GROUP"
            and row.trigger_source is None
        ):
            # Provider definitively rejected this send. A crash before this commit is
            # still ambiguous; only this committed transition permits private fallback.
            row.destination, row.chat_id = "PRIVATE", row.telegram_user_id
            row.provider_started_at = None
            row.fallback_reason = "GROUP_REJECTED_PRIVATE_FALLBACK"
            row.error_code = row.fallback_reason
            return True
        row.ack_token_hash = row.ack_expires_at = None
        if code == "RATE_LIMITED" and row.attempt_count < 3:
            delay = max(1, failure.retry_after)
            if delay <= 3600 and stamp + timedelta(seconds=delay) < row.delivery_deadline:
                row.status, row.claim_owner, row.claim_expires_at = "PENDING", None, None
                row.available_at, row.provider_started_at = stamp + timedelta(seconds=delay), None
                row.error_code = code
                return False
        definitive = code in {
            "RATE_LIMITED",
            "ACCESS_DENIED",
            "CHAT_UNAVAILABLE",
            "REQUEST_REJECTED",
            "INVALID_BOT_CREDENTIALS",
        }
        terminal(
            row,
            "FAILED" if definitive else "AMBIGUOUS",
            code if definitive else "ACCEPTANCE_UNKNOWN",
            stamp,
        )
        return False


async def inspect_group(factory, identifier, owner, provider):
    async with factory() as db:
        row = await db.get(ScheduleDispatch, identifier)
        if not row or row.status != "PROCESSING" or row.claim_owner != owner:
            return None
        if row.destination != "WORK_GROUP":
            return True
        binding = await db.get(TelegramBinding, row.technician_id)
        if (
            not binding
            or not can_deliver(binding, "WORK_GROUP", row.bot_id)
            or binding.group_generation != row.group_generation
        ):
            return False
        chat_id, bot_id, user_id = row.chat_id, row.bot_id, row.telegram_user_id
    try:
        bot = await provider.member(chat_id, bot_id)
        if not bot.present or not bot.can_send_messages:
            return False
        technician = await provider.member(chat_id, user_id)
        return technician.present
    except ProviderError as exc:
        if exc.code in {"ACCESS_DENIED", "CHAT_UNAVAILABLE"}:
            return False
    except Exception:
        pass
    # No send was attempted, but membership cannot be proven. Do not disclose to
    # an unverified group or treat a transient inspection failure as a send attempt.
    async with factory() as db, db.begin():
        row, stamp = await owned(db, identifier, owner)
        if row:
            terminal(row, "FAILED", "MEMBERSHIP_UNVERIFIED", stamp)
    return None


async def deliver_one(factory, lock_engine, provider, settings):
    ticket = await claim(factory, settings.telegram_expected_bot_id)
    if not ticket:
        return False
    identifier, technician_id, owner = ticket
    async with advisory_guard(lock_engine, "technician", technician_id):
        for _ in range(2):
            group_available = await inspect_group(factory, identifier, owner, provider)
            if group_available is None:
                break
            prepared = await prepare(
                factory, identifier, owner, settings, group_available=group_available
            )
            if not prepared:
                break
            try:
                message_id = await provider.send_schedule(*prepared)
            except Exception as exc:
                error = (
                    exc if isinstance(exc, ProviderError) else ProviderError("NETWORK_UNCERTAIN")
                )
                fallback = await finish(factory, identifier, owner, failure=error)
                logger.info("schedule_dispatch id=%s result=%s", identifier, error.code)
                if fallback:
                    continue
            else:
                await finish(factory, identifier, owner, message_id=message_id)
                logger.info("schedule_dispatch id=%s result=PROVIDER_ACCEPTED", identifier)
            break
    return True


async def purge(factory):
    async with factory() as db, db.begin():
        stamp = await clock(db)
        rows = (
            await db.scalars(
                select(ScheduleDispatch)
                .where(
                    ScheduleDispatch.payload_expires_at <= stamp,
                    ScheduleDispatch.encrypted_payload.is_not(None),
                    ScheduleDispatch.status.in_(["FAILED", "AMBIGUOUS", "CANCELLED"]),
                )
                .with_for_update(skip_locked=True)
                .limit(100)
            )
        ).all()
        for row in rows:
            row.encrypted_payload = None
