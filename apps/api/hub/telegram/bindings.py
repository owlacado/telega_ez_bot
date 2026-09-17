from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from hub.audit.service import audit
from hub.auth.security import now, rate_limit
from hub.core.config import Settings
from hub.integrations.models import TelegramBinding
from hub.telegram.common import (
    binding,
    can_deliver,
    configured,
    generation,
    invalidate,
    lock_technician,
    reject,
)
from hub.telegram.invitations import pending_invitation
from hub.telegram.locks import lock_key
from hub.telegram.models import TelegramOutbox
from hub.telegram.schemas import Disconnect, ReviewInvitation, TestMessage


def enqueue(
    db: AsyncSession,
    current: TelegramBinding,
    purpose: str,
    kind: str,
    manager_id: UUID,
    *,
    invitation_id: UUID | None = None,
) -> TelegramOutbox:
    job = TelegramOutbox(
        technician_id=current.technician_id,
        invitation_id=invitation_id,
        bot_id=current.bot_id,
        destination=purpose,
        kind=kind,
        generation=generation(current, purpose),
        private_generation=current.private_generation,
        requested_by=manager_id,
    )
    db.add(job)
    return job


async def review(
    db: AsyncSession,
    identifier: UUID,
    invitation_id: UUID,
    manager_id: UUID,
    payload: ReviewInvitation,
    settings: Settings,
) -> None:
    bot_id = configured(settings)
    await lock_technician(db, identifier)
    current = await binding(db, identifier)
    value = await pending_invitation(db, identifier, invitation_id)
    if (
        value.closed_at
        or value.expires_at <= now()
        or not value.consumed_at
        or value.bot_id != bot_id
        or value.expected_generation != generation(current, value.purpose)
        or value.expected_private_generation != current.private_generation
    ):
        await reject(
            db,
            "telegram.review_rejected",
            identifier,
            manager_id,
            "Invitation is expired, revoked, or stale. Refresh and generate a new link.",
            "STALE",
        )
    if payload.decision == "REJECT":
        value.rejected_at = value.closed_at = now()
        value.reviewed_by_manager_id = manager_id
        audit(db, "telegram.candidate_rejected", identifier, actor_id=manager_id)
        await db.commit()
        return
    if value.candidate_user_id is None:
        raise HTTPException(409, "No candidate has claimed this invitation.")
    if value.purpose == "WORK_GROUP" and (
        value.setup_error
        or not value.initiator_admin
        or not value.bot_admin
        or not value.technician_member
        or not value.verified_at
        or (now() - value.verified_at).total_seconds() > 120
        or current.telegram_user_id is None
    ):
        raise HTTPException(
            409,
            (
                "Group checks are incomplete or older than two minutes. Retry "
                "verification, then approve."
            ),
        )
    candidate_id = (
        value.candidate_user_id if value.purpose == "PRIVATE_ACCOUNT" else value.candidate_chat_id
    )
    field = (
        TelegramBinding.telegram_user_id
        if value.purpose == "PRIVATE_ACCOUNT"
        else TelegramBinding.telegram_group_chat_id
    )
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key(value.purpose, candidate_id)}
    )
    conflict = await db.scalar(
        select(TelegramBinding.technician_id).where(
            field == candidate_id, TelegramBinding.technician_id != identifier
        )
    )
    if conflict:
        await reject(
            db,
            "telegram.approval_conflict",
            identifier,
            manager_id,
            "This Telegram identity is already assigned to another technician.",
        )
    current.bot_id = bot_id
    if value.purpose == "PRIVATE_ACCOUNT":
        current.telegram_user_id = value.candidate_user_id
        current.private_display_name = value.candidate_display_name
        current.private_username = value.candidate_username
        current.private_status = "CONNECTED"
        current.private_availability = "AVAILABLE"
        current.private_generation += 1
        # Keep the group identity reserved, but never let the new person inherit delivery.
        current.group_generation += 1
        current.group_private_generation = None
        current.group_availability = (
            "REVALIDATION_REQUIRED" if current.telegram_group_chat_id else "UNKNOWN"
        )
        await invalidate(db, identifier, except_invite=value.id)
    else:
        current.telegram_group_chat_id = value.candidate_chat_id
        current.group_title = value.candidate_chat_title
        current.group_actor_id = value.candidate_user_id
        current.group_status = "CONNECTED"
        current.group_availability = "AVAILABLE"
        current.group_generation += 1
        current.group_private_generation = current.private_generation
        await invalidate(db, identifier, "WORK_GROUP", except_invite=value.id)
    value.approved_at = value.closed_at = now()
    value.reviewed_by_manager_id = manager_id
    enqueue(db, current, value.purpose, "APPROVED", manager_id)
    audit(
        db, "telegram.connection_approved", identifier, actor_id=manager_id, outcome=value.purpose
    )
    await db.commit()


async def disconnect(
    db: AsyncSession, identifier: UUID, manager_id: UUID, payload: Disconnect
) -> None:
    await lock_technician(db, identifier, active=False)
    current = await binding(db, identifier)
    if generation(current, payload.purpose) != payload.expected_generation:
        raise HTTPException(409, "Connection changed. Refresh before disconnecting.")
    if payload.purpose == "PRIVATE_ACCOUNT":
        current.telegram_user_id = None
        current.private_display_name = current.private_username = None
        current.private_status = "NOT_CONNECTED"
        current.private_availability = "UNKNOWN"
        current.private_generation += 1
        current.group_generation += 1
        current.group_private_generation = None
        current.group_availability = (
            "REVALIDATION_REQUIRED" if current.telegram_group_chat_id else "UNKNOWN"
        )
        await invalidate(db, identifier)
    else:
        current.telegram_group_chat_id = current.group_actor_id = None
        current.group_title = None
        current.group_status = "NOT_CONNECTED"
        current.group_availability = "UNKNOWN"
        current.group_generation += 1
        current.group_private_generation = None
        await invalidate(db, identifier, "WORK_GROUP")
    audit(db, "telegram.disconnected", identifier, actor_id=manager_id, outcome=payload.purpose)
    await db.commit()


async def request_test(
    db: AsyncSession, identifier: UUID, manager_id: UUID, payload: TestMessage, settings: Settings
) -> TelegramOutbox:
    bot_id = configured(settings)
    await lock_technician(db, identifier)
    current = await binding(db, identifier)
    if generation(current, payload.destination) != payload.expected_generation or not can_deliver(
        current, payload.destination, bot_id
    ):
        raise HTTPException(
            409, "This approved destination is unavailable or has changed. Refresh the connection."
        )
    await rate_limit(db, f"telegram:test:{identifier}:{payload.destination}", limit=1, seconds=60)
    job = enqueue(db, current, payload.destination, "TEST", manager_id)
    audit(
        db, "telegram.test_requested", identifier, actor_id=manager_id, outcome=payload.destination
    )
    await db.commit()
    return job


async def request_verification(
    db: AsyncSession, identifier: UUID, invitation_id: UUID, manager_id: UUID, settings: Settings
) -> None:
    bot_id = configured(settings)
    await lock_technician(db, identifier)
    current = await binding(db, identifier)
    value = await pending_invitation(db, identifier, invitation_id)
    if (
        value.purpose != "WORK_GROUP"
        or not value.consumed_at
        or value.closed_at
        or value.expires_at <= now()
        or value.expected_generation != current.group_generation
        or value.expected_private_generation != current.private_generation
        or value.bot_id != bot_id
    ):
        raise HTTPException(409, "This group invitation is no longer pending. Generate a new link.")
    await rate_limit(db, f"telegram:verify:{invitation_id}", limit=3, seconds=60)
    current.bot_id = bot_id
    enqueue(db, current, "WORK_GROUP", "VERIFY_GROUP", manager_id, invitation_id=invitation_id)
    audit(db, "telegram.verification_requested", identifier, actor_id=manager_id)
    await db.commit()
