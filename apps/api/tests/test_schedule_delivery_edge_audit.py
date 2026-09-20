"""Additional provider, migration, encryption, and scheduler boundary attacks."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from hub.schedule_delivery import delivery, scheduler, service
from hub.schedule_delivery.domain import cipher
from hub.schedule_delivery.models import ScheduleDispatch
from hub.telegram.types import ProviderError, TrustedEvent
from tests.fakes import BOT_ID, FakeTelegram
from tests.test_schedule_delivery import assigned as assigned
from tests.test_schedule_delivery import enqueue, request, row, run_delivery
from tests.test_schedule_delivery import google as google
from tests.test_schedule_delivery import ready as ready


@pytest.mark.parametrize("variant", ["corrupt", "version", "shape"])
async def test_invalid_encrypted_rows_fail_closed(app, client, ready, variant):
    data = await enqueue(client, ready)
    saved = await row(app, data["id"])
    values = {
        c.name: getattr(saved, c.name)
        for c in ScheduleDispatch.__table__.columns
        if c.name not in {"id", "created_at", "updated_at"}
    }
    values["encrypted_payload"] = {
        "corrupt": "v1:corrupt",
        "version": "v2:unsupported",
        "shape": cipher(app.state.settings).encrypt('{"bad":true}'),
    }[variant]
    async with app.state.session_factory() as db, db.begin():
        current = await db.get(ScheduleDispatch, UUID(data["id"]))
        await db.delete(current)
    if variant == "version":
        with pytest.raises(IntegrityError):
            async with app.state.session_factory() as db, db.begin():
                db.add(ScheduleDispatch(**values))
        return
    async with app.state.session_factory() as db, db.begin():
        bad = ScheduleDispatch(**values)
        db.add(bad)
        await db.flush()
        identifier = bad.id
    fake = FakeTelegram()
    await run_delivery(app, fake)
    current = await row(app, identifier)
    assert current.status == "FAILED" and current.error_code == "SNAPSHOT_UNREADABLE"
    assert current.encrypted_payload is None and not fake.schedule_sent


@pytest.mark.parametrize("kind", ["http_error", "timeout", "unknown"])
async def test_simulated_acceptance_then_transport_error_is_uncertain(app, client, ready, kind):
    from requests import HTTPError

    data = await enqueue(client, ready)
    fake = FakeTelegram()
    original = fake.send_schedule

    async def send(*args):
        await original(*args)
        raise {"http_error": HTTPError, "timeout": TimeoutError, "unknown": RuntimeError}[kind](
            "synthetic post-acceptance error"
        )

    fake.send_schedule = send
    await run_delivery(app, fake)
    await run_delivery(app, fake)
    assert len(fake.schedule_sent) == 1 and (await row(app, data["id"])).status == "AMBIGUOUS"


@pytest.mark.parametrize("already_sent", [False, True])
async def test_trusted_group_migration_invalidates_old_send_and_ack(
    app, client, ready, already_sent
):
    from hub.schedule_delivery.acknowledgements import acknowledge
    from hub.telegram.updates import process_update

    data = await enqueue(client, ready)
    fake = FakeTelegram()
    if already_sent:
        await run_delivery(app, fake)
    event = TrustedEvent(
        300, "MIGRATION", chat_id=-771002, chat_type="group", migrated_chat_id=-880002
    )
    assert (
        await process_update(app.state.session_factory, fake, event, BOT_ID)
    ).outcome == "MIGRATED"
    if already_sent:
        saved = await row(app, data["id"])
        ack = TrustedEvent(
            301,
            "CALLBACK",
            chat_id=-771002,
            user_id=771001,
            message_id=saved.message_id,
            payload=fake.schedule_sent[0][2],
        )
        assert await acknowledge(app.state.session_factory, ack, BOT_ID) == "ACK_UNAVAILABLE"
    else:
        await run_delivery(app, fake)
        assert [chat for chat, _, _ in fake.schedule_sent] == [771001]


async def test_old_group_transferred_to_another_technician(app, client, ready):
    from hub.integrations.models import TelegramBinding
    from hub.technicians.models import Technician

    await enqueue(client, ready)
    async with app.state.session_factory() as db, db.begin():
        original = await db.get(TelegramBinding, ready)
        original.telegram_group_chat_id = None
        original.group_status = "NOT_CONNECTED"
        original.group_availability = "UNKNOWN"
        original.group_generation += 1
        original.group_private_generation = None
        await db.flush()
        other = Technician(id=uuid4(), first_name="Other", last_name="Technician")
        db.add(other)
        await db.flush()
        db.add(
            TelegramBinding(
                technician_id=other.id,
                bot_id=BOT_ID,
                telegram_user_id=990001,
                telegram_group_chat_id=-771002,
                private_status="CONNECTED",
                group_status="CONNECTED",
                private_availability="AVAILABLE",
                group_availability="AVAILABLE",
                private_generation=1,
                group_generation=1,
                group_private_generation=1,
            )
        )
    fake = FakeTelegram()
    await run_delivery(app, fake)
    assert [chat for chat, _, _ in fake.schedule_sent] == [771001]


async def test_auto_disable_during_authoritative_fetch(app, client, google, ready, monkeypatch):
    await client.put(f"/api/technicians/{ready}/schedule-delivery", json={"enabled": True})
    stamp = datetime(2026, 9, 18, 0, 7, tzinfo=UTC)
    monkeypatch.setattr(scheduler, "now", lambda: stamp)
    monkeypatch.setattr(service, "now", lambda: stamp)
    entered, release = asyncio.Event(), asyncio.Event()
    original = google.list_events

    async def slow(*args):
        entered.set()
        await release.wait()
        return await original(*args)

    google.list_events = slow
    task = asyncio.create_task(scheduler.evaluate(request(app)))
    await asyncio.wait_for(entered.wait(), 5)
    try:
        assert (
            await client.put(f"/api/technicians/{ready}/schedule-delivery", json={"enabled": False})
        ).status_code == 200
    finally:
        release.set()
        await task
    async with app.state.session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(ScheduleDispatch)) == 0


@pytest.mark.parametrize(
    "stamp,due",
    [
        (datetime(2026, 9, 18, 1, tzinfo=UTC), True),
        (datetime(2026, 9, 18, 4, 30, tzinfo=UTC), False),
    ],
)
async def test_scheduler_restart_inside_and_after_window(
    app, client, ready, monkeypatch, stamp, due
):
    await client.put(f"/api/technicians/{ready}/schedule-delivery", json={"enabled": True})
    monkeypatch.setattr(scheduler, "now", lambda: stamp)
    monkeypatch.setattr(service, "now", lambda: stamp)
    await asyncio.gather(*[scheduler.evaluate(request(app)) for _ in range(5)])
    await scheduler.evaluate(request(app))
    async with app.state.session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(ScheduleDispatch)) == int(due)


async def test_definitive_manual_failure_allows_first_automatic_attempt(
    app, client, ready, monkeypatch
):
    await enqueue(client, ready)
    fake = FakeTelegram()
    fake.send_error = ProviderError("REQUEST_REJECTED")
    await run_delivery(app, fake)
    await client.put(f"/api/technicians/{ready}/schedule-delivery", json={"enabled": True})
    stamp = datetime(2026, 9, 18, 0, 7, tzinfo=UTC)
    monkeypatch.setattr(scheduler, "now", lambda: stamp)
    monkeypatch.setattr(service, "now", lambda: stamp)
    await scheduler.evaluate(request(app))
    async with app.state.session_factory() as db:
        rows = (await db.scalars(select(ScheduleDispatch))).all()
        assert len(rows) == 2 and {r.trigger for r in rows} == {"MANUAL", "AUTOMATIC"}


@pytest.mark.parametrize("marked", [False, True])
async def test_retired_bot_expired_work_recovers_without_sending(app, client, ready, marked):
    data = await enqueue(client, ready)
    if marked:
        identifier, _, owner = await delivery.claim(app.state.session_factory, BOT_ID)
        assert await delivery.prepare(
            app.state.session_factory, identifier, owner, app.state.settings
        )
    async with app.state.session_factory() as db, db.begin():
        current = await db.get(ScheduleDispatch, UUID(data["id"]))
        stamp = await delivery.clock(db)
        current.delivery_deadline = stamp - timedelta(seconds=1)
        if marked:
            current.claim_expires_at = stamp - timedelta(seconds=1)
    assert await delivery.claim(app.state.session_factory, BOT_ID + 1) is None
    current = await row(app, data["id"])
    assert current.status == ("AMBIGUOUS" if marked else "CANCELLED")
    if not marked:
        assert current.encrypted_payload is None
    assert await delivery.claim(app.state.session_factory, BOT_ID) is None
