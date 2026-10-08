"""Daily/manager workflow integration with PostgreSQL and synthetic providers only."""

import asyncio
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from hub.accounting.service import calculate
from hub.calendar_events import service as events
from hub.core.config import Settings
from hub.integrations.models import TelegramBinding
from hub.schedule_delivery import scheduler
from hub.schedule_delivery.acknowledgements import acknowledge
from hub.schedule_delivery.models import ScheduleDispatch
from hub.technicians.models import Technician
from hub.telegram import daily
from hub.telegram.models import TelegramProcessedUpdate
from hub.telegram.transport import parse_update
from hub.telegram.types import TrustedEvent
from hub.telegram.updates import process_update
from tests.fakes import BOT_ID, BOT_USERNAME, FakeTelegram
from tests.test_calendar_events import item
from tests.test_schedule_delivery import (
    assigned as assigned,
)
from tests.test_schedule_delivery import (
    deliver_private_prompt,
    enqueue,
    preview,
    request,
    row,
    run_delivery,
)
from tests.test_schedule_delivery import (
    google as google,
)
from tests.test_schedule_delivery import (
    ready as ready,
)


@pytest.mark.parametrize("weekday,delta", [(0, 1), (1, 1), (2, 1), (3, 1), (4, 1), (5, 2), (6, 1)])
async def test_resolver_weekdays_and_empty_sunday(
    client, google, ready, monkeypatch, weekday, delta
):
    day = date(2026, 9, 14) + timedelta(days=weekday)
    monkeypatch.setattr(
        events, "now", lambda: datetime.combine(day, datetime.min.time(), UTC) + timedelta(hours=12)
    )
    google.events = []
    data = (await client.get(f"/api/technicians/{ready}/calendar/next-schedule")).json()
    assert data["state"] == "READY"
    assert data["operational_date"] == str(day + timedelta(days=delta))
    assert bool(data["resolution_note"]) == (weekday == 5)
    sent = await enqueue(client, ready)
    assert sent["target_date"] == data["operational_date"]
    assert sent["trigger_source"] == "MANAGER_MANUAL"
    assert sent["destination"] == "WORK_GROUP"


@pytest.mark.parametrize(
    "kind,expected", [("real", 20), ("fake", 21), ("cancelled", 21), ("early", 21), ("all_day", 21)]
)
async def test_sunday_uses_canonical_filter(client, google, ready, monkeypatch, kind, expected):
    monkeypatch.setattr(events, "now", lambda: datetime(2026, 9, 19, 16, tzinfo=UTC))
    event = item(day=date(2026, 9, 20))
    if kind == "fake":
        event["summary"] = "1. fake appointment"
    if kind == "cancelled":
        event["status"] = "cancelled"
    if kind == "early":
        event = item(day=date(2026, 9, 20), hour="07:00")
    if kind == "all_day":
        event.update(start={"date": "2026-09-20"}, end={"date": "2026-09-21"})
    google.events = [event]
    result = await preview(client, ready)
    assert result["target_date"] == f"2026-09-{expected}"


def command(update_id=99001):
    return parse_update(
        {
            "update_id": update_id,
            "message": {
                "message_id": 1,
                "chat": {"id": 771001, "type": "private"},
                "from": {"id": 771001, "is_bot": False, "first_name": "Test"},
                "text": "/daily@" + BOT_USERNAME,
            },
        },
        BOT_USERNAME,
    )


async def daily_setup(app, ready, google, monkeypatch):
    async with app.state.session_factory() as db, db.begin():
        tech = await db.get(Technician, ready)
        tech.accounting_timezone = "America/New_York"
    monkeypatch.setattr(daily, "google_provider", lambda settings: google)


async def test_daily_accounting_and_group_dispatch_replay(app, client, google, ready, monkeypatch):
    await daily_setup(app, ready, google, monkeypatch)
    fake = FakeTelegram()
    result = await process_update(
        app.state.session_factory, fake, command(), BOT_ID, settings=app.state.settings
    )
    assert result.outcome == "DAILY_READY"
    async with app.state.session_factory() as db:
        projection = await calculate(db, ready, "daily")
    assert fake.sent[0] == (771001, daily.render_daily(projection))
    assert "queued for your Work Group" in result.reply
    async with app.state.session_factory() as db:
        dispatch = await db.scalar(select(ScheduleDispatch))
        assert dispatch.trigger_source == "TECHNICIAN_DAILY"
        assert dispatch.destination == "WORK_GROUP" and dispatch.chat_id == -771002
    repeated = await process_update(
        app.state.session_factory, fake, command(), BOT_ID, settings=app.state.settings
    )
    assert repeated.outcome == "DUPLICATE"
    fake.group(-771002, 771001, 771001)
    await deliver_private_prompt(app, fake)  # Drain the preceding Daily summary.
    await run_delivery(app, fake)
    assert len(fake.schedule_sent) == 1


@pytest.mark.parametrize("group_state", ["UNAVAILABLE", "REVALIDATION_REQUIRED"])
async def test_daily_accounting_survives_unavailable_group(
    app, google, ready, monkeypatch, group_state
):
    await daily_setup(app, ready, google, monkeypatch)
    async with app.state.session_factory() as db, db.begin():
        binding = await db.get(TelegramBinding, ready)
        binding.group_availability = group_state
    fake = FakeTelegram()
    result = await process_update(
        app.state.session_factory, fake, command(), BOT_ID, settings=app.state.settings
    )
    assert result.outcome == "DAILY_READY"
    assert "Gross total:" in fake.sent[0][1] and "next schedule could not be sent" in result.reply
    async with app.state.session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(ScheduleDispatch)) == 0


async def test_daily_accounting_survives_google_failure(app, google, ready, monkeypatch):
    await daily_setup(app, ready, google, monkeypatch)

    async def broken(*args):
        raise RuntimeError("SECRET_PROVIDER_DETAIL")

    monkeypatch.setattr(google, "list_events", broken)
    fake = FakeTelegram()
    result = await process_update(
        app.state.session_factory, fake, command(), BOT_ID, settings=app.state.settings
    )
    assert result.outcome == "DAILY_READY" and "Gross total:" in fake.sent[0][1]
    assert "next schedule could not be sent" in result.reply
    assert "SECRET_PROVIDER_DETAIL" not in result.reply


async def test_daily_is_private_and_bound(app, google, ready, monkeypatch):
    await daily_setup(app, ready, google, monkeypatch)
    for event in [
        replace(command(99002), chat_type="group", chat_id=-771002),
        replace(command(99003), user_id=990000, chat_id=990000),
    ]:
        result = await process_update(
            app.state.session_factory, FakeTelegram(), event, BOT_ID, settings=app.state.settings
        )
        assert result.outcome in {"IGNORED", "UNAVAILABLE"}
        assert not result.reply or "Gross total" not in result.reply
    async with app.state.session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(ScheduleDispatch)) == 0


async def test_new_official_dispatch_no_private_fallback(app, client, ready):
    saved = await enqueue(client, ready)
    async with app.state.session_factory() as db, db.begin():
        binding = await db.get(TelegramBinding, ready)
        binding.group_availability = "REVALIDATION_REQUIRED"
    fake = FakeTelegram()
    await run_delivery(app, fake)
    assert not fake.schedule_sent
    assert (await row(app, saved["id"])).status == "CANCELLED"


async def test_exact_ack_and_replacement(app, client, google, ready):
    first = await enqueue(client, ready)
    fake = FakeTelegram()
    await run_delivery(app, fake)
    await deliver_private_prompt(app, fake)
    stored = await row(app, first["id"])
    event = TrustedEvent(
        88001,
        "CALLBACK",
        chat_id=771001,
        chat_type="private",
        user_id=771001,
        message_id=stored.ack_message_id,
        payload=fake.schedule_sent[-1][2],
    )
    assert (
        await acknowledge(app.state.session_factory, replace(event, user_id=666), BOT_ID)
        == "ACK_UNAVAILABLE"
    )
    assert await acknowledge(app.state.session_factory, event, BOT_ID) == "ACKNOWLEDGED"
    assert await acknowledge(app.state.session_factory, event, BOT_ID) == "ACKNOWLEDGED"
    google.events = []
    second = await enqueue(client, ready)
    assert (await row(app, first["id"])).superseded_at is not None
    assert await acknowledge(app.state.session_factory, event, BOT_ID) == "ACK_UNAVAILABLE"
    assert second["id"] != first["id"]


async def test_pilot_clock_never_creates_schedule(app, client, ready):
    assert Settings(_env_file=None).schedule_timed_auto_enabled is False
    app.state.settings.schedule_timed_auto_enabled = True
    app.state.settings.app_env = "pilot"
    result = await client.put(f"/api/technicians/{ready}/schedule-delivery", json={"enabled": True})
    assert result.status_code == 409
    await scheduler.evaluate(request(app))
    async with app.state.session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(ScheduleDispatch)) == 0


async def test_crash_replay_reuses_dispatch_even_when_calendar_changes(
    app, google, ready, monkeypatch
):
    await daily_setup(app, ready, google, monkeypatch)
    fake = FakeTelegram()
    await process_update(
        app.state.session_factory, fake, command(), BOT_ID, settings=app.state.settings
    )
    fake.group(-771002, 771001, 771001)
    await deliver_private_prompt(app, fake)  # Drain the preceding Daily summary.
    await run_delivery(app, fake)
    async with app.state.session_factory() as db, db.begin():
        reservation = await db.get(TelegramProcessedUpdate, (BOT_ID, command().update_id))
        reservation.outcome = (
            "DAILY_ACCOUNTING_ATTEMPTED"  # Crash after enqueue, before completion.
        )
    google.events = []
    result = await process_update(
        app.state.session_factory, fake, command(), BOT_ID, settings=app.state.settings
    )
    assert "was sent to your Work Group" in result.reply
    assert len([message for _, message in fake.sent if message.startswith("Daily report\n")]) == 1
    async with app.state.session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(ScheduleDispatch)) == 1


async def test_trigger_source_is_immutable(app, client, ready):
    saved = await enqueue(client, ready)
    async with app.state.session_factory() as db:
        dispatch = await db.get(ScheduleDispatch, UUID(saved["id"]))
        dispatch.trigger_source = None
        with pytest.raises(IntegrityError):
            await db.commit()


async def test_accounting_receipt_precedes_provider_and_survives_crash(
    app, google, ready, monkeypatch
):
    await daily_setup(app, ready, google, monkeypatch)
    fake = FakeTelegram()
    original = google.list_events

    async def verify_order(*args):
        assert fake.sent and "Gross total:" in fake.sent[0][1]
        return await original(*args)

    monkeypatch.setattr(google, "list_events", verify_order)
    result = await process_update(
        app.state.session_factory, fake, command(), BOT_ID, settings=app.state.settings
    )
    assert result.outcome == "DAILY_READY" and "queued" in result.reply


async def test_crash_after_accounting_receipt_resumes_without_resending(
    app, google, ready, monkeypatch
):
    await daily_setup(app, ready, google, monkeypatch)
    fake = FakeTelegram()
    original = daily.create_dispatch

    async def crash(*args, **kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(daily, "create_dispatch", crash)
    with pytest.raises(asyncio.CancelledError):
        await process_update(
            app.state.session_factory, fake, command(), BOT_ID, settings=app.state.settings
        )
    assert len(fake.sent) == 1 and "Gross total:" in fake.sent[0][1]
    monkeypatch.setattr(daily, "create_dispatch", original)
    result = await process_update(
        app.state.session_factory, fake, command(), BOT_ID, settings=app.state.settings
    )
    assert "queued" in result.reply and len(fake.sent) == 1


async def test_pilot_timed_switch_does_not_stop_durable_processing(app, client, ready):
    saved = await enqueue(client, ready)
    app.state.settings.schedule_timed_auto_enabled = False
    app.state.settings.app_env = "pilot"
    fake = FakeTelegram()
    await run_delivery(app, fake)
    assert (await row(app, saved["id"])).status == "SENT"
    assert len(fake.schedule_sent) == 1
