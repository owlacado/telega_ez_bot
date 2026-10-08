"""Private ACK + full canonical daily group report, with isolated DB and fake providers."""

import asyncio
import html
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from hub.accounting.service import calculate
from hub.integrations.models import TelegramBinding
from hub.schedule_delivery.acknowledgements import acknowledge
from hub.schedule_delivery.models import ScheduleDispatch
from hub.telegram import daily, delivery
from hub.telegram.adapter import TelegramBotAdapter
from hub.telegram.models import TelegramOutbox, TelegramProcessedUpdate
from hub.telegram.notices import render_daily_summary
from hub.telegram.types import ProviderError, TrustedEvent
from hub.telegram.updates import process_update
from tests.accounting_data import seed
from tests.fakes import BOT_ID, FakeTelegram
from tests.test_daily_schedule import command, daily_setup
from tests.test_schedule_delivery import assigned as assigned
from tests.test_schedule_delivery import enqueue, row, run_delivery
from tests.test_schedule_delivery import google as google
from tests.test_schedule_delivery import ready as ready

REAL_SCHEDULE_SEND = TelegramBotAdapter.send_schedule


async def drain(app, fake):
    while await delivery.deliver_one(
        app.state.session_factory, app.state.google_lock_engine, fake, BOT_ID, app.state.settings
    ):
        pass


async def jobs(app, kind):
    async with app.state.session_factory() as db:
        return list(await db.scalars(select(TelegramOutbox).where(TelegramOutbox.kind == kind)))


async def sent_dispatch(app, client, ready, fake):
    data = await enqueue(client, ready)
    await run_delivery(app, fake)
    await drain(app, fake)
    stored = await row(app, data["id"])
    prompt = next(message for message in fake.schedule_sent if message[0] > 0)
    return stored, TrustedEvent(
        91001,
        "CALLBACK",
        chat_type="private",
        chat_id=771001,
        user_id=771001,
        message_id=stored.ack_message_id,
        payload=prompt[2],
        callback_query_id="synthetic-query",
    )


@pytest.mark.parametrize("nonzero", [False, True])
async def test_daily_private_accounting_and_one_canonical_group_summary(
    app, client, google, ready, monkeypatch, nonzero
):
    await daily_setup(app, ready, google, monkeypatch)
    async with app.state.session_factory() as db:
        projection = await calculate(db, ready, "daily")
    if nonzero:
        await seed(
            app.state.session_factory,
            projection.business_date,
            technician_id=ready,
            reports=[
                {"day": 0, "amount": "450.00", "payment_method": "CASH"},
                {"day": 0, "amount": "500.00", "payment_method": "CASH"},
            ],
            expenses=[
                {"day": 0, "amount": "50.00", "revision_number": 2, "previous_amount": "90.00"}
            ],
        )
    fake = FakeTelegram()
    fake.group(-771002, 771001, 771001)
    result = await process_update(
        app.state.session_factory, fake, command(), BOT_ID, settings=app.state.settings
    )
    assert result.outcome == "DAILY_READY"
    async with app.state.session_factory() as db:
        projection = await calculate(db, ready, "daily")
    assert fake.sent[0] == (771001, daily.render_daily(projection))
    await drain(app, fake)
    summaries = [message for chat, message in fake.sent if chat == -771002]
    assert summaries == [render_daily_summary(projection)]
    assert summaries[0] == fake.sent[0][1]
    assert ("Reports: 2" if nonzero else "Reports: 0") in summaries[0]
    assert ("Gross total: $950.00" if nonzero else "Gross total: $0.00") in summaries[0]
    assert "Payments:" in summaries[0] and "Reviews:" in summaries[0]
    for prohibited in ["771001", str(ready), "sch:"]:
        assert prohibited not in summaries[0]
    # Replayed completed action and crash after intent, before marking update completed.
    assert (
        await process_update(
            app.state.session_factory, fake, command(), BOT_ID, settings=app.state.settings
        )
    ).outcome == "DUPLICATE"
    async with app.state.session_factory() as db, db.begin():
        record = await db.get(TelegramProcessedUpdate, (BOT_ID, command().update_id))
        record.outcome = "DAILY_ACCOUNTING_ATTEMPTED"
    await process_update(
        app.state.session_factory, fake, command(), BOT_ID, settings=app.state.settings
    )
    await drain(app, fake)
    assert len(await jobs(app, "DAILY_SUMMARY")) == 1
    assert [message for chat, message in fake.sent if chat == -771002] == summaries


async def test_group_schedule_no_button_private_prompt_and_one_confirmation(app, client, ready):
    fake = FakeTelegram()
    dispatch, event = await sent_dispatch(app, client, ready, fake)
    assert dispatch.private_ack_required and dispatch.ack_message_id
    group, prompt = fake.schedule_sent
    assert group[0] == -771002 and group[2] is None
    assert "Waiting for technician confirmation" in group[1]
    assert prompt[0] == 771001 and prompt[2].startswith("sch:")
    assert group[1] == prompt[1] + "\n\n\u23f3 Waiting for technician confirmation"
    preview = await client.get(f"/api/technicians/{ready}/calendar/next-schedule")
    assert preview.status_code == 200
    assert preview.json()["presentation"] == html.unescape(
        prompt[1].replace("<b>", "").replace("</b>", "")
    )
    assert "DESCRIPTION_CANARY" in prompt[1] and str(dispatch.target_date.year) in prompt[1]
    results = await asyncio.gather(
        *[acknowledge(app.state.session_factory, event, BOT_ID) for _ in range(3)]
    )
    assert results == ["ACKNOWLEDGED"] * 3
    stamp = (await row(app, dispatch.id)).acknowledged_at
    assert len(await jobs(app, "SCHEDULE_CONFIRMED")) == 1
    await drain(app, fake)
    confirmations = [m for c, m in fake.sent if c == -771002 and "Confirmed by" in m]
    assert len(confirmations) == 1 and str(dispatch.target_date) in confirmations[0]
    assert "UTC" in confirmations[0]
    await process_update(
        app.state.session_factory, fake, event, BOT_ID, settings=app.state.settings
    )
    assert "already confirmed" in fake.callbacks[-1][1]
    await process_update(
        app.state.session_factory, fake, event, BOT_ID, settings=app.state.settings
    )
    assert len(fake.callbacks) == 2 and "Checking" not in str(fake.callbacks)
    await drain(app, fake)
    assert len(await jobs(app, "SCHEDULE_CONFIRMED")) == 1
    assert (await row(app, dispatch.id)).acknowledged_at == stamp
    history = (await client.get(f"/api/technicians/{ready}/schedule-delivery")).json()["history"][0]
    assert history["ack_status"] == "ACKNOWLEDGED" and history["acknowledged_at"]
    assert "ack_message_id" not in history and "ack_token_hash" not in history


@pytest.mark.parametrize(
    "attack",
    [
        "manager",
        "group",
        "message",
        "token",
        "anonymous",
        "bot",
        "private_generation",
        "group_generation",
        "unavailable",
        "revalidation",
        "wrong_group",
        "wrong_binding",
    ],
)
async def test_private_ack_security(app, client, ready, attack):
    fake = FakeTelegram()
    dispatch, event = await sent_dispatch(app, client, ready, fake)
    if attack == "manager":
        event = replace(event, user_id=999)
    elif attack == "group":
        event = replace(
            event, chat_id=-771002, chat_type="supergroup", message_id=dispatch.message_id
        )
    elif attack == "message":
        event = replace(event, message_id=999)
    elif attack == "token":
        event = replace(event, payload="sch:invalid")
    elif attack == "anonymous":
        event = replace(event, anonymous=True)
    elif attack == "bot":
        event = replace(event, user_is_bot=True)
    else:
        async with app.state.session_factory() as db, db.begin():
            binding = await db.get(TelegramBinding, ready)
            if attack == "private_generation":
                binding.private_generation += 1
                binding.group_private_generation = binding.private_generation
            elif attack == "group_generation":
                binding.group_generation += 1
            elif attack == "unavailable":
                binding.group_availability = "UNAVAILABLE"
            elif attack == "revalidation":
                binding.group_availability = "REVALIDATION_REQUIRED"
            elif attack == "wrong_group":
                binding.telegram_group_chat_id = -999
            elif attack == "wrong_binding":
                binding.telegram_user_id = 999
    result = await process_update(
        app.state.session_factory, fake, event, BOT_ID, settings=app.state.settings
    )
    assert result.outcome not in {"ACKNOWLEDGED", "ACK_ALREADY_ACKNOWLEDGED"}
    assert len(fake.callbacks) == 1 and "Checking" not in fake.callbacks[0][1]
    assert (await row(app, dispatch.id)).ack_status == "PENDING"
    assert not await jobs(app, "SCHEDULE_CONFIRMED")


async def test_superseded_private_button_clear_feedback_new_schedule_needs_ack(
    app, client, google, ready
):
    fake = FakeTelegram()
    old, event = await sent_dispatch(app, client, ready, fake)
    assert await acknowledge(app.state.session_factory, event, BOT_ID) == "ACKNOWLEDGED"
    google.events = []
    new = await enqueue(client, ready)
    result = await process_update(
        app.state.session_factory, fake, event, BOT_ID, settings=app.state.settings
    )
    assert result.outcome == "ACK_SUPERSEDED"
    assert "has been updated" in fake.callbacks[-1][1]
    assert (await row(app, old.id)).superseded_at
    await run_delivery(app, fake)
    await drain(app, fake)
    fresh = await row(app, new["id"])
    assert fresh.ack_status == "PENDING" and fresh.acknowledged_at is None
    current = replace(
        event, update_id=91002, payload=fake.schedule_sent[-1][2], message_id=fresh.ack_message_id
    )
    assert await acknowledge(app.state.session_factory, current, BOT_ID) == "ACKNOWLEDGED"
    await drain(app, fake)
    # The old queued confirmation cannot masquerade as confirmation of the updated schedule.
    assert [j.state for j in await jobs(app, "SCHEDULE_CONFIRMED")].count("SENT") == 1


@pytest.mark.parametrize("kind", ["DAILY_SUMMARY", "SCHEDULE_PROMPT", "SCHEDULE_CONFIRMED"])
async def test_ambiguous_notice_never_blindly_retried(
    app, client, google, ready, monkeypatch, kind
):
    fake = FakeTelegram()
    fake.group(-771002, 771001, 771001)
    if kind == "DAILY_SUMMARY":
        await daily_setup(app, ready, google, monkeypatch)
        await process_update(
            app.state.session_factory, fake, command(), BOT_ID, settings=app.state.settings
        )
    elif kind == "SCHEDULE_PROMPT":
        await enqueue(client, ready)
        await run_delivery(app, fake)
    else:
        _, event = await sent_dispatch(app, client, ready, fake)
        await acknowledge(app.state.session_factory, event, BOT_ID)
    fake.send_error = ProviderError("NETWORK_UNCERTAIN")
    await drain(app, fake)
    assert (await jobs(app, kind))[0].state == "UNKNOWN"
    fake.send_error = None
    before = list(fake.sent)
    await delivery.recover_processing(app.state.session_factory, BOT_ID)
    await drain(app, fake)
    assert fake.sent == before


async def test_accounting_survives_summary_enqueue_failure_and_schedule_failure(
    app, google, ready, monkeypatch
):
    await daily_setup(app, ready, google, monkeypatch)

    async def broken(*args, **kwargs):
        raise RuntimeError("PRIVATE_ERROR_DETAIL")

    monkeypatch.setattr(daily, "enqueue_daily_summary", broken)
    monkeypatch.setattr(daily, "create_dispatch", broken)
    fake = FakeTelegram()
    result = await process_update(
        app.state.session_factory, fake, command(), BOT_ID, settings=app.state.settings
    )
    assert result.outcome == "DAILY_READY" and "Gross total:" in fake.sent[0][1]
    assert (
        "summary could not be queued" in result.reply
        and "schedule could not be sent" in result.reply
    )
    assert "PRIVATE_ERROR_DETAIL" not in result.reply


async def test_provider_calls_outside_transactions_and_membership_race(app, client, ready):
    fake = FakeTelegram()
    await enqueue(client, ready)
    await run_delivery(app, fake)
    original = fake.member
    changed = False

    async def member(chat, actor):
        nonlocal changed
        async with app.state.session_factory() as db:
            assert (
                await db.scalar(
                    text(
                        "SELECT count(*) FROM pg_stat_activity WHERE "
                        "datname=current_database() AND state='idle in transaction'"
                    )
                )
                == 0
            )
        result = await original(chat, actor)
        if not changed:
            changed = True
            async with app.state.session_factory() as db, db.begin():
                binding = await db.get(TelegramBinding, ready)
                binding.group_availability = "UNAVAILABLE"
        return result

    fake.member = member
    await drain(app, fake)
    assert len(fake.schedule_sent) == 1  # Only the earlier official group schedule.
    assert (await jobs(app, "SCHEDULE_PROMPT"))[0].state == "CANCELLED"


async def test_database_guards_private_prompt_receipt_and_summary_snapshot(
    app, client, google, ready, monkeypatch
):
    fake = FakeTelegram()
    dispatch, _ = await sent_dispatch(app, client, ready, fake)
    async with app.state.session_factory() as db:
        stored = await db.get(ScheduleDispatch, dispatch.id)
        stored.ack_message_id += 1
        with pytest.raises(IntegrityError):
            await db.commit()
    await daily_setup(app, ready, google, monkeypatch)
    await process_update(
        app.state.session_factory, fake, command(), BOT_ID, settings=app.state.settings
    )
    summary = (await jobs(app, "DAILY_SUMMARY"))[0]
    async with app.state.session_factory() as db:
        stored = await db.get(TelegramOutbox, summary.id)
        stored.summary_text = "tampered"
        with pytest.raises(IntegrityError):
            await db.commit()


@pytest.mark.parametrize("callback", [None, "sch:synthetic"])
async def test_adapter_group_has_no_keyboard_private_has_confirm_button(callback):
    adapter = object.__new__(TelegramBotAdapter)
    adapter.bot = SimpleNamespace(
        send_message=AsyncMock(return_value=SimpleNamespace(message_id=42))
    )
    await REAL_SCHEDULE_SEND(
        adapter, -771002 if callback is None else 771001, "Safe schedule", callback
    )
    markup = adapter.bot.send_message.call_args.kwargs["reply_markup"]
    if callback is None:
        assert markup is None
    else:
        assert markup.inline_keyboard[0][0].text == "Confirm schedule"
        assert markup.inline_keyboard[0][0].callback_data == callback


@pytest.mark.parametrize("previous", ["RATE_LIMITED", "ACK_UNAVAILABLE"])
async def test_rejected_callback_replay_does_not_bypass_admission(app, client, ready, previous):
    fake = FakeTelegram()
    dispatch, event = await sent_dispatch(app, client, ready, fake)
    async with app.state.session_factory() as db, db.begin():
        db.add(TelegramProcessedUpdate(bot_id=BOT_ID, update_id=event.update_id, outcome=previous))
    result = await process_update(
        app.state.session_factory, fake, event, BOT_ID, settings=app.state.settings
    )
    assert result.outcome == "DUPLICATE"
    assert (await row(app, dispatch.id)).ack_status == "PENDING"
    assert not await jobs(app, "SCHEDULE_CONFIRMED")
    assert len(fake.callbacks) == 1
    if previous == "RATE_LIMITED":
        assert "Too many actions" in fake.callbacks[-1][1]


@pytest.mark.parametrize("kind", ["DAILY_SUMMARY", "SCHEDULE_PROMPT", "SCHEDULE_CONFIRMED"])
@pytest.mark.parametrize("change", ["rebound", "unavailable", "private_rebound", "bot_missing"])
async def test_queued_notices_never_move_to_replaced_or_unavailable_destination(
    app, client, google, ready, monkeypatch, kind, change
):
    fake = FakeTelegram()
    fake.group(-771002, 771001, 771001)
    if kind == "DAILY_SUMMARY":
        await daily_setup(app, ready, google, monkeypatch)
        await process_update(
            app.state.session_factory, fake, command(), BOT_ID, settings=app.state.settings
        )
    elif kind == "SCHEDULE_PROMPT":
        await enqueue(client, ready)
        await run_delivery(app, fake)
    else:
        _, event = await sent_dispatch(app, client, ready, fake)
        await acknowledge(app.state.session_factory, event, BOT_ID)
    if change == "bot_missing":
        from hub.telegram.types import Member

        fake.members[(-771002, BOT_ID)] = Member("left")
    else:
        async with app.state.session_factory() as db, db.begin():
            binding = await db.get(TelegramBinding, ready)
            if change == "rebound":
                binding.telegram_group_chat_id = -990001
                binding.group_generation += 1
            elif change == "private_rebound":
                binding.private_generation += 1
                binding.group_private_generation = binding.private_generation
                binding.telegram_user_id = 990002
            else:
                binding.group_availability = "REVALIDATION_REQUIRED"
    before = list(fake.sent)
    await drain(app, fake)
    assert fake.sent == before
    assert (await jobs(app, kind))[0].state in {"FAILED", "CANCELLED"}


async def test_unknown_group_send_never_queues_private_prompt(app, client, ready):
    fake = FakeTelegram()
    fake.send_error = ProviderError("NETWORK_UNCERTAIN")
    data = await enqueue(client, ready)
    await run_delivery(app, fake)
    assert (await row(app, data["id"])).status == "AMBIGUOUS"
    assert not await jobs(app, "SCHEDULE_PROMPT")


async def test_callback_exception_still_gets_final_safe_feedback(app, client, ready, monkeypatch):
    from hub.schedule_delivery import acknowledgements

    fake = FakeTelegram()
    _, event = await sent_dispatch(app, client, ready, fake)

    async def broken(*args, **kwargs):
        raise RuntimeError("SECRET_DATABASE_DETAIL")

    monkeypatch.setattr(acknowledgements, "acknowledge", broken)
    with pytest.raises(RuntimeError):
        await process_update(
            app.state.session_factory, fake, event, BOT_ID, settings=app.state.settings
        )
    assert len(fake.callbacks) == 1 and "unavailable" in fake.callbacks[0][1]
    assert "SECRET_DATABASE_DETAIL" not in str(fake.callbacks)


async def test_success_callback_has_one_final_answer(app, client, ready):
    fake = FakeTelegram()
    dispatch, event = await sent_dispatch(app, client, ready, fake)
    result = await process_update(
        app.state.session_factory, fake, event, BOT_ID, settings=app.state.settings
    )
    assert result.outcome == "ACKNOWLEDGED"
    assert fake.callbacks == [(event.callback_query_id, "Schedule confirmed. Thank you.")]
    assert (await row(app, dispatch.id)).acknowledged_at


async def test_entire_daily_ack_provider_path_has_no_open_business_transaction(
    app, client, google, ready, monkeypatch
):
    await daily_setup(app, ready, google, monkeypatch)
    fake = FakeTelegram()
    fake.group(-771002, 771001, 771001)
    for method in ["initialize", "member", "send", "send_schedule", "answer_callback"]:
        original = getattr(fake, method)

        async def checked(*args, original=original, **kwargs):
            async with app.state.session_factory() as db:
                assert (
                    await db.scalar(
                        text(
                            "SELECT count(*) FROM pg_stat_activity WHERE "
                            "datname=current_database() AND state='idle in transaction'"
                        )
                    )
                    == 0
                )
            return await original(*args, **kwargs)

        setattr(fake, method, checked)
    await process_update(
        app.state.session_factory, fake, command(), BOT_ID, settings=app.state.settings
    )
    await drain(app, fake)
    await run_delivery(app, fake)
    await drain(app, fake)
    async with app.state.session_factory() as db:
        dispatch = await db.scalar(select(ScheduleDispatch))
    event = TrustedEvent(
        95000,
        "CALLBACK",
        chat_type="private",
        chat_id=771001,
        user_id=771001,
        message_id=dispatch.ack_message_id,
        payload=fake.schedule_sent[-1][2],
        callback_query_id="probe-callback",
    )
    await process_update(
        app.state.session_factory, fake, event, BOT_ID, settings=app.state.settings
    )
    await drain(app, fake)
    assert (await jobs(app, "SCHEDULE_CONFIRMED"))[0].state == "SENT"


async def test_expired_and_historical_group_manager_buttons_get_final_feedback(
    app, client, ready, monkeypatch
):
    from datetime import timedelta
    from uuid import uuid4

    from hub.auth.security import now
    from hub.schedule_delivery import acknowledgements
    from hub.schedule_delivery.domain import token_hash

    fake = FakeTelegram()
    dispatch, event = await sent_dispatch(app, client, ready, fake)
    async with app.state.session_factory() as db, db.begin():
        values = {
            column.name: getattr(dispatch, column.name)
            for column in ScheduleDispatch.__table__.columns
            if column.name not in {"id", "created_at", "updated_at"}
        }
        values.update(
            private_ack_required=False,
            ack_message_id=None,
            target_date=dispatch.target_date + timedelta(days=1),
            ack_token_hash=token_hash("historical-test-token"),
        )
        db.add(ScheduleDispatch(id=uuid4(), **values))
    historical = replace(
        event,
        user_id=990000,
        chat_type="supergroup",
        chat_id=dispatch.chat_id,
        message_id=dispatch.message_id,
        payload="sch:historical-test-token",
    )
    result = await process_update(
        app.state.session_factory, fake, historical, BOT_ID, settings=app.state.settings
    )
    assert result.outcome == "ACK_WRONG_USER" and "Only the assigned" in fake.callbacks[-1][1]

    async def future_clock(db):
        return now() + timedelta(days=8)

    monkeypatch.setattr(acknowledgements, "clock", future_clock)
    result = await process_update(
        app.state.session_factory,
        fake,
        replace(event, update_id=96001),
        BOT_ID,
        settings=app.state.settings,
    )
    assert result.outcome == "ACK_EXPIRED" and "expired" in fake.callbacks[-1][1]


async def test_populated_private_ack_migration_refuses_destructive_rollback(app, client, ready):
    import os
    import subprocess
    import sys
    from pathlib import Path

    from tests.conftest import TEST_URL

    fake = FakeTelegram()
    dispatch, _ = await sent_dispatch(app, client, ready, fake)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "ffc610080001"],
        cwd=Path(__file__).parents[1],
        env={**os.environ, "DATABASE_URL": TEST_URL},
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0 and "PRIVATE_ACK_HISTORY_ROLLBACK_REFUSED" in result.stderr
    saved = await row(app, dispatch.id)
    assert saved.ack_message_id == dispatch.ack_message_id and saved.status == "SENT"
    async with app.state.session_factory() as db:
        assert await db.scalar(text("SELECT version_num FROM alembic_version")) == "ffe610080001"


@pytest.mark.parametrize("summary_error", [None, "NETWORK_UNCERTAIN", "ACCESS_DENIED"])
async def test_daily_group_order_across_workers_and_independent_summary_failure(
    app, client, google, ready, monkeypatch, summary_error
):
    await daily_setup(app, ready, google, monkeypatch)
    fake = FakeTelegram()
    fake.group(-771002, 771001, 771001)
    await process_update(
        app.state.session_factory, fake, command(), BOT_ID, settings=app.state.settings
    )
    assert not await run_delivery(app, fake)  # Summary has not yet been attempted.
    assert not fake.schedule_sent
    fake.send_error = ProviderError(summary_error) if summary_error else None
    await drain(app, fake)
    if summary_error == "ACCESS_DENIED":
        # Simulate safe same-binding recovery before trying the independent schedule.
        async with app.state.session_factory() as db, db.begin():
            binding = await db.get(TelegramBinding, ready)
            binding.group_availability = "AVAILABLE"
    fake.send_error = None
    assert await run_delivery(app, fake)
    assert fake.schedule_sent[0][0] == -771002
    await drain(app, fake)
    assert fake.schedule_sent[-1][0] == 771001
    assert "Gross total:" in fake.sent[0][1]
    if not summary_error:
        assert fake.sent[1][1] == fake.sent[0][1]
        assert "Waiting for technician confirmation" in fake.sent[2][1]
