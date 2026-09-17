"""Explicit opt-in Bot API adapter. Never uses Application/Updater bootstrap helpers."""

import logging
from pathlib import Path

from telegram import Bot
from telegram.error import (
    BadRequest,
    Conflict,
    Forbidden,
    InvalidToken,
    NetworkError,
    RetryAfter,
    TelegramError,
    TimedOut,
)
from telegram.request import HTTPXRequest

from hub.core.config import Settings
from hub.telegram.transport import parse_update
from hub.telegram.types import BotIdentity, Member, ProviderError, TrustedEvent


def safe_error(error: Exception) -> ProviderError:
    if isinstance(error, Conflict):
        return ProviderError("POLLING_CONFLICT")
    if isinstance(error, InvalidToken):
        return ProviderError("INVALID_BOT_CREDENTIALS")
    if isinstance(error, Forbidden):
        return ProviderError("ACCESS_DENIED")
    if isinstance(error, RetryAfter):
        value = error.retry_after
        return ProviderError(
            "RATE_LIMITED",
            retry_after=int(value.total_seconds() if hasattr(value, "total_seconds") else value),
        )
    if isinstance(error, BadRequest):
        return ProviderError("REQUEST_REJECTED")
    if isinstance(error, (TimedOut, NetworkError)):
        return ProviderError("NETWORK_UNCERTAIN")
    return ProviderError("PROVIDER_UNAVAILABLE")


class TelegramBotAdapter:
    def __init__(self, settings: Settings):
        if (
            settings.telegram_mode != "real"
            or not settings.telegram_expected_bot_id
            or not settings.telegram_expected_bot_username
        ):
            raise ProviderError("BOT_NOT_CONFIGURED")
        token = (
            settings.telegram_bot_token.get_secret_value() if settings.telegram_bot_token else None
        )
        if settings.telegram_token_file:
            token = Path(settings.telegram_token_file).read_text(encoding="utf-8").strip()
        if not token:
            raise ProviderError("BOT_NOT_CONFIGURED")
        # Library debug/HTTP exception logs may contain token URLs or full update bodies.
        for name in ["telegram", "httpx", "httpcore"]:
            logging.getLogger(name).setLevel(logging.CRITICAL + 1)
        self.settings = settings
        self.bot = Bot(
            token,
            request=HTTPXRequest(
                connect_timeout=5,
                read_timeout=10,
                write_timeout=10,
                pool_timeout=5,
                httpx_kwargs={"trust_env": False},
            ),
            get_updates_request=HTTPXRequest(
                connect_timeout=5,
                read_timeout=35,
                write_timeout=10,
                pool_timeout=5,
                httpx_kwargs={"trust_env": False},
            ),
        )

    async def initialize(self) -> BotIdentity:
        try:
            # Bot.initialize only initializes HTTP resources and calls getMe; no webhook mutation.
            await self.bot.initialize()
            return BotIdentity(self.bot.id, self.bot.username)
        except TelegramError as error:
            raise safe_error(error) from None

    async def webhook_configured(self) -> bool:
        try:
            return bool((await self.bot.get_webhook_info()).url)
        except TelegramError as error:
            raise safe_error(error) from None

    async def updates(self, offset: int | None) -> list[TrustedEvent]:
        try:
            updates = await self.bot.get_updates(
                offset=offset,
                timeout=25,
                limit=50,
                allowed_updates=["message", "my_chat_member", "chat_member"],
            )
            return [
                parse_update(value.to_dict(), self.settings.telegram_expected_bot_username)
                for value in updates
            ]
        except TelegramError as error:
            raise safe_error(error) from None

    async def member(self, chat_id: int, user_id: int) -> Member:
        try:
            value = await self.bot.get_chat_member(chat_id, user_id)
            return Member(
                str(value.status),
                getattr(value, "is_member", False),
                getattr(value, "is_anonymous", False),
                getattr(value, "can_send_messages", True),
            )
        except TelegramError as error:
            raise safe_error(error) from None

    async def send(self, chat_id: int, message: str) -> int:
        try:
            return (await self.bot.send_message(chat_id, message, protect_content=True)).message_id
        except TelegramError as error:
            raise safe_error(error) from None

    async def close(self) -> None:
        await self.bot.shutdown()
