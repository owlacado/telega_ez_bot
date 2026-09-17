from datetime import timedelta
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from hub.audit.service import audit
from hub.auth.security import now
from hub.integrations.models import TelegramBinding
from hub.integrations.ports import TelegramProvider
from hub.technicians.models import Technician
from hub.telegram.common import approved_id, can_deliver, generation
from hub.telegram.locks import advisory_guard
from hub.telegram.models import TelegramInvitation, TelegramOutbox
from hub.telegram.types import ProviderError
from hub.telegram.verification import verify_group

MESSAGES = {
    "APPROVED": (
        "Your Technician Hub connection has been approved by a manager. "
        "Reports and schedules are not available in this stage."
    ),
    "TEST": (
        "Technician Hub connection test requested by your manager. "
        "Telegram accepted this message; delivery does not imply it has "
        "been read."
    ),
}


async def recover_processing(factory: async_sessionmaker, bot_id: int) -> None:
    async with factory() as db, db.begin():
        jobs = (
            await db.scalars(
                select(TelegramOutbox)
                .where(TelegramOutbox.bot_id == bot_id, TelegramOutbox.state == "PROCESSING")
                .with_for_update()
            )
        ).all()
        for job in jobs:
            job.state = "QUEUED" if job.kind == "VERIFY_GROUP" else "UNKNOWN"
            job.error_code = "WORKER_RESTARTED"
            audit(
                db,
                "telegram.delivery_result",
                job.technician_id,
                actor_kind="TELEGRAM_WORKER",
                outcome=job.state,
            )


async def claim_job(factory: async_sessionmaker, bot_id: int) -> tuple[UUID, UUID] | None:
    async with factory() as db, db.begin():
        job = await db.scalar(
            select(TelegramOutbox)
            .where(
                TelegramOutbox.bot_id == bot_id,
                TelegramOutbox.state == "QUEUED",
                TelegramOutbox.available_at <= func.now(),
            )
            .order_by(TelegramOutbox.created_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if not job:
            return None
        job.state, job.started_at = "PROCESSING", now()
        job.attempts += 1
        return job.id, job.technician_id


async def finish(
    factory: async_sessionmaker,
    job_id: UUID,
    state: str,
    *,
    error: str | None = None,
    message_id: int | None = None,
    retry_after: int = 0,
) -> None:
    async with factory() as db, db.begin():
        job = await db.get(TelegramOutbox, job_id, with_for_update=True)
        if not job or job.state != "PROCESSING":
            return
        if state == "QUEUED" and job.attempts >= 3:
            state = "FAILED"
        job.state, job.error_code, job.provider_message_id = state, error, message_id
        job.finished_at = now() if state != "QUEUED" else None
        if state == "QUEUED":
            job.available_at = now() + timedelta(seconds=max(1, retry_after))
        if error in {"ACCESS_DENIED", "CHAT_UNAVAILABLE"}:
            current = await db.get(TelegramBinding, job.technician_id)
            if current and generation(current, job.destination) == job.generation:
                if job.destination == "PRIVATE_TELEGRAM":
                    current.private_availability = (
                        "BLOCKED" if error == "ACCESS_DENIED" else "UNAVAILABLE"
                    )
                else:
                    current.group_availability = "UNAVAILABLE"
        audit(
            db,
            "telegram.delivery_result",
            job.technician_id,
            actor_kind="TELEGRAM_WORKER",
            outcome=state,
        )


async def verify_pending(
    factory: async_sessionmaker, provider: TelegramProvider, job_id: UUID
) -> None:
    async with factory() as db:
        job = await db.get(TelegramOutbox, job_id)
        value = await db.get(TelegramInvitation, job.invitation_id) if job else None
        current = await db.get(TelegramBinding, job.technician_id) if job else None
        valid = bool(
            job
            and value
            and current
            and not value.closed_at
            and value.expires_at > now()
            and value.expected_generation == current.group_generation
            and value.expected_private_generation == current.private_generation
            and current.telegram_user_id is not None
            and value.candidate_chat_id is not None
            and value.candidate_user_id is not None
        )
    if not valid:
        await finish(factory, job_id, "CANCELLED", error="STALE_INVITATION")
        return
    checks = await verify_group(
        provider,
        value.candidate_chat_id,
        value.candidate_user_id,
        current.telegram_user_id,
        job.bot_id,
    )
    async with factory() as db, db.begin():
        fresh = await db.get(TelegramInvitation, value.id, with_for_update=True)
        if fresh and not fresh.closed_at and fresh.expires_at > now():
            fresh.initiator_admin, fresh.bot_admin, fresh.technician_member = (
                checks.initiator_admin,
                checks.bot_admin,
                checks.technician_member,
            )
            fresh.setup_error, fresh.verified_at = checks.error, now()
    await finish(factory, job_id, "SENT" if checks.passed else "FAILED", error=checks.error)


async def deliver_one(
    factory: async_sessionmaker, engine: AsyncEngine, provider: TelegramProvider, bot_id: int
) -> bool:
    selected = await claim_job(factory, bot_id)
    if not selected:
        return False
    job_id, technician_id = selected
    async with advisory_guard(engine, "technician", technician_id):
        async with factory() as db:
            job = await db.get(TelegramOutbox, job_id)
            current = await db.get(TelegramBinding, technician_id)
            technician = await db.get(Technician, technician_id)
            if not job or job.state != "PROCESSING":
                return True
            valid = bool(
                technician
                and technician.status == "ACTIVE"
                and current
                and current.bot_id == bot_id
                and generation(current, job.destination) == job.generation
                and current.private_generation == job.private_generation
            )
            target = approved_id(current, job.destination) if current else None
            available = valid and can_deliver(current, job.destination, bot_id)
        if not valid:
            await finish(factory, job_id, "CANCELLED", error="BINDING_CHANGED")
        elif job.kind == "VERIFY_GROUP":
            await verify_pending(factory, provider, job_id)
        elif not available or target is None:
            await finish(factory, job_id, "CANCELLED", error="DESTINATION_UNAVAILABLE")
        else:
            try:
                if job.destination == "WORK_GROUP":
                    bot = await provider.member(target, bot_id)
                    member = (
                        await provider.member(target, current.telegram_user_id)
                        if bot.status == "administrator"
                        else None
                    )
                    if (
                        not bot.present
                        or not bot.can_send_messages
                        or (member and not member.present)
                    ):
                        raise ProviderError("ACCESS_DENIED")
                # Dedicated advisory lock serializes sends with disconnect/replacement/deletion.
                # No transaction remains open while Telegram is being contacted.
                message = MESSAGES[job.kind]
                if job.kind == "APPROVED":
                    message = (
                        "You're connected to Technician Hub."
                        if job.destination == "PRIVATE_TELEGRAM"
                        else (
                            f"Technician Hub connected this group to {technician.first_name} "
                            f"{technician.last_name}."
                        )
                    )
                message_id = await provider.send(target, message)
                await finish(factory, job_id, "SENT", message_id=message_id)
            except ProviderError as error:
                if error.code == "RATE_LIMITED" and 0 <= error.retry_after <= 600:
                    await finish(
                        factory, job_id, "QUEUED", error=error.code, retry_after=error.retry_after
                    )
                else:
                    await finish(
                        factory,
                        job_id,
                        "UNKNOWN" if error.code == "NETWORK_UNCERTAIN" else "FAILED",
                        error=error.code,
                    )
    return True
