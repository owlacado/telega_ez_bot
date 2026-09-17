import asyncio

from hub.integrations.ports import TelegramProvider
from hub.telegram.types import GroupChecks, ProviderError


async def verify_group(
    provider: TelegramProvider, chat_id: int, actor_id: int, technician_user_id: int, bot_id: int
) -> GroupChecks:
    try:
        actor, bot, technician = await asyncio.gather(
            provider.member(chat_id, actor_id),
            provider.member(chat_id, bot_id),
            provider.member(chat_id, technician_user_id),
        )
    except ProviderError as error:
        return GroupChecks(False, False, False, error.code)
    actor_ok = actor.status in {"creator", "administrator"} and not actor.is_anonymous
    bot_ok = bot.status == "administrator"
    error = (
        None
        if actor_ok and bot_ok and technician.present
        else "INITIATOR_NOT_ADMIN"
        if not actor_ok
        else "BOT_ADMIN_REQUIRED"
        if not bot_ok
        else "TECHNICIAN_NOT_MEMBER"
    )
    return GroupChecks(actor_ok, bot_ok, technician.present, error)
