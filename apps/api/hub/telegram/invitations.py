from datetime import timedelta
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from hub.audit.service import audit
from hub.auth.security import digest, now, random_token, rate_limit
from hub.core.config import Settings
from hub.telegram.common import approved_id, binding, configured, generation, lock_technician
from hub.telegram.models import TelegramInvitation, TelegramOutbox
from hub.telegram.schemas import IssuedInvitation, IssueInvitation
from hub.telegram.state import invitation_read


async def issue(
    db: AsyncSession,
    identifier: UUID,
    manager_id: UUID,
    payload: IssueInvitation,
    settings: Settings,
) -> IssuedInvitation:
    bot_id = configured(settings)
    await lock_technician(db, identifier)
    current = await binding(db, identifier)
    if current.bot_id not in {None, bot_id} and (
        current.telegram_user_id or current.telegram_group_chat_id
    ):
        raise HTTPException(409, "Disconnect the previous bot's bindings before using another bot.")
    if generation(current, payload.purpose) != payload.expected_generation:
        raise HTTPException(409, "Connection changed. Refresh this profile.")
    if approved_id(current, payload.purpose) is not None and (
        not payload.replace or payload.confirmation != "REPLACE"
    ):
        raise HTTPException(409, "Explicit replacement confirmation is required.")
    if payload.purpose == "WORK_GROUP" and (
        current.telegram_user_id is None or current.private_status != "CONNECTED"
    ):
        raise HTTPException(409, "Approve the private Telegram account first.")
    await rate_limit(db, f"invite:{manager_id}:{identifier}", limit=12, seconds=900)
    await db.execute(
        update(TelegramInvitation)
        .where(
            TelegramInvitation.technician_id == identifier,
            TelegramInvitation.purpose == payload.purpose,
            TelegramInvitation.closed_at.is_(None),
        )
        .values(revoked_at=now(), closed_at=now())
    )
    token = random_token()
    invitation = TelegramInvitation(
        technician_id=identifier,
        bot_id=bot_id,
        purpose=payload.purpose,
        token_hash=digest(token),
        expected_generation=generation(current, payload.purpose),
        expected_private_generation=current.private_generation,
        created_by_manager_id=manager_id,
        expires_at=now() + timedelta(seconds=settings.telegram_invite_seconds),
    )
    db.add(invitation)
    await db.flush()
    audit(
        db,
        "telegram.invitation_issued",
        identifier,
        actor_id=manager_id,
        outcome="REPLACEMENT" if approved_id(current, payload.purpose) is not None else "NEW",
    )
    await db.commit()
    parameter = "start" if payload.purpose == "PRIVATE_ACCOUNT" else "startgroup"
    link = f"https://t.me/{settings.telegram_expected_bot_username}?{parameter}={token}"
    fallback = (
        f"/start@{settings.telegram_expected_bot_username} {token}"
        if parameter == "startgroup"
        else None
    )
    return IssuedInvitation(
        invitation=invitation_read(invitation), link=link, fallback_command=fallback
    )


async def pending_invitation(
    db: AsyncSession, identifier: UUID, invitation_id: UUID
) -> TelegramInvitation:
    value = await db.scalar(
        select(TelegramInvitation)
        .where(
            TelegramInvitation.id == invitation_id, TelegramInvitation.technician_id == identifier
        )
        .with_for_update()
    )
    if not value:
        raise HTTPException(404, "Invitation not found.")
    return value


async def revoke(db: AsyncSession, identifier: UUID, invitation_id: UUID, manager_id: UUID) -> None:
    await lock_technician(db, identifier, active=False)
    value = await pending_invitation(db, identifier, invitation_id)
    if value.closed_at is not None:
        raise HTTPException(409, "Invitation is already closed. Refresh this profile.")
    value.revoked_at = value.closed_at = now()
    await db.execute(
        update(TelegramOutbox)
        .where(TelegramOutbox.invitation_id == value.id, TelegramOutbox.state == "QUEUED")
        .values(state="CANCELLED", error_code="INVITATION_REVOKED")
    )
    audit(db, "telegram.invitation_revoked", identifier, actor_id=manager_id)
    await db.commit()
