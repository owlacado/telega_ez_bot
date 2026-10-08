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


async def verify_automatic_group(
    provider: TelegramProvider, chat_id: int, bot_id: int
) -> GroupChecks:
    """The trusted command sender already proves the linked technician is in the group."""
    try:
        bot = await provider.member(chat_id, bot_id)
    except ProviderError as error:
        return GroupChecks(False, False, True, error.code)
    return GroupChecks(
        False,
        bot.status == "administrator",
        True,
        None if bot.present and bot.can_send_messages else "BOT_CANNOT_SEND",
    )


async def verify_bound_group(
    provider: TelegramProvider, chat_id: int, technician_user_id: int, bot_id: int
) -> None:
    """Read-only proof for an existing binding; never approves a new identity."""
    identity = await provider.initialize()
    if identity.id != bot_id:
        raise ProviderError("BOT_IDENTITY_MISMATCH")
    # Keep both reads fully awaited, including failures, before the caller opens
    # its final transaction. No sibling provider task may outlive this proof.
    bot = await provider.member(chat_id, bot_id)
    technician = await provider.member(chat_id, technician_user_id)
    if not bot.present or not bot.can_send_messages or not technician.present:
        raise ProviderError("ACCESS_DENIED")
