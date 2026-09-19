from contextlib import AsyncExitStack
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import async_sessionmaker

from hub.integrations.models import TelegramBinding
from hub.integrations.ports import TelegramProvider
from hub.technicians.models import Technician
from hub.telegram.claims import consume_claim, prepare_claim
from hub.telegram.common import can_deliver
from hub.telegram.lifecycle import lifecycle
from hub.telegram.locks import advisory_guard
from hub.telegram.models import TelegramProcessedUpdate
from hub.telegram.types import TrustedEvent

REPLIES = {
    "INVITATION_REQUIRED": (
        "This Telegram account is not connected to Technician Hub. "
        "Ask your manager for a connection link."
    ),
    "INVALID_INVITATION": (
        "This invitation is invalid, expired, or already used. Ask your manager for a new link."
    ),
    "AWAITING_APPROVAL": (
        "Invitation received. Your account or group is awaiting manager "
        "approval; access has not been granted yet."
    ),
    "NEEDS_SETUP": (
        "Invitation received, but group permissions or membership need "
        "attention. Ask your manager to review setup checks and retry "
        "verification."
    ),
    "CONNECTED": (
        "You're connected to Technician Hub. /report — Submit Report; /expenses — Expenses"
    ),
    "UNAVAILABLE": "Your connection is currently unavailable. Contact your manager.",
    "HELP": (
        "Use your manager's /start invitation to connect. /status shows "
        "connection status. /getid shows your own Telegram ID in a private chat. "
        "/report — Submit Report; /expenses — Expenses. Use Schedule received "
        "on your delivered schedule to acknowledge it."
    ),
}


@dataclass(frozen=True)
class UpdateResult:
    outcome: str
    reply: str | None = field(default=None, repr=False)


async def operational_access(db, user_id: int, bot_id: int) -> bool:
    row = (
        await db.execute(
            select(Technician.status, TelegramBinding)
            .join(TelegramBinding, TelegramBinding.technician_id == Technician.id)
            .where(TelegramBinding.telegram_user_id == user_id)
        )
    ).first()
    return bool(row and row[0] == "ACTIVE" and can_deliver(row[1], "PRIVATE_TELEGRAM", bot_id))


async def process_update(
    factory: async_sessionmaker,
    provider: TelegramProvider,
    event: TrustedEvent,
    bot_id: int,
    *,
    settings=None,
) -> UpdateResult:
    if event.kind == "CALLBACK":
        # Clear Telegram's progress indicator promptly, before database work. A failure
        # to answer is cosmetic and must not prevent the authoritative acknowledgement.
        try:
            await provider.answer_callback(event.callback_query_id, "Checking schedule receipt...")
        except Exception:
            pass
        from hub.schedule_delivery.acknowledgements import acknowledge

        outcome = await acknowledge(factory, event, bot_id)
        try:
            await provider.answer_callback(
                event.callback_query_id,
                "Schedule received."
                if outcome == "ACKNOWLEDGED"
                else "Receipt unavailable. Check your current connection or try again.",
            )
        except Exception:
            pass
        return UpdateResult(outcome)
    async with factory() as db:
        if await db.get(TelegramProcessedUpdate, (bot_id, event.update_id)):
            return UpdateResult("DUPLICATE")
    proof = await prepare_claim(factory, event, provider, bot_id)
    async with AsyncExitStack() as locks:
        if proof:
            await locks.enter_async_context(
                advisory_guard(factory.kw["bind"], "technician", proof.technician_id)
            )
        async with factory() as db, db.begin():
            inserted = await db.scalar(
                insert(TelegramProcessedUpdate)
                .values(bot_id=bot_id, update_id=event.update_id, outcome="PROCESSING")
                .on_conflict_do_nothing()
                .returning(TelegramProcessedUpdate.update_id)
            )
            if inserted is None:
                return UpdateResult("DUPLICATE")
            result = "IGNORED"
            reply = None
            if event.kind in {"BOT_MEMBERSHIP", "MEMBER", "MIGRATION"}:
                result = await lifecycle(db, event, bot_id)
            elif (
                event.kind == "COMMAND"
                and not event.user_is_bot
                and not event.anonymous
                and event.user_id is not None
            ):
                if event.command == "/start" and event.payload:
                    result = await consume_claim(db, event, proof, bot_id)
                elif event.chat_type == "private" and event.chat_id == event.user_id:
                    if event.command == "/help":
                        result = "HELP"
                    elif event.command == "/expenses":
                        from hub.core.config import Settings
                        from hub.expenses.service import issue

                        config = settings or Settings()
                        token = await issue(db, event, bot_id, config)
                        result = "EXPENSE_FORM" if token else "UNAVAILABLE"
                        reply = (
                            (
                                "Expenses\nOpen this private link within 15 minutes. "
                                "Do not share it.\n"
                                f"{config.allowed_origins[0]}/technician/expense#{token}"
                            )
                            if token
                            else (
                                "Expenses unavailable. Ask your manager to check your "
                                "connection and "
                                "accounting timezone."
                            )
                        )
                    elif event.command == "/report":
                        from hub.core.config import Settings
                        from hub.work_reports.service import issue

                        config = settings or Settings()
                        token = await issue(db, event, bot_id, config)
                        result = "WORK_REPORT_FORM" if token else "INVITATION_REQUIRED"
                        if token:
                            reply = (
                                "Submit Report\nOpen this private link within 15 minutes. "
                                "Do not share it.\n"
                                f"{config.allowed_origins[0]}/technician/work-report#{token}"
                            )
                    elif event.command in {None, "/start", "/status"}:
                        linked = await db.scalar(
                            select(TelegramBinding.technician_id).where(
                                TelegramBinding.telegram_user_id == event.user_id,
                                TelegramBinding.bot_id == bot_id,
                            )
                        )
                        result = (
                            "CONNECTED"
                            if await operational_access(db, event.user_id, bot_id)
                            else "UNAVAILABLE"
                            if linked
                            else "INVITATION_REQUIRED"
                        )
                    elif event.command == "/getid":
                        result, reply = (
                            "OWN_ID",
                            f"Your Telegram user ID is {event.user_id}. "
                            "This is not required for manager onboarding.",
                        )
                if event.chat_type in {"private", "group", "supergroup"}:
                    reply = reply or REPLIES.get(result)
                if proof and result == "CONNECTED":
                    reply = None  # Durable, generation-checked outbox sends the confirmation.
            record = await db.get(TelegramProcessedUpdate, (bot_id, event.update_id))
            record.outcome = result
        return UpdateResult(result, reply)
