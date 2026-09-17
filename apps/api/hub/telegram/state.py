from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from hub.auth.security import now
from hub.core.config import Settings
from hub.integrations.models import TelegramBinding
from hub.technicians.service import require_technician
from hub.telegram.common import approved_id, generation
from hub.telegram.models import TelegramInvitation, TelegramOutbox, TelegramWorkerState
from hub.telegram.schemas import (
    ConnectionRead,
    DeliveryRead,
    InvitationRead,
    RuntimeRead,
    TelegramState,
)


def invitation_state(value: TelegramInvitation) -> str:
    if value.approved_at:
        return "APPROVED"
    if value.rejected_at:
        return "REJECTED"
    if value.revoked_at:
        return "REVOKED"
    if value.expires_at <= now():
        return "EXPIRED"
    if value.consumed_at:
        return "ERROR" if value.setup_error else "AWAITING_APPROVAL"
    return "LINK_ISSUED"


def invitation_read(value: TelegramInvitation) -> InvitationRead:
    return InvitationRead(
        id=value.id,
        purpose=value.purpose,
        expires_at=value.expires_at,
        state=invitation_state(value),
        candidate_user_id=str(value.candidate_user_id)
        if value.candidate_user_id is not None
        else None,
        candidate_display_name=value.candidate_display_name,
        candidate_username=value.candidate_username,
        candidate_chat_id=str(value.candidate_chat_id)
        if value.candidate_chat_id is not None
        else None,
        candidate_chat_title=value.candidate_chat_title,
        initiator_admin=value.initiator_admin,
        bot_admin=value.bot_admin,
        technician_member=value.technician_member,
        verified_at=value.verified_at,
        setup_error=value.setup_error,
    )


async def runtime_state(db: AsyncSession, settings: Settings) -> RuntimeRead:
    worker = (
        await db.get(TelegramWorkerState, settings.telegram_expected_bot_id)
        if settings.telegram_expected_bot_id
        else None
    )
    state = "WORKER_UNAVAILABLE"
    if settings.telegram_mode == "disabled":
        state = "DISABLED"
    elif not settings.telegram_expected_bot_id or not settings.telegram_expected_bot_username:
        state = "NOT_CONFIGURED"
    elif (
        worker
        and worker.status == "RUNNING"
        and worker.heartbeat_at
        and (now() - worker.heartbeat_at).total_seconds() < 90
    ):
        state = "RUNNING"
    return RuntimeRead(
        mode=settings.telegram_mode,
        state=state,
        bot_username=settings.telegram_expected_bot_username,
        heartbeat_at=worker.heartbeat_at if worker else None,
        error_code=worker.error_code if worker else None,
    )


async def read_state(db: AsyncSession, identifier: UUID, settings: Settings) -> TelegramState:
    technician = await require_technician(db, identifier)
    current = await db.get(TelegramBinding, identifier)
    results = {}
    for key, purpose in [("private", "PRIVATE_ACCOUNT"), ("group", "WORK_GROUP")]:
        latest = await db.scalar(
            select(TelegramInvitation)
            .where(
                TelegramInvitation.technician_id == identifier,
                TelegramInvitation.purpose == purpose,
            )
            .order_by(TelegramInvitation.created_at.desc(), TelegramInvitation.id.desc())
            .limit(1)
        )
        pending = invitation_read(latest) if latest and not latest.approved_at else None
        telegram_id = approved_id(current, purpose) if current else None
        availability = getattr(current, f"{key}_availability") if current else "UNKNOWN"
        if technician.status != "ACTIVE":
            availability = "TECHNICIAN_INACTIVE"
        elif current and current.bot_id != settings.telegram_expected_bot_id:
            availability = "BOT_CHANGED"
        elif (
            key == "group"
            and current
            and availability == "AVAILABLE"
            and current.private_availability != "AVAILABLE"
        ):
            availability = "PRIVATE_UNAVAILABLE"
        state = "CONNECTED" if telegram_id is not None else "NOT_CONNECTED"
        if pending and pending.state not in {"REJECTED", "REVOKED"}:
            state = pending.state
        results[key] = ConnectionRead(
            state=state,
            approved=telegram_id is not None,
            generation=generation(current, purpose) if current else 0,
            availability=availability,
            telegram_id=str(telegram_id) if telegram_id is not None else None,
            display_name=(current.private_display_name if key == "private" else current.group_title)
            if current
            else None,
            username=current.private_username if current and key == "private" else None,
            replacement_pending=bool(
                telegram_id is not None
                and pending
                and pending.state in {"LINK_ISSUED", "AWAITING_APPROVAL", "ERROR"}
            ),
            invitation=pending,
        )
    deliveries = (
        await db.scalars(
            select(TelegramOutbox)
            .where(TelegramOutbox.technician_id == identifier)
            .order_by(TelegramOutbox.created_at.desc())
            .limit(10)
        )
    ).all()
    return TelegramState(
        **results,
        runtime=await runtime_state(db, settings),
        deliveries=[
            DeliveryRead(
                id=value.id,
                destination=value.destination,
                kind=value.kind,
                state=value.state,
                error_code=value.error_code,
                created_at=value.created_at,
            )
            for value in deliveries
        ],
    )
