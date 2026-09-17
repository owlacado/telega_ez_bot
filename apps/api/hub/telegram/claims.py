from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hub.audit.service import audit
from hub.auth.security import digest, now
from hub.integrations.models import TelegramBinding
from hub.integrations.ports import TelegramProvider
from hub.technicians.models import Technician
from hub.telegram.common import generation
from hub.telegram.models import TelegramInvitation
from hub.telegram.types import GroupChecks, TrustedEvent
from hub.telegram.verification import verify_group


@dataclass(frozen=True)
class ClaimProof:
    invitation_id: UUID
    checks: GroupChecks | None


async def prepare_claim(
    factory: async_sessionmaker, event: TrustedEvent, provider: TelegramProvider, bot_id: int
) -> ClaimProof | None:
    if (
        event.kind != "COMMAND"
        or event.command != "/start"
        or not event.payload
        or event.user_is_bot
        or event.anonymous
        or event.user_id is None
    ):
        return None
    if event.chat_type == "private" and event.chat_id != event.user_id:
        return None
    async with factory() as db:
        invitation = await db.scalar(
            select(TelegramInvitation).where(
                TelegramInvitation.token_hash == digest(event.payload),
                TelegramInvitation.bot_id == bot_id,
            )
        )
        if (
            not invitation
            or invitation.closed_at
            or invitation.consumed_at
            or invitation.expires_at <= now()
        ):
            return None
        technician = await db.get(Technician, invitation.technician_id)
        current = await db.get(TelegramBinding, invitation.technician_id)
        if not technician or technician.status != "ACTIVE" or not current:
            return None
        if (
            invitation.expected_generation != generation(current, invitation.purpose)
            or invitation.expected_private_generation != current.private_generation
        ):
            return None
        invitation_id, purpose, user_id = (
            invitation.id,
            invitation.purpose,
            current.telegram_user_id,
        )
    # Network calls are outside every database transaction.
    if purpose == "PRIVATE_ACCOUNT" and event.chat_type == "private":
        return ClaimProof(invitation_id, None)
    if (
        purpose == "WORK_GROUP"
        and event.chat_type in {"group", "supergroup"}
        and event.chat_id is not None
        and event.chat_id < 0
        and user_id
    ):
        return ClaimProof(
            invitation_id,
            await verify_group(provider, event.chat_id, event.user_id, user_id, bot_id),
        )
    return None


async def consume_claim(
    db: AsyncSession, event: TrustedEvent, proof: ClaimProof | None, bot_id: int
) -> str:
    if proof is None:
        return "INVALID_INVITATION"
    candidate = await db.get(TelegramInvitation, proof.invitation_id)
    if not candidate:
        return "INVALID_INVITATION"
    technician = await db.scalar(
        select(Technician).where(Technician.id == candidate.technician_id).with_for_update()
    )
    if not technician or technician.status != "ACTIVE":
        return "INVALID_INVITATION"
    value = await db.scalar(
        select(TelegramInvitation)
        .where(TelegramInvitation.id == proof.invitation_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    current = await db.get(TelegramBinding, technician.id, populate_existing=True)
    if (
        not value
        or not current
        or value.consumed_at
        or value.closed_at
        or value.expires_at <= now()
        or value.bot_id != bot_id
        or value.expected_generation != generation(current, value.purpose)
        or value.expected_private_generation != current.private_generation
    ):
        return "INVALID_INVITATION"
    value.consumed_at = now()
    value.candidate_user_id = event.user_id
    value.candidate_display_name = event.display_name
    value.candidate_username = event.username
    if value.purpose == "WORK_GROUP":
        value.candidate_chat_id = event.chat_id
        value.candidate_chat_title = event.chat_title
        checks = proof.checks
        assert checks is not None
        value.initiator_admin, value.bot_admin, value.technician_member = (
            checks.initiator_admin,
            checks.bot_admin,
            checks.technician_member,
        )
        value.verified_at = now()
        value.setup_error = checks.error
    audit(
        db,
        "telegram.candidate_captured",
        technician.id,
        actor_kind="TELEGRAM_WORKER",
        outcome="NEEDS_SETUP" if value.setup_error else "AWAITING_APPROVAL",
    )
    return "NEEDS_SETUP" if value.setup_error else "AWAITING_APPROVAL"
