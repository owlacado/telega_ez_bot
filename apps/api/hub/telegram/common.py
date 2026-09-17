from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import lazyload

from hub.audit.service import audit
from hub.auth.security import now
from hub.core.config import Settings
from hub.integrations.models import TelegramBinding
from hub.technicians.models import Technician
from hub.telegram.models import TelegramInvitation, TelegramOutbox


def configured(settings: Settings) -> int:
    if settings.telegram_mode == "disabled":
        raise HTTPException(
            409,
            (
                "Telegram is disabled. Configure a dedicated test bot and "
                "explicitly enable its worker later."
            ),
        )
    if not settings.telegram_expected_bot_id or not settings.telegram_expected_bot_username:
        raise HTTPException(409, "Bot identity is not configured.")
    return settings.telegram_expected_bot_id


async def lock_technician(db: AsyncSession, identifier: UUID, *, active: bool = True) -> Technician:
    technician = await db.scalar(
        select(Technician)
        .options(lazyload("*"))
        .where(Technician.id == identifier)
        .with_for_update()
    )
    if not technician:
        raise HTTPException(404, "Technician not found.")
    if active and technician.status != "ACTIVE":
        raise HTTPException(409, "This technician is inactive.")
    return technician


async def binding(db: AsyncSession, identifier: UUID) -> TelegramBinding:
    value = await db.get(TelegramBinding, identifier)
    if not value:
        value = TelegramBinding(technician_id=identifier)
        db.add(value)
        await db.flush()
    return value


def generation(value: TelegramBinding, purpose: str) -> int:
    return value.private_generation if purpose == "PRIVATE_ACCOUNT" else value.group_generation


def approved_id(value: TelegramBinding, purpose: str) -> int | None:
    return value.telegram_user_id if purpose == "PRIVATE_ACCOUNT" else value.telegram_group_chat_id


def can_deliver(value: TelegramBinding, purpose: str, bot_id: int) -> bool:
    if (
        value.bot_id != bot_id
        or value.private_status != "CONNECTED"
        or not value.telegram_user_id
        or value.private_availability != "AVAILABLE"
    ):
        return False
    return purpose == "PRIVATE_ACCOUNT" or (
        value.group_status == "CONNECTED"
        and value.telegram_group_chat_id is not None
        and value.group_availability == "AVAILABLE"
        and value.group_private_generation == value.private_generation
    )


async def invalidate(
    db: AsyncSession,
    identifier: UUID,
    purpose: str | None = None,
    *,
    except_invite: UUID | None = None,
) -> None:
    invitations = update(TelegramInvitation).where(
        TelegramInvitation.technician_id == identifier, TelegramInvitation.closed_at.is_(None)
    )
    jobs = update(TelegramOutbox).where(
        TelegramOutbox.technician_id == identifier,
        TelegramOutbox.state.in_(["QUEUED", "PROCESSING"]),
    )
    if purpose:
        invitations = invitations.where(TelegramInvitation.purpose == purpose)
        jobs = jobs.where(TelegramOutbox.destination == purpose)
    if except_invite:
        invitations = invitations.where(TelegramInvitation.id != except_invite)
    await db.execute(invitations.values(revoked_at=now(), closed_at=now()))
    await db.execute(
        jobs.values(state="CANCELLED", error_code="BINDING_CHANGED", finished_at=now())
    )


async def reject(
    db: AsyncSession,
    action: str,
    identifier: UUID,
    manager_id: UUID | None,
    message: str,
    outcome: str = "CONFLICT",
) -> None:
    audit(db, action, identifier, actor_id=manager_id, outcome=outcome)
    await db.commit()
    raise HTTPException(409, message)
