"""Native command menus, using Bot API stubs only (no provider traffic)."""

from dataclasses import replace
from types import MethodType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker
from telegram import ReplyKeyboardRemove
from telegram.error import NetworkError

from hub.telegram.adapter import TelegramBotAdapter
from hub.telegram.delivery import deliver_one
from hub.telegram.updates import process_update
from tests.fakes import BOT_ID, BOT_USERNAME, FakeTelegram
from tests.telegram_helpers import event, issue, technician

REAL_SEND = TelegramBotAdapter.send


@pytest.fixture
def adapter():
    value = object.__new__(TelegramBotAdapter)
    # Exercise serialization with a fully stubbed Bot; global network guards stay active.
    value.send = MethodType(REAL_SEND, value)
    value.bot = SimpleNamespace(
        set_my_commands=AsyncMock(return_value=True),
        set_chat_menu_button=AsyncMock(return_value=True),
        send_message=AsyncMock(return_value=SimpleNamespace(message_id=42)),
    )
    return value


@pytest.mark.parametrize(
    "message",
    [
        "You're connected to Technician Hub.",
        "You're connected to Technician Hub. /report /expenses",
        "Submit Report\nOpen this private link",
        "Expenses\nOpen this private link",
    ],
)
async def test_connected_private_menu_exact_commands_and_keyboard_removal(adapter, message):
    assert await adapter.send(12345678, message) == 42
    call = adapter.bot.set_my_commands.call_args
    assert [c.to_dict() for c in call.args[0]] == [
        {"command": "report", "description": "Submit a report"},
        {"command": "expenses", "description": "Expenses"},
    ]
    assert call.kwargs["scope"].to_dict() == {"type": "chat", "chat_id": 12345678}
    assert call.kwargs["language_code"] == ""
    button = adapter.bot.set_chat_menu_button.call_args.kwargs
    assert button["chat_id"] == 12345678
    assert button["menu_button"].to_dict() == {"type": "commands"}
    sent = adapter.bot.send_message.call_args
    assert sent.args == (12345678, message)
    assert isinstance(sent.kwargs["reply_markup"], ReplyKeyboardRemove)
    assert sent.kwargs["protect_content"] is True
    assert sent.kwargs["link_preview_options"].is_disabled


@pytest.mark.parametrize(
    "chat_id,message",
    [
        (-100123, "You're connected to Technician Hub."),
        (-100123, "Submit Report\nOpen this private link"),
        (-100123, "Expenses\nOpen this private link"),
        (12345678, "This invitation is invalid, expired, or already used."),
        (12345678, "Your connection is currently unavailable. Contact your manager."),
    ],
)
async def test_no_menu_for_groups_or_unavailable_private_users(adapter, chat_id, message):
    await adapter.send(chat_id, message)
    adapter.bot.set_my_commands.assert_not_awaited()
    adapter.bot.set_chat_menu_button.assert_not_awaited()
    if chat_id < 0:
        assert adapter.bot.send_message.call_args.kwargs["reply_markup"] is None


@pytest.mark.parametrize("method", ["set_my_commands", "set_chat_menu_button"])
async def test_menu_failure_preserves_delivery_and_next_session_retries(adapter, method, caplog):
    getattr(adapter.bot, method).side_effect = NetworkError("secret-canary-token")
    assert await adapter.send(12345678, "You're connected to Technician Hub.") == 42
    assert "secret-canary-token" not in caplog.text
    getattr(adapter.bot, method).side_effect = None
    assert await adapter.send(12345678, "You're connected to Technician Hub.") == 42
    assert adapter.bot.set_my_commands.await_count == 2
    assert adapter.bot.send_message.await_count == 2


async def test_real_onboarding_outbox_and_subsequent_start_menu(client, engine, adapter, app):
    app.state.settings = app.state.settings.model_copy(
        update={
            "telegram_mode": "fake",
            "allow_fake_providers": True,
            "telegram_expected_bot_id": BOT_ID,
            "telegram_expected_bot_username": BOT_USERNAME,
        }
    )
    identifier = await technician(client)
    invitation = await issue(client, identifier)
    incoming = event(invitation)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    provider = FakeTelegram()
    assert (await process_update(factory, provider, incoming, BOT_ID)).outcome == "CONNECTED"
    assert await deliver_one(factory, engine, adapter, BOT_ID)
    assert isinstance(
        adapter.bot.send_message.call_args.kwargs["reply_markup"], ReplyKeyboardRemove
    )
    assert adapter.bot.set_my_commands.await_count == 1
    assert (await process_update(factory, provider, incoming, BOT_ID)).outcome == "DUPLICATE"
    assert not await deliver_one(factory, engine, adapter, BOT_ID)
    assert adapter.bot.set_my_commands.await_count == 1
    home = await process_update(
        factory, provider, replace(incoming, update_id=2, payload=None), BOT_ID
    )
    assert home.outcome == "CONNECTED"
    await adapter.send(incoming.chat_id, home.reply)
    assert adapter.bot.set_my_commands.await_count == 2
