"""Daily and exact-dispatch notices on the existing Telegram outbox."""

import html
import secrets

from sqlalchemy.dialects.postgresql import insert

from hub.auth.security import now
from hub.integrations.models import TelegramBinding
from hub.schedule_delivery.domain import token_hash
from hub.schedule_delivery.models import ScheduleDispatch
from hub.technicians.models import Technician
from hub.telegram.activity import clip
from hub.telegram.common import can_deliver
from hub.telegram.models import TelegramOutbox
from hub.telegram.types import ProviderError
from hub.telegram.verification import verify_bound_group

SCHEDULE_NOTICE_KINDS = {"SCHEDULE_PROMPT", "SCHEDULE_CONFIRMED"}


def render_daily_summary(daily):
    totals = daily.totals
    name = clip(" ".join(daily.technician_name.split()), 250)
    return (
        f"\u2705 {name} completed Daily Report\n"
        f"{totals.report_count} reports \u00b7 ${totals.gross_total:.2f} gross "
        f"\u00b7 ${totals.expense_total:.2f} expenses"
    )


async def enqueue_daily_summary(factory, technician_id, expected, bot_id, request_key, daily):
    async with factory() as db, db.begin():
        tech = await db.get(Technician, technician_id, with_for_update=True)
        binding = await db.get(TelegramBinding, technician_id)
        available = bool(
            tech
            and tech.status == "ACTIVE"
            and binding
            and can_deliver(binding, "WORK_GROUP", bot_id)
            and (
                binding.telegram_user_id,
                binding.private_generation,
                binding.group_generation,
                binding.telegram_group_chat_id,
            )
            == expected
        )
        await db.execute(
            insert(TelegramOutbox)
            .values(
                technician_id=technician_id,
                bot_id=bot_id,
                kind="DAILY_SUMMARY",
                destination="WORK_GROUP",
                generation=expected[2],
                private_generation=expected[1],
                activity_chat_id=expected[3],
                activity_user_id=expected[0],
                daily_request_key=request_key,
                summary_text=render_daily_summary(daily),
                state="QUEUED" if available else "CANCELLED",
                error_code=None if available else "DESTINATION_UNAVAILABLE",
                finished_at=None if available else now(),
            )
            .on_conflict_do_nothing(constraint="uq_telegram_daily_summary")
        )
        return available


async def enqueue_schedule_notice(db, dispatch, kind):
    private = kind == "SCHEDULE_PROMPT"
    await db.execute(
        insert(TelegramOutbox)
        .values(
            technician_id=dispatch.technician_id,
            bot_id=dispatch.bot_id,
            kind=kind,
            schedule_id=dispatch.id,
            destination="PRIVATE_TELEGRAM" if private else "WORK_GROUP",
            generation=dispatch.private_generation if private else dispatch.group_generation,
            private_generation=dispatch.private_generation,
            activity_chat_id=dispatch.chat_id,
            activity_user_id=dispatch.telegram_user_id,
        )
        .on_conflict_do_nothing(constraint="uq_telegram_schedule_notice")
    )


def current_notice(job, row, binding, tech):
    return bool(
        job
        and job.state == "PROCESSING"
        and row
        and row.status == "SENT"
        and row.superseded_at is None
        and row.destination == "WORK_GROUP"
        and tech
        and tech.status == "ACTIVE"
        and binding
        and job.technician_id == row.technician_id
        and job.bot_id == row.bot_id
        and can_deliver(binding, "WORK_GROUP", job.bot_id)
        and binding.telegram_user_id == row.telegram_user_id == job.activity_user_id
        and binding.telegram_group_chat_id == row.chat_id == job.activity_chat_id
        and binding.private_generation == row.private_generation == job.private_generation
        and binding.group_generation == row.group_generation
        and (
            job.kind != "SCHEDULE_PROMPT"
            or (
                row.private_ack_required
                and row.ack_message_id is None
                and row.ack_status == "PENDING"
                and row.ack_expires_at > now()
            )
        )
        and (job.kind != "SCHEDULE_CONFIRMED" or row.ack_status == "ACKNOWLEDGED")
    )


async def deliver_schedule_notice(factory, provider, job_id):
    # The caller owns the existing technician advisory lock and PROCESSING marker.
    from hub.telegram.delivery import finish

    async with factory() as db:
        job = await db.get(TelegramOutbox, job_id)
        row = await db.get(ScheduleDispatch, job.schedule_id)
        binding = await db.get(TelegramBinding, job.technician_id)
        tech = await db.get(Technician, job.technician_id)
        valid = current_notice(job, row, binding, tech)
    if not valid:
        await finish(factory, job_id, "CANCELLED", error="BINDING_OR_SCHEDULE_CHANGED")
        return
    send_started = False
    try:
        await verify_bound_group(provider, row.chat_id, row.telegram_user_id, row.bot_id)
        async with factory() as db, db.begin():
            tech = await db.get(Technician, job.technician_id, with_for_update=True)
            binding = await db.get(TelegramBinding, job.technician_id)
            row = await db.get(ScheduleDispatch, job.schedule_id, with_for_update=True)
            job = await db.get(TelegramOutbox, job_id, with_for_update=True)
            if not current_notice(job, row, binding, tech):
                if job.state == "PROCESSING":
                    job.state, job.error_code, job.finished_at = (
                        "CANCELLED",
                        "BINDING_OR_SCHEDULE_CHANGED",
                        now(),
                    )
                return
            name = clip(" ".join(f"{tech.first_name} {tech.last_name}".split()), 250)
            if job.kind == "SCHEDULE_PROMPT":
                token = secrets.token_urlsafe(32)
                row.ack_token_hash = token_hash(token)
                target = row.telegram_user_id
                message = (
                    f"<b>Confirm schedule</b>\n{row.target_date:%A, %B %d, %Y}\n"
                    f"{html.escape(name)} \u00b7 {row.job_count} jobs\n"
                    "See the official schedule in your Work Group. "
                    "Confirm that you have seen this exact schedule."
                )
            else:
                target = row.chat_id
                message = (
                    f"\u2705 Confirmed by {name}\nSchedule: {row.target_date}\n"
                    f"{row.acknowledged_at:%Y-%m-%d %H:%M:%S %Z}"
                )
        send_started = True
        message_id = (
            await provider.send_schedule(target, message, "sch:" + token)
            if job.kind == "SCHEDULE_PROMPT"
            else await provider.send(target, message)
        )
        if not isinstance(message_id, int) or isinstance(message_id, bool) or message_id <= 0:
            raise ProviderError("NETWORK_UNCERTAIN")
        await finish(factory, job_id, "SENT", message_id=message_id)
    except Exception as exc:
        error = exc if isinstance(exc, ProviderError) else ProviderError("NETWORK_UNCERTAIN")
        if error.code == "RATE_LIMITED" and 0 <= error.retry_after <= 600:
            await finish(factory, job_id, "QUEUED", error=error.code, retry_after=error.retry_after)
        else:
            if not send_started and job.kind == "SCHEDULE_PROMPT":
                await finish(factory, job_id, "FAILED", error="GROUP_UNVERIFIED")
                return
            await finish(
                factory,
                job_id,
                "UNKNOWN"
                if send_started and error.code in {"NETWORK_UNCERTAIN", "PROVIDER_UNAVAILABLE"}
                else "FAILED",
                error=error.code,
            )
