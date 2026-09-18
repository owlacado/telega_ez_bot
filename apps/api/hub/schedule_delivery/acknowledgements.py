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
from hub.telegram.locks import advisory_guard


async def acknowledge(factory, event, bot_id):
    locks = create_async_engine(factory.kw["bind"].url, poolclass=NullPool, hide_parameters=True)
    try:
        return await _acknowledge(factory, locks, event, bot_id)
    finally:
        await locks.dispose()


async def _acknowledge(factory, locks, event, bot_id):
    if (
        not event.payload
        or not event.payload.startswith("sch:")
        or event.user_is_bot
        or event.anonymous
        or not event.user_id
    ):
        return "ACK_UNAVAILABLE"
    digest = token_hash(event.payload[4:])
    async with factory() as db:
        technician_id = await db.scalar(
            select(ScheduleDispatch.technician_id).where(ScheduleDispatch.ack_token_hash == digest)
        )
    if technician_id is None:
        return "ACK_UNAVAILABLE"
    async with advisory_guard(locks, "technician", technician_id):
        async with factory() as db, db.begin():
            row = await db.scalar(
                select(ScheduleDispatch)
                .where(ScheduleDispatch.ack_token_hash == digest)
                .with_for_update()
            )
            binding = await db.get(TelegramBinding, technician_id)
            tech = await db.get(Technician, technician_id)
            stamp = await clock(db)
            if (
                not row
                or row.status != "SENT"
                or not row.ack_expires_at
                or row.ack_expires_at <= stamp
                or row.bot_id != bot_id
                or row.telegram_user_id != event.user_id
                or row.chat_id != event.chat_id
                or row.message_id != event.message_id
                or not binding
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
            if row.ack_status != "ACKNOWLEDGED":
                row.ack_status, row.acknowledged_at = "ACKNOWLEDGED", stamp
                audit(db, "schedule.acknowledged", row.id, actor_kind="TELEGRAM_WORKER")
            return "ACKNOWLEDGED"
