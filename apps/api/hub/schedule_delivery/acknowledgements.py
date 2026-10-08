"""Callbacks are capabilities AND actor-bound; a token alone never grants access."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from hub.audit.service import audit
from hub.integrations.models import TelegramBinding
from hub.schedule_delivery.delivery import clock
from hub.schedule_delivery.domain import token_hash
from hub.schedule_delivery.models import ScheduleDispatch
from hub.technicians.models import Technician
from hub.telegram.common import can_deliver
from hub.telegram.locks import advisory_guard


async def acknowledge(factory, event, bot_id, *, detailed=False):
    outcome = await checked_receipt(factory, event, bot_id, read_only=False)
    if detailed:
        return outcome
    return (
        "ACKNOWLEDGED"
        if outcome in {"ACKNOWLEDGED", "ACK_ALREADY_ACKNOWLEDGED"}
        else "ACK_UNAVAILABLE"
    )


async def acknowledgement_feedback(factory, event, bot_id):
    # Completed-update replay can inspect a receipt, never execute another ACK.
    return await checked_receipt(factory, event, bot_id, read_only=True)


async def checked_receipt(factory, event, bot_id, *, read_only):
    locks = create_async_engine(factory.kw["bind"].url, poolclass=NullPool, hide_parameters=True)
    try:
        return await _acknowledge(factory, locks, event, bot_id, read_only=read_only)
    finally:
        await locks.dispose()


async def _acknowledge(factory, locks, event, bot_id, *, read_only=False):
    if (
        not event.payload
        or not event.payload.startswith("sch:")
        or event.user_is_bot
        or event.anonymous
        or not event.user_id
    ):
        return "ACK_INVALID"
    digest = token_hash(event.payload[4:])
    async with factory() as db:
        technician_id = await db.scalar(
            select(ScheduleDispatch.technician_id).where(ScheduleDispatch.ack_token_hash == digest)
        )
    if technician_id is None:
        return "ACK_INVALID"
    async with advisory_guard(locks, "technician", technician_id):
        async with factory() as db, db.begin():
            row = await db.scalar(
                select(ScheduleDispatch)
                .where(ScheduleDispatch.ack_token_hash == digest)
                .with_for_update()
            )
            tech = await db.get(Technician, technician_id, with_for_update=True)
            binding = await db.get(TelegramBinding, technician_id)
            stamp = await clock(db)
            if row and row.telegram_user_id != event.user_id:
                return "ACK_WRONG_USER"
            if row and row.superseded_at is not None:
                return "ACK_SUPERSEDED"
            if row and (not row.ack_expires_at or row.ack_expires_at <= stamp):
                return "ACK_EXPIRED"
            if (
                not row
                or row.status != "SENT"
                or row.superseded_at is not None
                or not row.ack_expires_at
                or row.ack_expires_at <= stamp
                or row.bot_id != bot_id
                or row.telegram_user_id != event.user_id
                or (row.telegram_user_id if row.private_ack_required else row.chat_id)
                != event.chat_id
                or (row.ack_message_id if row.private_ack_required else row.message_id)
                != event.message_id
                or (
                    row.private_ack_required
                    and (event.chat_type != "private" or row.ack_message_id is None)
                )
                or not binding
                or not can_deliver(
                    binding,
                    "WORK_GROUP" if row.destination == "WORK_GROUP" else "PRIVATE_TELEGRAM",
                    bot_id,
                )
                or binding.bot_id != bot_id
                or binding.private_status != "CONNECTED"
                or binding.telegram_user_id != event.user_id
                or binding.private_generation != row.private_generation
                or (
                    row.destination == "WORK_GROUP"
                    and (
                        binding.group_status != "CONNECTED"
                        or binding.group_generation != row.group_generation
                        or binding.telegram_group_chat_id != row.chat_id
                        or binding.group_private_generation != row.private_generation
                    )
                )
                or not tech
                or tech.status != "ACTIVE"
            ):
                return "ACK_UNAVAILABLE"
            if row.ack_status == "ACKNOWLEDGED":
                return "ACK_ALREADY_ACKNOWLEDGED"
            if read_only:
                return "ACK_UNAVAILABLE"
            row.ack_status, row.acknowledged_at = "ACKNOWLEDGED", stamp
            if row.private_ack_required and row.destination == "WORK_GROUP":
                from hub.telegram.notices import enqueue_schedule_notice

                await enqueue_schedule_notice(db, row, "SCHEDULE_CONFIRMED")
            audit(db, "schedule.acknowledged", row.id, actor_kind="TELEGRAM_WORKER")
            return "ACKNOWLEDGED"
