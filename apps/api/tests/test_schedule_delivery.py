"""Stage 4: real PostgreSQL state/locking with strictly injected providers."""

import asyncio
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import func, select, update

from hub.audit.models import AuditEvent
from hub.auth.security import now
from hub.integrations.models import TelegramBinding
from hub.schedule_delivery import delivery, scheduler, service
from hub.schedule_delivery.acknowledgements import acknowledge
from hub.schedule_delivery.domain import Payload, PayloadJob, cipher
from hub.schedule_delivery.models import (
    ScheduleAutoDecision,
    ScheduleDeliverySetting,
    ScheduleDispatch,
)
from hub.schedule_delivery.worker import Worker
from hub.telegram.transport import parse_update
from hub.telegram.types import ProviderError, TrustedEvent
from tests.fakes import BOT_ID, BOT_USERNAME, FakeTelegram
from tests.test_calendar_events import assigned as assigned
from tests.test_calendar_events import item
from tests.test_google_calendar import google as google


@pytest.fixture
async def ready(app, client, google, assigned):
    settings = app.state.settings
    settings.schedule_delivery_enabled = True
    settings.schedule_payload_encryption_key = SecretStr(Fernet.generate_key().decode())
    settings.telegram_mode, settings.telegram_expected_bot_id = "fake", BOT_ID
    settings.telegram_expected_bot_username = BOT_USERNAME
    tid = UUID(assigned[0]["id"])
    async with app.state.session_factory() as db, db.begin():
        binding = TelegramBinding(technician_id=tid)
        db.add(binding)
        binding.bot_id, binding.telegram_user_id = BOT_ID, 771001
        binding.private_status = binding.group_status = "CONNECTED"
        binding.private_availability = binding.group_availability = "AVAILABLE"
        binding.private_generation = binding.group_generation = binding.group_private_generation = 1
        binding.telegram_group_chat_id = -771002
    google.events = [
        item(
            day=date(2026, 9, 18),
            title="1. Repair <b>important</b> (secret note)",
            location="ADDRESS_CANARY",
            description="DESCRIPTION_CANARY",
        )
    ]
    return tid


async def preview(client, tid):
    response = await client.get(f"/api/technicians/{tid}/calendar/next-schedule")
    assert response.status_code == 200, response.text
    result = response.json()
    return {"target_date": result["operational_date"], "fingerprint": result["fingerprint"]}


async def enqueue(client, tid, body=None):
    response = await client.post(
        f"/api/technicians/{tid}/schedule-dispatches", json=body or await preview(client, tid)
    )
    assert response.status_code == 202, response.text
    return response.json()


async def row(app, identifier):
    async with app.state.session_factory() as db:
        return await db.get(ScheduleDispatch, UUID(str(identifier)))


async def run_delivery(app, fake):
    fake.group(-771002, 771001, 771001)
    return await delivery.deliver_one(
        app.state.session_factory, app.state.google_lock_engine, fake, app.state.settings
    )


def request(app):
    return SimpleNamespace(app=app, state=SimpleNamespace(manager_id=None))


async def test_manual_snapshot_render_ack_history(app, client, google, ready, caplog):
    data = await enqueue(client, ready)
    saved = await row(app, data["id"])
    assert saved.encrypted_payload.startswith("v1:")
    assert "ADDRESS_CANARY" not in saved.encrypted_payload
    payload = cipher(app.state.settings).decrypt(saved.encrypted_payload)
    assert "ADDRESS_CANARY" in payload and "DESCRIPTION_CANARY" not in payload
    assert "secret note" not in payload
    fake = FakeTelegram()
    google.events = []  # Delivery must use the immutable snapshot, never re-read.
    await run_delivery(app, fake)
    assert len(fake.schedule_sent) == 1
    chat, message, token = fake.schedule_sent[0]
    assert chat == -771002 and "&lt;b&gt;" in message and "<b>important</b>" not in message
    assert "08:00" in message and "Friday, September 18, 2026" in message
    assert len(token.encode()) <= 64
    saved = await row(app, data["id"])
    assert saved.status == "SENT" and saved.encrypted_payload is None
    assert saved.attempt_count == 1 and saved.ack_status == "PENDING"
    event = TrustedEvent(
        55, "CALLBACK", chat_id=chat, user_id=771001, message_id=saved.message_id, payload=token
    )
    assert (
        await acknowledge(app.state.session_factory, replace(event, user_id=999), BOT_ID)
        == "ACK_UNAVAILABLE"
    )
    results = await asyncio.gather(
        *[acknowledge(app.state.session_factory, event, BOT_ID) for _ in range(4)]
    )
    assert results == ["ACKNOWLEDGED"] * 4
    async with app.state.session_factory() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "schedule.acknowledged")
            )
            == 1
        )
    history = await client.get(f"/api/technicians/{ready}/schedule-delivery")
    assert history.headers["cache-control"] == "no-store"
    assert history.json()["history"][0]["ack_status"] == "ACKNOWLEDGED"
    for secret in [
        token,
        saved.ack_token_hash,
        "ADDRESS_CANARY",
        "DESCRIPTION_CANARY",
        "771001",
        "771002",
        "encrypted_payload",
        "ack_token_hash",
    ]:
        assert secret not in history.text and secret not in caplog.text


async def test_stale_preview_and_extra_jobs_rejected(app, client, google, ready):
    body = await preview(client, ready)
    google.events = []
    response = await client.post(f"/api/technicians/{ready}/schedule-dispatches", json=body)
    assert response.status_code == 409 and "SCHEDULE_CHANGED" in response.text
    body = await preview(client, ready)
    body["jobs"] = [{"title": "attacker"}]
    assert (
        await client.post(f"/api/technicians/{ready}/schedule-dispatches", json=body)
    ).status_code == 422
    async with app.state.session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(ScheduleDispatch)) == 0


async def test_duplicate_resend_changed_content(app, client, google, ready):
    body = await preview(client, ready)
    first = await enqueue(client, ready, body)
    assert (await enqueue(client, ready, body))["id"] == first["id"]
    fake = FakeTelegram()
    await run_delivery(app, fake)
    response = await client.post(f"/api/technicians/{ready}/schedule-dispatches", json=body)
    assert response.status_code == 409 and "ALREADY_SENT" in response.text
    resend = {**body, "resend_of_id": first["id"]}
    assert (
        await client.post(f"/api/technicians/{ready}/schedule-dispatches", json=resend)
    ).status_code == 409
    resend["confirm_duplicate_risk"] = True
    second = await enqueue(client, ready, resend)
    assert second["id"] != first["id"] and second["trigger"] == "MANUAL_RESEND"
    assert (await enqueue(client, ready, resend))["id"] == second["id"]
    await run_delivery(app, fake)
    google.events = []
    changed = await enqueue(client, ready)
    assert changed["fingerprint"] != body["fingerprint"]
    await run_delivery(app, fake)
    assert "No scheduled jobs." in fake.schedule_sent[-1][1]


@pytest.mark.parametrize(
    "code,status,fallback",
    [
        ("NETWORK_UNCERTAIN", "AMBIGUOUS", False),
        ("PROVIDER_UNAVAILABLE", "AMBIGUOUS", False),
        ("PROCESSING_FAILED", "AMBIGUOUS", False),
        ("REQUEST_REJECTED", "FAILED", False),
        ("ACCESS_DENIED", "SENT", True),
        ("CHAT_UNAVAILABLE", "SENT", True),
        ("RATE_LIMITED", "PENDING", False),
    ],
)
async def test_provider_outcomes(app, client, ready, code, status, fallback):
    data = await enqueue(client, ready)
    fake = FakeTelegram()
    calls = []
    original = fake.send_schedule

    async def send(chat, message, token):
        calls.append(chat)
        if len(calls) == 1:
            raise ProviderError(code, retry_after=10)
        return await original(chat, message, token)

    fake.send_schedule = send
    await run_delivery(app, fake)
    saved = await row(app, data["id"])
    assert saved.status == status
    assert len(calls) == (2 if fallback else 1)
    if fallback:
        assert calls == [-771002, 771001] and saved.destination == "PRIVATE"
    if status == "AMBIGUOUS":
        await run_delivery(app, fake)
        assert len(calls) == 1
        response = await client.post(
            f"/api/technicians/{ready}/schedule-dispatches", json=await preview(client, ready)
        )
        assert response.status_code == 409 and "AMBIGUOUS" in response.text
        assert (
            await enqueue(
                client,
                ready,
                {
                    **await preview(client, ready),
                    "resend_of_id": data["id"],
                    "confirm_duplicate_risk": True,
                },
            )
        )["id"] != data["id"]


async def test_competing_workers(app, client, ready):
    data = await enqueue(client, ready)
    fake = FakeTelegram()
    await asyncio.gather(*[run_delivery(app, fake) for _ in range(8)])
    assert len(fake.schedule_sent) == 1
    assert (await row(app, data["id"])).attempt_count == 1


@pytest.mark.parametrize("started", [False, True])
async def test_expired_claim_recovery_and_stale_owner(app, client, ready, started):
    data = await enqueue(client, ready)
    ticket = await delivery.claim(app.state.session_factory, BOT_ID)
    if started:
        await delivery.prepare(app.state.session_factory, ticket[0], ticket[2], app.state.settings)
    async with app.state.session_factory() as db, db.begin():
        await db.execute(
            update(ScheduleDispatch).values(claim_expires_at=now() - timedelta(minutes=1))
        )
    fake = FakeTelegram()
    await run_delivery(app, fake)
    await delivery.finish(app.state.session_factory, ticket[0], ticket[2], message_id=777)
    saved = await row(app, data["id"])
    assert saved.status == ("AMBIGUOUS" if started else "SENT")
    assert len(fake.schedule_sent) == (0 if started else 1)
    assert saved.message_id != 777


@pytest.mark.parametrize(
    "change",
    ["private_generation", "telegram_user_id", "bot_id", "private_status", "private_availability"],
)
async def test_binding_change_cancels_without_send(app, client, ready, change):
    data = await enqueue(client, ready)
    async with app.state.session_factory() as db, db.begin():
        binding = await db.get(TelegramBinding, ready)
        setattr(
            binding,
            change,
            "NOT_CONNECTED"
            if change == "private_status"
            else "BLOCKED"
            if change == "private_availability"
            else 555,
        )
    fake = FakeTelegram()
    await run_delivery(app, fake)
    saved = await row(app, data["id"])
    assert saved.status == "CANCELLED" and saved.attempt_count == 0 and not fake.sent


@pytest.mark.parametrize("change", ["private_generation", "telegram_user_id", "private_status"])
async def test_rebound_identity_cannot_ack(app, client, ready, change):
    data = await enqueue(client, ready)
    fake = FakeTelegram()
    await run_delivery(app, fake)
    saved = await row(app, data["id"])
    async with app.state.session_factory() as db, db.begin():
        binding = await db.get(TelegramBinding, ready)
        setattr(binding, change, "NOT_CONNECTED" if change == "private_status" else 444)
    event = TrustedEvent(
        1,
        "CALLBACK",
        chat_id=saved.chat_id,
        user_id=771001,
        message_id=saved.message_id,
        payload=fake.schedule_sent[0][2],
    )
    assert await acknowledge(app.state.session_factory, event, BOT_ID) == "ACK_UNAVAILABLE"


async def test_auto_default_off_and_manual_suppression(app, client, google, ready, monkeypatch):
    assert not (await client.get(f"/api/technicians/{ready}/schedule-delivery")).json()["enabled"]
    await enqueue(client, ready)
    await run_delivery(app, FakeTelegram())
    await client.put(f"/api/technicians/{ready}/schedule-delivery", json={"enabled": True})
    stamp = datetime(2026, 9, 18, 0, 30, tzinfo=UTC)
    monkeypatch.setattr(scheduler, "now", lambda: stamp)
    monkeypatch.setattr(service, "now", lambda: stamp)
    google.events = []
    await asyncio.gather(scheduler.evaluate(request(app)), scheduler.evaluate(request(app)))
    async with app.state.session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(ScheduleDispatch)) == 1
        assert (
            await db.get(ScheduleAutoDecision, (ready, date(2026, 9, 18)))
        ).state == "SUPPRESSED"


@pytest.mark.parametrize(
    "hour,zone,due",
    [
        (0, "America/New_York", True),
        (0, "America/Los_Angeles", False),
        (3, "America/New_York", False),
        (3, "America/Los_Angeles", True),
        (6, "America/Los_Angeles", False),
        (19, "America/New_York", False),
    ],
)
def test_scheduler_timezone(hour, zone, due):
    assert (
        scheduler.in_window(
            datetime(2026, 9, 18, hour, 30, tzinfo=UTC),
            zone,
            SimpleNamespace(schedule_auto_delivery_local_time="20:00"),
        )
        is due
    )


@pytest.mark.parametrize("changed", ["technician_name", "target_date", "jobs"])
def test_fingerprint_tracks_only_rendered_content(changed):
    payload = Payload(
        target_date=date(2026, 9, 18),
        technician_name="Tech",
        jobs=(PayloadJob(time="08:00", title="Repair", location=None),),
    )
    other = payload.model_copy(
        update={
            changed: {"technician_name": "Other", "target_date": date(2026, 9, 19), "jobs": ()}[
                changed
            ]
        }
    )
    assert payload.fingerprint != other.fingerprint
    assert Payload.model_validate_json(payload.canonical()).fingerprint == payload.fingerprint


async def test_oversized_and_bad_cipher(app, client, google, ready):
    google.events = [
        item(str(i), day=date(2026, 9, 18), title=f"{i}. " + "A" * 500) for i in range(15)
    ]
    response = await client.post(
        f"/api/technicians/{ready}/schedule-dispatches", json=await preview(client, ready)
    )
    assert response.status_code == 409 and "SCHEDULE_TOO_LARGE" in response.text
    google.events = []
    data = await enqueue(client, ready)
    app.state.settings.schedule_payload_encryption_key = SecretStr(Fernet.generate_key().decode())
    fake = FakeTelegram()
    await run_delivery(app, fake)
    assert (await row(app, data["id"])).error_code == "SNAPSHOT_UNREADABLE" and not fake.sent


async def test_worker_startup_shutdown(app, google, ready):
    fake = FakeTelegram()
    worker = Worker(
        app.state.settings, app.state.engine, app.state.google_lock_engine, fake, google
    )
    await worker.run(asyncio.Event(), max_cycles=1)
    assert fake.initialized and fake.closed and not fake.offsets


@pytest.mark.parametrize("data", ["sch:" + "x" * 43, "sch:" + "x" * 44, "bad", None])
def test_callback_parser(data):
    event = parse_update(
        {
            "update_id": 12,
            "callback_query": {
                "id": "query",
                "data": data,
                "from": {"id": 3, "is_bot": False},
                "message": {"message_id": 4, "chat": {"id": -5, "type": "group"}},
            },
        },
        BOT_USERNAME,
    )
    assert event.kind == "CALLBACK"
    assert event.payload == (data if data and len(data) == 47 else None)
    assert not data or data not in repr(event)


async def test_wrong_claim_owner_cannot_finalize_active_claim(app, client, ready):
    data = await enqueue(client, ready)
    ticket = await delivery.claim(app.state.session_factory, BOT_ID)
    await delivery.prepare(app.state.session_factory, ticket[0], ticket[2], app.state.settings)
    await delivery.finish(app.state.session_factory, ticket[0], uuid4(), message_id=777)
    assert (await row(app, data["id"])).status == "PROCESSING"


@pytest.mark.parametrize(
    "change", ["assignment", "inactive", "scope", "disconnect", "auto_disabled"]
)
async def test_source_or_eligibility_change_cancels_queued(app, client, ready, change):
    from hub.calendars.models import CalendarAssignment
    from hub.google_calendar.models import CalendarConnection
    from hub.technicians.models import Technician

    if change == "auto_disabled":
        await client.put(f"/api/technicians/{ready}/schedule-delivery", json={"enabled": True})
    data = await enqueue(client, ready)
    async with app.state.session_factory() as db, db.begin():
        if change == "assignment":
            await db.execute(update(CalendarAssignment).values(is_active=False))
        elif change == "inactive":
            await db.execute(
                update(Technician).where(Technician.id == ready).values(status="INACTIVE")
            )
        elif change == "scope":
            from hub.google_calendar.types import SCOPE

            await db.execute(update(CalendarConnection).values(granted_scopes=[SCOPE]))
        elif change == "disconnect":
            await db.execute(update(CalendarConnection).values(status="REAUTH_REQUIRED"))
        else:
            # Toggle behaviour is independently tested via automatic creation below.
            await db.execute(update(ScheduleDeliverySetting).values(enabled=False))
    fake = FakeTelegram()
    await run_delivery(app, fake)
    saved = await row(app, data["id"])
    if change == "auto_disabled":
        assert saved.status == "SENT"  # Turning auto off must not cancel explicit manual sends.
    else:
        assert saved.status == "CANCELLED" and saved.attempt_count == 0 and not fake.sent


async def test_concurrent_manual_enqueue_creates_one_dispatch(app, client, ready):
    body = await preview(client, ready)
    results = await asyncio.gather(
        *[client.post(f"/api/technicians/{ready}/schedule-dispatches", json=body) for _ in range(6)]
    )
    assert all(r.status_code in {202, 409} for r in results)
    async with app.state.session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(ScheduleDispatch)) == 1


async def test_auto_queues_once_and_toggle_cancels(app, client, ready, monkeypatch):
    await client.put(f"/api/technicians/{ready}/schedule-delivery", json={"enabled": True})
    stamp = datetime(2026, 9, 18, 0, 30, tzinfo=UTC)
    monkeypatch.setattr(scheduler, "now", lambda: stamp)
    monkeypatch.setattr(service, "now", lambda: stamp)
    await asyncio.gather(scheduler.evaluate(request(app)), scheduler.evaluate(request(app)))
    async with app.state.session_factory() as db:
        rows = (await db.scalars(select(ScheduleDispatch))).all()
        assert len(rows) == 1 and rows[0].trigger == "AUTOMATIC"
        identifier = rows[0].id
    await client.put(f"/api/technicians/{ready}/schedule-delivery", json={"enabled": False})
    await run_delivery(app, FakeTelegram())
    assert (await row(app, identifier)).status == "CANCELLED"


async def test_auto_missed_window_never_catches_up_next_morning(app, client, ready, monkeypatch):
    await client.put(f"/api/technicians/{ready}/schedule-delivery", json={"enabled": True})
    for stamp in [
        datetime(2026, 9, 18, 3, 30, tzinfo=UTC),
        datetime(2026, 9, 18, 14, 0, tzinfo=UTC),
    ]:
        monkeypatch.setattr(scheduler, "now", lambda stamp=stamp: stamp)
        await scheduler.evaluate(request(app))
    async with app.state.session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(ScheduleDispatch)) == 0
        assert (await db.get(ScheduleAutoDecision, (ready, date(2026, 9, 18)))).state == "MISSED"


async def test_ack_expired_wrong_message_and_group_generation(app, client, ready):
    data = await enqueue(client, ready)
    fake = FakeTelegram()
    await run_delivery(app, fake)
    saved = await row(app, data["id"])
    event = TrustedEvent(
        1,
        "CALLBACK",
        chat_id=saved.chat_id,
        user_id=771001,
        message_id=saved.message_id,
        payload=fake.schedule_sent[0][2],
    )
    assert (
        await acknowledge(app.state.session_factory, replace(event, message_id=888), BOT_ID)
        == "ACK_UNAVAILABLE"
    )
    assert (
        await acknowledge(app.state.session_factory, replace(event, chat_id=888), BOT_ID)
        == "ACK_UNAVAILABLE"
    )
    async with app.state.session_factory() as db, db.begin():
        await db.execute(update(ScheduleDispatch).values(ack_expires_at=now() - timedelta(days=1)))
    assert await acknowledge(app.state.session_factory, event, BOT_ID) == "ACK_UNAVAILABLE"


async def test_sent_immutable_and_payload_retention(app, client, ready):
    from sqlalchemy.exc import IntegrityError

    data = await enqueue(client, ready)
    fake = FakeTelegram()
    fake.send_error = ProviderError("NETWORK_UNCERTAIN")
    await run_delivery(app, fake)
    async with app.state.session_factory() as db, db.begin():
        await db.execute(
            update(ScheduleDispatch).values(payload_expires_at=now() - timedelta(days=1))
        )
    await delivery.purge(app.state.session_factory)
    assert (await row(app, data["id"])).encrypted_payload is None
    async with app.state.session_factory() as db:
        with pytest.raises(IntegrityError):
            await db.execute(update(ScheduleDispatch).values(fingerprint="0" * 64))
            await db.commit()


@pytest.mark.parametrize("where", ["name", "title", "location"])
def test_all_rendered_text_is_escaped(where):
    value = "<a href='https://evil.invalid'>&customer</a>"
    payload = Payload(
        target_date=date(2026, 9, 18),
        technician_name=value if where == "name" else "Tech",
        jobs=(
            PayloadJob(
                time="08:00",
                title=value if where == "title" else "Job",
                location=value if where == "location" else None,
            ),
        ),
    )
    assert "<a" not in payload.render() and "&lt;a" in payload.render()


async def test_provider_inspection_failure_is_not_a_send_attempt(app, client, ready):
    data = await enqueue(client, ready)
    fake = FakeTelegram()
    fake.member_error = ProviderError("NETWORK_UNCERTAIN")
    await run_delivery(app, fake)
    saved = await row(app, data["id"])
    assert saved.status == "FAILED" and saved.attempt_count == 0 and not fake.sent


async def test_retry_after_and_limit(app, client, ready):
    data = await enqueue(client, ready)
    fake = FakeTelegram()
    fake.send_error = ProviderError("RATE_LIMITED", retry_after=30)
    for attempt in range(3):
        await run_delivery(app, fake)
        saved = await row(app, data["id"])
        assert saved.attempt_count == attempt + 1
        if attempt < 2:
            assert saved.status == "PENDING"
            async with app.state.session_factory() as db:
                stamp = await delivery.clock(db)
            assert (saved.available_at - stamp).total_seconds() > 25
            await run_delivery(app, fake)
            assert (await row(app, data["id"])).attempt_count == attempt + 1
            async with app.state.session_factory() as db, db.begin():
                await db.execute(
                    update(ScheduleDispatch).values(available_at=now() - timedelta(minutes=2))
                )
    assert (await row(app, data["id"])).status == "FAILED"


async def test_manager_auth_csrf_and_private_history(app, client, ready):
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://127.0.0.1:3000"
    ) as guest:
        assert (await guest.get(f"/api/technicians/{ready}/schedule-delivery")).status_code == 401
        assert (
            await guest.post(
                f"/api/technicians/{ready}/schedule-dispatches",
                headers={"Origin": "http://127.0.0.1:3000"},
                json=await preview(client, ready),
            )
        ).status_code == 401
    response = await client.put(
        f"/api/technicians/{ready}/schedule-delivery",
        headers={"X-CSRF-Token": "invalid"},
        json={"enabled": True},
    )
    assert response.status_code == 403


async def test_auto_google_failure_never_sends_empty_schedule(
    app, client, google, ready, monkeypatch
):
    from hub.google_calendar.types import ProviderError as GoogleError

    await client.put(f"/api/technicians/{ready}/schedule-delivery", json={"enabled": True})
    stamp = datetime(2026, 9, 18, 0, 30, tzinfo=UTC)
    monkeypatch.setattr(scheduler, "now", lambda: stamp)
    monkeypatch.setattr(service, "now", lambda: stamp)
    google.error = GoogleError("PROVIDER_TEMPORARY_ERROR")
    await scheduler.evaluate(request(app))
    async with app.state.session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(ScheduleDispatch)) == 0
        assert (await db.get(ScheduleAutoDecision, (ready, date(2026, 9, 18)))).state == "RETRY"


@pytest.mark.parametrize("key", [None, "not-a-fernet-key"])
def test_enabled_delivery_missing_key_fails_closed(key):
    from pydantic import ValidationError

    from hub.core.config import Settings

    with pytest.raises((ValidationError, ValueError)):
        Settings(
            _env_file=None, schedule_delivery_enabled=True, schedule_payload_encryption_key=key
        )


async def test_delivery_keeps_single_connection_pool_free_during_provider_io(
    app, client, ready, monkeypatch
):
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(
        app.state.settings.database_url,
        pool_size=1,
        max_overflow=0,
        pool_timeout=2,
        hide_parameters=True,
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(app.state, "session_factory", factory)
    entered, release = asyncio.Event(), asyncio.Event()
    fake = FakeTelegram()
    original = fake.send_schedule

    async def slow(*args):
        entered.set()
        await release.wait()
        return await original(*args)

    fake.send_schedule = slow
    try:
        data = await enqueue(client, ready)
        task = asyncio.create_task(run_delivery(app, fake))
        await asyncio.wait_for(entered.wait(), 10)
        async with factory() as db:
            assert await asyncio.wait_for(db.scalar(text("SELECT 1")), 2) == 1
        release.set()
        await task
        assert (await row(app, data["id"])).status == "SENT"
    finally:
        release.set()
        await engine.dispose()
