from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from hub.audit.service import audit
from hub.auth.security import now
from hub.integrations.models import TelegramBinding
from hub.technicians.models import Technician
from hub.telegram.common import invalidate
from hub.telegram.locks import lock_key
from hub.telegram.models import TelegramOutbox
from hub.telegram.types import TrustedEvent


async def lifecycle(db: AsyncSession, event: TrustedEvent, bot_id: int) -> str:
    field = (
        TelegramBinding.telegram_user_id
        if event.chat_type == "private"
        else TelegramBinding.telegram_group_chat_id
    )
    current = await db.scalar(
        select(TelegramBinding).where(field == event.chat_id, TelegramBinding.bot_id == bot_id)
    )
    if event.kind == "MIGRATION":
        current = await db.scalar(
            select(TelegramBinding).where(
                TelegramBinding.telegram_group_chat_id == event.chat_id,
                TelegramBinding.bot_id == bot_id,
            )
        )
    if current is None:
        return "IGNORED"
    technician = await db.scalar(
        select(Technician).where(Technician.id == current.technician_id).with_for_update()
    )
    if not technician:
        return "IGNORED"
    await db.refresh(current)
    # The binding may have been replaced while this update waited for the row lock.
    matched_id = (
        current.telegram_user_id
        if event.chat_type == "private" and event.kind != "MIGRATION"
        else current.telegram_group_chat_id
    )
    if current.bot_id != bot_id or matched_id != event.chat_id:
        return "IGNORED"
    if event.kind == "MIGRATION":
        if (
            not event.chat_id
            or not event.migrated_chat_id
            or event.chat_id >= 0
            or event.migrated_chat_id >= 0
        ):
            return "IGNORED"
        await db.execute(
            text("SELECT pg_advisory_xact_lock(:key)"),
            {"key": lock_key("WORK_GROUP", event.migrated_chat_id)},
        )
        other = await db.scalar(
            select(TelegramBinding.technician_id).where(
                TelegramBinding.telegram_group_chat_id == event.migrated_chat_id,
                TelegramBinding.technician_id != current.technician_id,
            )
        )
        current.group_generation += 1
        current.group_private_generation = None
        current.group_availability = "MIGRATION_CONFLICT" if other else "REVALIDATION_REQUIRED"
        if not other:
            current.telegram_group_chat_id = event.migrated_chat_id
        await invalidate(db, current.technician_id, "WORK_GROUP")
        audit(
            db,
            "telegram.group_migrated",
            current.technician_id,
            actor_kind="TELEGRAM_WORKER",
            outcome="CONFLICT" if other else "REVALIDATION_REQUIRED",
        )
        return "MIGRATION_CONFLICT" if other else "MIGRATED"
    if event.kind == "BOT_MEMBERSHIP":
        if event.member_user_id != bot_id:
            return "IGNORED"
        if event.chat_type == "private":
            current.private_availability = "AVAILABLE" if event.member_present else "BLOCKED"
        elif event.chat_type in {"group", "supergroup"}:
            current.group_availability = (
                "REVALIDATION_REQUIRED" if event.member_status == "administrator" else "UNAVAILABLE"
            )
        else:
            return "IGNORED"
    elif (
        event.kind == "MEMBER"
        and event.member_user_id == current.telegram_user_id
        and event.chat_type in {"group", "supergroup"}
    ):
        current.group_availability = (
            "REVALIDATION_REQUIRED" if event.member_present else "UNAVAILABLE"
        )
    else:
        return "IGNORED"
    await db.execute(
        update(TelegramOutbox)
        .where(
            TelegramOutbox.technician_id == current.technician_id,
            TelegramOutbox.state == "QUEUED",
            TelegramOutbox.kind != "VERIFY_GROUP",
        )
        .values(state="CANCELLED", error_code="AVAILABILITY_CHANGED", finished_at=now())
    )
    audit(
        db,
        "telegram.availability_changed",
        current.technician_id,
        actor_kind="TELEGRAM_WORKER",
        outcome="UPDATED",
    )
    return "AVAILABILITY_UPDATED"
