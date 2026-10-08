"""Private canonical daily accounting followed by the shared schedule enqueue."""

import hashlib
import logging
from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import select

from hub.accounting.service import calculate
from hub.integrations.models import TelegramBinding
from hub.schedule_delivery.service import create_dispatch
from hub.technicians.models import Technician
from hub.telegram.common import can_deliver
from hub.telegram.locks import advisory_guard
from hub.telegram.models import TelegramProcessedUpdate
from hub.telegram.notices import enqueue_daily_summary

SCHEDULE_FAILED = (
    "\n\nDaily report is ready, but your next schedule could not be sent. "
    "Please contact your manager."
)


def google_provider(settings):
    if settings.google_mode != "real":
        return None
    from hub.google_calendar.provider import GoogleCalendarProvider

    return GoogleCalendarProvider(settings)


def render_daily(daily):
    totals = daily.totals
    lines = [
        "Daily report",
        f"{daily.business_date} ({daily.accounting_timezone})",
        f"Reports: {totals.report_count}",
        f"Gross total: ${totals.gross_total:.2f}",
        f"Expenses: {totals.expense_count} | ${totals.expense_total:.2f}",
        f"Maintenance plans: {totals.maintenance_count}",
        "",
        "Payments:",
    ]
    lines.extend(
        f"{key.replace('_', ' ').title()}: ${value:.2f}" for key, value in totals.payments.items()
    )
    lines.append("Reviews:")
    lines.extend(f"{key.title()}: {value}" for key, value in totals.reviews.items())
    lines.append("Closed by:")
    lines.extend(
        f"{key.replace('_', ' ').title()}: {value}" for key, value in totals.closed_by.items()
    )
    return "\n".join(lines)


async def identity(factory, event, bot_id):
    async with factory() as db:
        row = (
            await db.execute(
                select(Technician, TelegramBinding)
                .join(TelegramBinding, TelegramBinding.technician_id == Technician.id)
                .where(TelegramBinding.telegram_user_id == event.user_id)
            )
        ).first()
        if (
            not row
            or row[0].status != "ACTIVE"
            or not can_deliver(row[1], "PRIVATE_TELEGRAM", bot_id)
        ):
            return None
        binding = row[1]
        return row[0].id, (
            binding.telegram_user_id,
            binding.private_generation,
            binding.group_generation,
            binding.telegram_group_chat_id,
        )


async def handle_daily(factory, event, bot_id, settings, provider):
    from hub.telegram.updates import UpdateResult

    async with factory() as db:
        admitted = await db.get(TelegramProcessedUpdate, (bot_id, event.update_id))
        if not admitted or admitted.outcome not in {"ADMITTED", "DAILY_ACCOUNTING_ATTEMPTED"}:
            return UpdateResult("DUPLICATE")
        # The reservation timestamp distinguishes Telegram ID reuse after retention/idle epochs.
        request_key = hashlib.sha256(
            f"{bot_id}:{event.update_id}:{admitted.processed_at.isoformat()}".encode()
        ).hexdigest()
    receipt_attempted = admitted.outcome == "DAILY_ACCOUNTING_ATTEMPTED"
    linked = await identity(factory, event, bot_id)
    if linked is None:
        outcome, reply = (
            "UNAVAILABLE",
            "Your connection is currently unavailable. Contact your manager.",
        )
    else:
        technician_id, binding = linked
        try:
            async with factory() as db:
                daily = await calculate(db, technician_id, "daily")
            reply = render_daily(daily)
            outcome = "DAILY_READY"
        except Exception:
            outcome, reply = (
                "DAILY_UNAVAILABLE",
                "Daily accounting is unavailable. Please contact your manager.",
            )
        if outcome == "DAILY_READY":
            # A private receipt is attempted BEFORE Google work, independently of schedule success.
            # Persist the attempt first; crash/ambiguous delivery must not blindly replay it.
            if not receipt_attempted:
                async with advisory_guard(factory.kw["bind"], "technician", technician_id):
                    current = await identity(factory, event, bot_id)
                    if (
                        current is None
                        or current[0] != technician_id
                        or current[1][:2] != binding[:2]
                    ):
                        reply = "Your connection changed. Please contact your manager."
                        outcome = "UNAVAILABLE"
                    else:
                        async with factory() as db, db.begin():
                            record = await db.get(
                                TelegramProcessedUpdate,
                                (bot_id, event.update_id),
                                with_for_update=True,
                            )
                            record.outcome = "DAILY_ACCOUNTING_ATTEMPTED"
                        try:
                            await provider.send(event.chat_id, reply)
                            reply = "Daily report is ready."
                        except Exception:
                            logging.getLogger(__name__).warning(
                                "Daily accounting receipt could not be confirmed"
                            )
                            reply = (
                                "Daily report was calculated, "
                                "but its delivery could not be confirmed."
                            )
            else:
                reply = "Daily report delivery was already attempted."
        if outcome == "DAILY_READY":
            try:
                summary_queued = await enqueue_daily_summary(
                    factory, technician_id, binding, bot_id, request_key, daily
                )
            except Exception:
                summary_queued = False
            if not summary_queued:
                reply += (
                    "\n\nDaily report is ready, but its Work Group summary could not be queued. "
                    "Please contact your manager."
                )
            try:
                request = SimpleNamespace(
                    app=SimpleNamespace(
                        state=SimpleNamespace(
                            settings=settings,
                            session_factory=factory,
                            google_lock_engine=factory.kw["bind"],
                            google_provider=google_provider(settings),
                        )
                    ),
                    state=SimpleNamespace(manager_id=None),
                )
                dispatch = await create_dispatch(
                    request, technician_id, daily_binding=binding, daily_request_key=request_key
                )
                if dispatch.status in {"PENDING", "PROCESSING"}:
                    reply += (
                        f"\n\nNext schedule for {dispatch.target_date} "
                        "is queued for your Work Group."
                    )
                elif dispatch.status == "SENT":
                    reply += (
                        f"\n\nNext schedule for {dispatch.target_date} was sent to your Work Group."
                    )
                else:
                    reply += SCHEDULE_FAILED
            except HTTPException as exc:
                reply += (
                    "\n\nYour next schedule was already sent to your Work Group."
                    if exc.detail == "ALREADY_SENT"
                    else SCHEDULE_FAILED
                )
            except Exception:
                reply += SCHEDULE_FAILED
        # Revalidate private identity after the provider read before disclosing accounting.
        current = await identity(factory, event, bot_id)
        if current is None or current[0] != technician_id or current[1][:2] != binding[:2]:
            outcome, reply = "UNAVAILABLE", "Your connection changed. Please contact your manager."
    async with factory() as db, db.begin():
        record = await db.get(
            TelegramProcessedUpdate, (bot_id, event.update_id), with_for_update=True
        )
        if not record or record.outcome not in {"ADMITTED", "DAILY_ACCOUNTING_ATTEMPTED"}:
            return UpdateResult("DUPLICATE")
        record.outcome = outcome
    return UpdateResult(outcome, reply)
