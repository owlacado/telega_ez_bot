"""Independent Stage 4 adversarial audit; synthetic providers, real PostgreSQL."""

import asyncio
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from hub.schedule_delivery import delivery
from hub.schedule_delivery.models import ScheduleDispatch
from hub.telegram.types import ProviderError
from tests.fakes import BOT_ID, FakeTelegram
from tests.test_schedule_delivery import (
    assigned as assigned,
)
from tests.test_schedule_delivery import (
    enqueue,
    row,
    run_delivery,
)
from tests.test_schedule_delivery import (
    google as google,
)
from tests.test_schedule_delivery import (
    ready as ready,
)


async def test_fallback_provenance_survives_success(app, client, ready):
    data = await enqueue(client, ready)
    fake = FakeTelegram()
    original = fake.send_schedule
    calls = []

    async def send(*args):
        calls.append(args[0])
        if len(calls) == 1:
            raise ProviderError("CHAT_UNAVAILABLE")
        return await original(*args)

    fake.send_schedule = send
    await run_delivery(app, fake)
    history = (await client.get(f"/api/technicians/{ready}/schedule-delivery")).json()["history"][0]
    assert history["status"] == "SENT"
    assert history.get("requested_destination") == "WORK_GROUP"
    assert history["destination"] == "PRIVATE"
    assert history.get("fallback_reason") == "GROUP_REJECTED_PRIVATE_FALLBACK"
    assert (await row(app, data["id"])).encrypted_payload is None


async def test_failed_payload_has_no_retry_purpose(app, client, ready):
    data = await enqueue(client, ready)
    fake = FakeTelegram()
    fake.send_error = ProviderError("REQUEST_REJECTED")
    await run_delivery(app, fake)
    saved = await row(app, data["id"])
    assert saved.status == "FAILED"
    assert saved.encrypted_payload is None


@pytest.mark.parametrize(
    "field,value", [("chat_id", -12345), ("message_id", 998), ("error_code", "OTHER")]
)
async def test_terminal_receipt_history_cannot_be_rewritten(app, client, ready, field, value):
    await enqueue(client, ready)
    await run_delivery(app, FakeTelegram())
    with pytest.raises(IntegrityError):
        async with app.state.session_factory() as db, db.begin():
            await db.execute(update(ScheduleDispatch).values(**{field: value}))


async def test_expired_head_does_not_hide_ready_work(app, client, ready):
    data = await enqueue(client, ready)
    async with app.state.session_factory() as db, db.begin():
        original = await db.get(ScheduleDispatch, UUID(data["id"]))
        values = {
            c.name: getattr(original, c.name)
            for c in ScheduleDispatch.__table__.columns
            if c.name not in {"id", "created_at", "updated_at"}
        }
        values.update(
            target_date=original.target_date + timedelta(days=1),
            available_at=original.available_at + timedelta(seconds=1),
        )
        second = ScheduleDispatch(**values)
        db.add(second)
        original.delivery_deadline = datetime.now(UTC) - timedelta(days=1)
        # Both available; expired row sorts first.
        original.available_at -= timedelta(days=1)
        second.available_at -= timedelta(hours=1)
        await db.flush()
        second_id = second.id
    ticket = await delivery.claim(app.state.session_factory, BOT_ID)
    assert ticket and ticket[0] == second_id
    assert (await row(app, data["id"])).status == "CANCELLED"


async def population(app, client, ready, count):
    from hub.calendar_events.service import snapshot
    from hub.calendars.models import Calendar, CalendarAssignment
    from hub.integrations.models import TelegramBinding
    from hub.schedule_delivery.domain import source_version
    from hub.technicians.models import Technician
    from tests.test_schedule_delivery import request

    first = await enqueue(client, ready)
    template = await row(app, first["id"])
    ids = [ready]
    async with app.state.session_factory() as db, db.begin():
        original = await db.get(Technician, ready)
        source_cal = await db.get(Calendar, template.calendar_id)
        calendars = {}
        for i in range(count - 1):
            tid = uuid4()
            ids.append(tid)
            db.add(Technician(id=tid, first_name=original.first_name, last_name=original.last_name))
            await db.flush()
            cal_values = {
                c.name: getattr(source_cal, c.name)
                for c in Calendar.__table__.columns
                if c.name not in {"id", "created_at", "updated_at"}
            }
            cal_values["provider_calendar_id"] = "audit-calendar-" + str(i)
            cal = Calendar(**cal_values)
            db.add(cal)
            await db.flush()
            calendars[tid] = cal.id
            db.add(
                CalendarAssignment(
                    id=uuid4(),
                    technician_id=tid,
                    calendar_id=cal.id,
                    calendar_name=cal.name,
                    is_active=True,
                )
            )
            db.add(
                TelegramBinding(
                    technician_id=tid,
                    bot_id=BOT_ID,
                    telegram_user_id=800000 + i,
                    telegram_group_chat_id=-800000 - i,
                    private_status="CONNECTED",
                    group_status="CONNECTED",
                    private_availability="AVAILABLE",
                    group_availability="AVAILABLE",
                    private_generation=1,
                    group_generation=1,
                    group_private_generation=1,
                )
            )
    for i, tid in enumerate(ids[1:]):
        async with app.state.session_factory() as db, db.begin():
            _, identity, _ = await snapshot(
                request(app), tid, preview=True, worker=True, session=db
            )
            values = {
                c.name: getattr(template, c.name)
                for c in ScheduleDispatch.__table__.columns
                if c.name not in {"id", "created_at", "updated_at"}
            }
            values.update(
                technician_id=tid,
                calendar_id=calendars[tid],
                telegram_user_id=800000 + i,
                chat_id=-800000 - i,
                source_version=source_version(identity),
            )
            db.add(ScheduleDispatch(**values))
    return ids


@pytest.mark.parametrize("workers", [2, 5, 10])
async def test_worker_population_invocations(app, client, ready, workers):
    ids = await population(app, client, ready, 20)
    fake = FakeTelegram()
    fake.group(-771002, 771001, 771001)
    for i in range(19):
        fake.group(-800000 - i, 800000 + i, 800000 + i)

    async def drain():
        count = 0
        while await delivery.deliver_one(
            app.state.session_factory, app.state.google_lock_engine, fake, app.state.settings
        ):
            count += 1
        return count

    processed = await asyncio.gather(*[drain() for _ in range(workers)])
    assert sum(processed) == len(ids)
    assert len(fake.schedule_sent) == 20
    assert len({c for c, _, _ in fake.schedule_sent}) == 20
    async with app.state.session_factory() as db:
        rows = (await db.scalars(select(ScheduleDispatch))).all()
        assert all(
            r.status == "SENT" and r.attempt_count == 1 and r.claim_owner is None for r in rows
        )


@pytest.mark.parametrize("failure", [None, "REQUEST_REJECTED", "NETWORK_UNCERTAIN"])
async def test_reclaimed_owner_cannot_finalize_any_terminal(app, client, ready, failure):
    data = await enqueue(client, ready)
    a = await delivery.claim(app.state.session_factory, BOT_ID)
    async with app.state.session_factory() as db, db.begin():
        await db.execute(
            update(ScheduleDispatch).values(
                claim_expires_at=datetime.now(UTC) - timedelta(seconds=1)
            )
        )
    b = await delivery.claim(app.state.session_factory, BOT_ID)
    assert b[2] != a[2]
    await delivery.finish(
        app.state.session_factory,
        a[0],
        a[2],
        message_id=987,
        failure=ProviderError(failure) if failure else None,
    )
    saved = await row(app, data["id"])
    assert saved.status == "PROCESSING" and saved.claim_owner == b[2] and saved.message_id is None


@pytest.mark.parametrize("window", list("ABCDEFGHI"))
async def test_hard_process_death_matrix(app, client, ready, window, tmp_path):
    import json
    import subprocess
    import sys
    from pathlib import Path

    data = await enqueue(client, ready)
    ledger = tmp_path / "invocations.txt"
    args = {
        "url": app.state.settings.database_url,
        "key": app.state.settings.schedule_payload_encryption_key.get_secret_value(),
        "window": window,
        "ledger": str(ledger),
    }
    result = await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-m", "tests.schedule_crash_probe"],
        input=json.dumps(args),
        text=True,
        capture_output=True,
        cwd=Path(__file__).resolve().parents[1],
        timeout=30,
    )
    assert result.returncode == 81, result.stderr
    saved = await row(app, data["id"])
    if saved.status == "PROCESSING":
        async with app.state.session_factory() as db, db.begin():
            await db.execute(
                update(ScheduleDispatch).values(
                    claim_expires_at=datetime.now(UTC) - timedelta(seconds=1)
                )
            )
    fake = FakeTelegram()
    await run_delivery(app, fake)
    await run_delivery(app, fake)
    saved = await row(app, data["id"])
    expected = "SENT" if window in "ABGI" else "AMBIGUOUS"
    assert saved.status == expected
    assert len(fake.schedule_sent) == (1 if window in "AB" else 0)
    assert (len(ledger.read_text().splitlines()) if ledger.exists() else 0) == (
        1 if window in "DEFGHI" else 0
    )
    if expected == "SENT":
        assert saved.encrypted_payload is None
    else:
        assert saved.encrypted_payload is not None and saved.attempt_count == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("user_id", 771002),
        ("user_id", 800001),
        ("chat_id", -990),
        ("message_id", 999),
        ("user_is_bot", True),
        ("anonymous", True),
    ],
)
async def test_ack_identity_context_replays(app, client, ready, field, value):
    from dataclasses import replace

    from hub.schedule_delivery.acknowledgements import acknowledge
    from hub.telegram.types import TrustedEvent

    data = await enqueue(client, ready)
    fake = FakeTelegram()
    await run_delivery(app, fake)
    saved = await row(app, data["id"])
    event = TrustedEvent(
        1,
        "CALLBACK",
        user_id=771001,
        chat_id=saved.chat_id,
        message_id=saved.message_id,
        payload=fake.schedule_sent[0][2],
    )
    assert (
        await acknowledge(app.state.session_factory, replace(event, **{field: value}), BOT_ID)
        == "ACK_UNAVAILABLE"
    )
    assert (await row(app, data["id"])).ack_status == "PENDING"


async def test_twenty_ack_callbacks_one_audit(app, client, ready):
    from sqlalchemy import func

    from hub.audit.models import AuditEvent
    from hub.schedule_delivery.acknowledgements import acknowledge
    from hub.telegram.types import TrustedEvent

    data = await enqueue(client, ready)
    fake = FakeTelegram()
    await run_delivery(app, fake)
    saved = await row(app, data["id"])
    event = TrustedEvent(
        1,
        "CALLBACK",
        user_id=771001,
        chat_id=saved.chat_id,
        message_id=saved.message_id,
        payload=fake.schedule_sent[0][2],
    )
    assert (
        await asyncio.gather(
            *[acknowledge(app.state.session_factory, event, BOT_ID) for _ in range(20)]
        )
        == ["ACKNOWLEDGED"] * 20
    )
    async with app.state.session_factory() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "schedule.acknowledged")
            )
            == 1
        )


@pytest.mark.parametrize(
    "zone",
    [
        "America/New_York",
        "America/Chicago",
        "America/Denver",
        "America/Los_Angeles",
        "America/Phoenix",
    ],
)
@pytest.mark.parametrize("day", [date(2026, 3, 8), date(2026, 11, 1), date(2026, 12, 31)])
@pytest.mark.parametrize(
    "hour,minute,due",
    [
        (19, 59, False),
        (20, 0, True),
        (20, 7, True),
        (22, 59, True),
        (23, 0, False),
        (23, 1, False),
        (0, 30, False),
        (8, 0, False),
    ],
)
def test_timezone_window_matrix(zone, day, hour, minute, due):
    from types import SimpleNamespace
    from zoneinfo import ZoneInfo

    from hub.schedule_delivery.scheduler import in_window

    stamp = (
        datetime.combine(day, datetime.min.time(), ZoneInfo(zone))
        .replace(hour=hour, minute=minute)
        .astimezone(UTC)
    )
    assert in_window(stamp, zone, SimpleNamespace(schedule_auto_delivery_local_time="20:00")) is due


async def test_history_bounds_and_capability_privacy(app, client, ready):
    from hub.schedule_delivery.domain import token_hash

    data = await enqueue(client, ready)
    fake = FakeTelegram()
    await run_delivery(app, fake)
    saved = await row(app, data["id"])
    async with app.state.session_factory() as db, db.begin():
        for i in range(24):
            values = {
                c.name: getattr(saved, c.name)
                for c in ScheduleDispatch.__table__.columns
                if c.name not in {"id", "created_at", "updated_at"}
            }
            values.update(
                target_date=saved.target_date - timedelta(days=i + 1),
                ack_token_hash=token_hash(str(uuid4())),
            )
            db.add(ScheduleDispatch(**values))
    response = await client.get(f"/api/technicians/{ready}/schedule-delivery?limit=1000000")
    assert len(response.json()["history"]) == 20
    for secret in [
        fake.schedule_sent[0][2],
        saved.ack_token_hash,
        str(saved.chat_id),
        "ADDRESS_CANARY",
        "encrypted_payload",
        "ack_token",
    ]:
        assert secret not in response.text


async def test_wrong_group_rebind_private_fallback(app, client, ready):
    from hub.integrations.models import TelegramBinding

    data = await enqueue(client, ready)
    async with app.state.session_factory() as db, db.begin():
        binding = await db.get(TelegramBinding, ready)
        binding.telegram_group_chat_id = -900099
        binding.group_generation += 1
    fake = FakeTelegram()
    await run_delivery(app, fake)
    assert [c for c, _, _ in fake.schedule_sent] == [771001]
    saved = await row(app, data["id"])
    assert (
        saved.destination == "PRIVATE" and saved.fallback_reason == "GROUP_UNAVAILABLE_BEFORE_SEND"
    )


@pytest.mark.parametrize("result", [None, True, 0, -1, "123", {}, 123.0])
async def test_malformed_success_is_ambiguous(app, client, ready, result):
    data = await enqueue(client, ready)
    fake = FakeTelegram()
    calls = []

    async def send(*args):
        calls.append(args[0])
        return result

    fake.send_schedule = send
    await run_delivery(app, fake)
    await run_delivery(app, fake)
    assert (await row(app, data["id"])).status == "AMBIGUOUS" and calls == [-771002]


async def test_worker_stale_health_is_independent_of_api(app, ready):
    from hub.schedule_delivery.health import inspect
    from hub.schedule_delivery.models import ScheduleWorkerState

    async with app.state.session_factory() as db, db.begin():
        db.add(
            ScheduleWorkerState(
                worker_id=uuid4(),
                status="RUNNING",
                heartbeat_at=datetime.now(UTC) - timedelta(minutes=3),
            )
        )
    health = await inspect(app.state.session_factory, BOT_ID)
    assert health["database"] == "CONNECTED" and health["schedule_worker"] == "UNAVAILABLE"
    async with app.state.session_factory() as db, db.begin():
        await db.execute(update(ScheduleWorkerState).values(heartbeat_at=datetime.now(UTC)))
    assert (await inspect(app.state.session_factory, BOT_ID))["schedule_running_instances"] == 1


@pytest.mark.parametrize(
    "change",
    ["assignment", "scope", "disconnect", "excluded", "unavailable", "inactive"],
)
async def test_authoritative_fetch_lifecycle_races(app, client, google, ready, change):
    from sqlalchemy import func

    from hub.calendars.models import Calendar, CalendarAssignment
    from hub.google_calendar.models import CalendarConnection
    from hub.google_calendar.types import SCOPE
    from hub.technicians.models import Technician
    from tests.test_schedule_delivery import preview

    body = await preview(client, ready)
    entered, release = asyncio.Event(), asyncio.Event()
    original = google.list_events

    async def slow(*args):
        entered.set()
        await release.wait()
        return await original(*args)

    google.list_events = slow
    sending = asyncio.create_task(
        client.post(f"/api/technicians/{ready}/schedule-dispatches", json=body)
    )
    await asyncio.wait_for(entered.wait(), 5)
    try:
        async with app.state.session_factory() as db, db.begin():
            if change == "assignment":
                await db.execute(update(CalendarAssignment).values(is_active=False))
            elif change == "scope":
                await db.execute(update(CalendarConnection).values(granted_scopes=[SCOPE]))
            elif change == "disconnect":
                await db.execute(
                    update(CalendarConnection).values(
                        status="DISCONNECTED", encrypted_refresh_token=None
                    )
                )
            elif change == "excluded":
                await db.execute(update(Calendar).values(excluded_at=datetime.now(UTC)))
            elif change == "unavailable":
                await db.execute(update(Calendar).values(availability="UNAVAILABLE"))
            elif change == "inactive":
                await db.execute(
                    update(Technician).where(Technician.id == ready).values(status="INACTIVE")
                )
    finally:
        release.set()
    response = await asyncio.wait_for(sending, 10)
    assert response.status_code in {404, 409}
    async with app.state.session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(ScheduleDispatch)) == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("jobs", [{"time": "08:00", "title": "EXTRA", "location": "FAKE_ADDRESS"}]),
        ("location", "NEW ADDRESS"),
        ("time", "20:00"),
        ("technician_name", "OTHER"),
        ("removed_job", True),
    ],
)
async def test_frontend_content_cannot_become_authority(client, ready, field, value):
    from tests.test_schedule_delivery import preview

    body = await preview(client, ready)
    body[field] = value
    result = await client.post(f"/api/technicians/{ready}/schedule-dispatches", json=body)
    assert result.status_code == 422


@pytest.mark.parametrize("session_state", ["anonymous", "inactive", "logged_out", "forged"])
async def test_all_schedule_routes_require_current_manager(app, client, ready, session_state):
    from httpx import ASGITransport, AsyncClient

    from hub.auth.models import Manager, ManagerSession

    if session_state in {"inactive", "logged_out"}:
        async with app.state.session_factory() as db, db.begin():
            await db.execute(
                update(Manager).values(is_active=False)
                if session_state == "inactive"
                else update(ManagerSession).values(revoked_at=datetime.now(UTC))
            )
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://127.0.0.1:3000",
        headers={"Origin": "http://127.0.0.1:3000"},
    ) as guest:
        actor = client if session_state in {"inactive", "logged_out"} else guest
        if session_state == "forged":
            guest.cookies.set("hub_session", "unauthorized-account")
        for method, suffix, body in [
            ("GET", "schedule-delivery", None),
            ("PUT", "schedule-delivery", {"enabled": True}),
            ("POST", "schedule-dispatches", {"target_date": "2026-09-18", "fingerprint": "a" * 64}),
            (
                "POST",
                "schedule-dispatches",
                {
                    "target_date": "2026-09-18",
                    "fingerprint": "a" * 64,
                    "resend_of_id": str(uuid4()),
                    "confirm_duplicate_risk": True,
                },
            ),
        ]:
            response = await actor.request(method, f"/api/technicians/{ready}/{suffix}", json=body)
            assert response.status_code == 401


@pytest.mark.parametrize("headers", [{"Origin": "https://evil.invalid"}, {"X-CSRF-Token": "bad"}])
async def test_schedule_mutations_require_origin_csrf(client, ready, headers):
    for method, suffix, body in [
        ("PUT", "schedule-delivery", {"enabled": True}),
        ("POST", "schedule-dispatches", {"target_date": "2026-09-18", "fingerprint": "a" * 64}),
    ]:
        assert (
            await client.request(
                method, f"/api/technicians/{ready}/{suffix}", json=body, headers=headers
            )
        ).status_code == 403


@pytest.mark.parametrize("size", [4095, 4096, 4097])
def test_exact_escaped_message_boundary(size):
    from hub.schedule_delivery.domain import Payload, PayloadJob

    baseline = Payload(
        target_date=date(2026, 9, 18),
        technician_name="Tech",
        jobs=(PayloadJob(time="08:00", title="&", location=None),),
    )
    extra = size - len(baseline.render().encode("utf-16-le")) // 2
    payload = baseline.model_copy(update={"technician_name": "Tech" + "X" * extra})
    if size > 4096:
        with pytest.raises(ValueError, match="SCHEDULE_TOO_LARGE"):
            payload.render()
    else:
        assert len(payload.render().encode("utf-16-le")) // 2 == size


@pytest.mark.parametrize("location", [None, "", " ", "\r\n"])
def test_canonical_optional_text(location):
    from types import SimpleNamespace as N

    from hub.schedule_delivery.domain import from_schedule

    schedule = N(
        operational_date=date(2026, 9, 18),
        technician=N(first_name="Jos\u00e9", last_name="Tech"),
        jobs=[N(display_start_time="08:00", schedule_summary="Repair", location=None)],
    )
    original = from_schedule(schedule)
    schedule.technician.first_name = "Jose\u0301"
    schedule.jobs[0].schedule_summary = "  Repair  "
    schedule.jobs[0].location = location
    assert from_schedule(schedule).fingerprint == original.fingerprint
    assert from_schedule(schedule).render() == original.render()


async def test_purge_with_review_history_resend_and_send(app, client, ready):
    from tests.test_schedule_delivery import preview

    data = await enqueue(client, ready)
    fake = FakeTelegram()
    fake.send_error = ProviderError("NETWORK_UNCERTAIN")
    await run_delivery(app, fake)
    saved = await row(app, data["id"])
    async with app.state.session_factory() as db, db.begin():
        await db.execute(
            update(ScheduleDispatch).values(
                payload_expires_at=datetime.now(UTC) - timedelta(days=8)
            )
        )
    body = {
        **await preview(client, ready),
        "resend_of_id": data["id"],
        "confirm_duplicate_risk": True,
    }
    results = await asyncio.gather(
        delivery.purge(app.state.session_factory),
        client.get(f"/api/technicians/{ready}/schedule-delivery"),
        enqueue(client, ready, body),
    )
    await asyncio.gather(
        delivery.purge(app.state.session_factory), run_delivery(app, FakeTelegram())
    )
    await delivery.purge(app.state.session_factory)
    old = await row(app, data["id"])
    assert old.status == saved.status == "AMBIGUOUS" and old.finished_at == saved.finished_at
    assert old.encrypted_payload is None
    assert (await row(app, results[2]["id"])).status == "SENT"


@pytest.mark.parametrize("code", ["NETWORK_UNCERTAIN", "PROVIDER_UNAVAILABLE", "PROCESSING_FAILED"])
async def test_accept_then_failure_never_falls_back_or_retries(app, client, ready, code, caplog):
    import logging

    caplog.set_level(logging.INFO)
    data = await enqueue(client, ready)
    fake = FakeTelegram()
    calls = []

    async def send(*args):
        calls.append(args[0])
        raise ProviderError(code)

    fake.send_schedule = send
    await run_delivery(app, fake)
    await run_delivery(app, fake)
    assert calls == [-771002] and (await row(app, data["id"])).status == "AMBIGUOUS"
    for private in ["ADDRESS_CANARY", "771002", "sch:", "encrypted_payload"]:
        assert private not in caplog.text


async def test_many_paused_sends_keep_small_pool_and_health_free(app, client, ready, monkeypatch):
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    await population(app, client, ready, 5)
    engine = create_async_engine(
        app.state.settings.database_url, pool_size=2, max_overflow=0, pool_timeout=2
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(app.state, "session_factory", factory)
    entered, release = asyncio.Event(), asyncio.Event()
    invocations = []
    fake = FakeTelegram()
    fake.group(-771002, 771001, 771001)
    for i in range(4):
        fake.group(-800000 - i, 800000 + i, 800000 + i)

    async def send(*args):
        invocations.append(args[0])
        if len(invocations) == 5:
            entered.set()
        await release.wait()
        return 123

    fake.send_schedule = send
    tasks = [
        asyncio.create_task(
            delivery.deliver_one(factory, app.state.google_lock_engine, fake, app.state.settings)
        )
        for _ in range(5)
    ]
    try:
        await asyncio.wait_for(entered.wait(), 15)
        async with factory() as db:
            assert await asyncio.wait_for(db.scalar(text("SELECT 1")), 2) == 1
        assert (await asyncio.wait_for(client.get("/api/health"), 2)).status_code == 200
        assert (
            await asyncio.wait_for(client.get(f"/api/technicians/{ready}/schedule-delivery"), 2)
        ).status_code == 200
    finally:
        release.set()
        await asyncio.gather(*tasks)
        await engine.dispose()
    assert len(set(invocations)) == 5


async def test_delivery_lane_progresses_during_slow_scheduler(
    app, client, google, ready, monkeypatch
):
    from hub.schedule_delivery import worker as module
    from hub.schedule_delivery.worker import Worker

    data = await enqueue(client, ready)
    release, entered = asyncio.Event(), asyncio.Event()

    async def slow(*args):
        entered.set()
        await release.wait()

    monkeypatch.setattr(module, "evaluate", slow)
    fake = FakeTelegram()
    fake.group(-771002, 771001, 771001)
    worker = Worker(
        app.state.settings, app.state.engine, app.state.google_lock_engine, fake, google
    )
    cycle = asyncio.create_task(worker.cycle())
    try:
        await asyncio.wait_for(entered.wait(), 5)
        for _ in range(100):
            if (await row(app, data["id"])).status == "SENT":
                break
            await asyncio.sleep(0.02)
        assert (await row(app, data["id"])).status == "SENT"
    finally:
        release.set()
        await cycle


@pytest.mark.parametrize("count", [20, 50, 250])
async def test_due_population_query_cost(app, client, ready, monkeypatch, count):
    import json
    from pathlib import Path
    from time import perf_counter

    from sqlalchemy import event

    from hub.schedule_delivery import scheduler, service
    from hub.schedule_delivery.models import ScheduleAutoDecision, ScheduleDeliverySetting
    from tests.test_schedule_delivery import request

    ids = await population(app, client, ready, count)
    async with app.state.session_factory() as db, db.begin():
        db.add_all([ScheduleDeliverySetting(technician_id=tid, enabled=True) for tid in ids])
    stamp = datetime(2026, 9, 18, 0, 30, tzinfo=UTC)
    monkeypatch.setattr(scheduler, "now", lambda: stamp)
    monkeypatch.setattr(service, "now", lambda: stamp)
    statements = []

    def observed(conn, cursor, sql, parameters, context, executemany):
        statements.append(sql.split()[0])

    event.listen(app.state.engine.sync_engine, "before_cursor_execute", observed)
    try:
        start = perf_counter()
        await scheduler.evaluate(request(app))
        elapsed = perf_counter() - start
        decision_queries = len(statements)
        statements.clear()
        start = perf_counter()
        tickets = await asyncio.gather(
            *[delivery.claim(app.state.session_factory, BOT_ID) for _ in range(10)]
        )
        claim_seconds = perf_counter() - start
        claim_queries = len(statements)
        statements.clear()
        response = await client.get(f"/api/technicians/{ready}/schedule-delivery")
        history_queries = len(statements)
        assert response.status_code == 200 and len({t[0] for t in tickets}) == 10
        async with app.state.session_factory() as db:
            decisions = (await db.scalars(select(ScheduleAutoDecision))).all()
            assert len(decisions) == count and all(d.state == "SUPPRESSED" for d in decisions)
        assert decision_queries < count * 100 and history_queries < 30 and claim_queries < 120
        evidence = {
            "technicians": count,
            "decision_seconds": round(elapsed, 3),
            "decision_queries": decision_queries,
            "ten_claim_seconds": round(claim_seconds, 3),
            "ten_claim_queries": claim_queries,
            "history_queries": history_queries,
        }
        with (Path(__file__).resolve().parents[3] / ".local/stage4-audit-performance.jsonl").open(
            "a", encoding="utf-8"
        ) as report:
            report.write(json.dumps(evidence) + "\n")
    finally:
        event.remove(app.state.engine.sync_engine, "before_cursor_execute", observed)


async def test_worker_uses_approved_payload_without_google_reads(
    app, client, google, ready, monkeypatch
):
    from hub.calendar_events import service as events

    await enqueue(client, ready)
    google.events = []

    async def forbidden(*args, **kwargs):
        raise AssertionError("Delivery attempted to replace approved snapshot")

    monkeypatch.setattr(events, "read_schedule", forbidden)
    fake = FakeTelegram()
    await run_delivery(app, fake)
    assert len(fake.schedule_sent) == 1 and "ADDRESS_CANARY" in fake.schedule_sent[0][1]


async def test_manual_auto_and_resend_serialization(app, client, google, ready, monkeypatch):
    from hub.schedule_delivery import scheduler, service
    from hub.schedule_delivery.models import ScheduleDeliverySetting
    from tests.test_schedule_delivery import preview, request

    async with app.state.session_factory() as db, db.begin():
        db.add(ScheduleDeliverySetting(technician_id=ready, enabled=True))
    stamp = datetime(2026, 9, 18, 0, 30, tzinfo=UTC)
    monkeypatch.setattr(scheduler, "now", lambda: stamp)
    monkeypatch.setattr(service, "now", lambda: stamp)
    automatic = await service.create_dispatch(request(app), ready, automatic=True)
    body = await preview(client, ready)
    assert (await enqueue(client, ready, body))["id"] == str(automatic.id)
    await run_delivery(app, FakeTelegram())
    body.update(resend_of_id=str(automatic.id), confirm_duplicate_risk=True)
    responses = await asyncio.gather(
        *[client.post(f"/api/technicians/{ready}/schedule-dispatches", json=body) for _ in range(2)]
    )
    accepted = [r.json()["id"] for r in responses if r.status_code == 202]
    assert accepted and len(set(accepted)) == 1
    async with app.state.session_factory() as db:
        rows = (await db.scalars(select(ScheduleDispatch))).all()
        assert len(rows) == 2 and len([r for r in rows if r.status == "PENDING"]) == 1


@pytest.mark.parametrize(
    "values",
    [
        {"status": "SENT"},
        {"ack_status": "ACKNOWLEDGED"},
        {"message_id": 17},
        {
            "status": "CANCELLED",
            "finished_at": datetime(2026, 9, 18, tzinfo=UTC),
            "claim_owner": uuid4(),
            "claim_expires_at": datetime(2026, 9, 19, tzinfo=UTC),
        },
        {"encrypted_payload": None},
        {"fingerprint": "bad"},
        {"attempt_count": -1},
        {"trigger": "MANUAL_RESEND"},
        {"ack_token_hash": "a" * 64},
        {"fallback_reason": "GROUP_UNAVAILABLE_BEFORE_SEND"},
    ],
)
async def test_database_rejects_impossible_states(app, client, ready, values):
    await enqueue(client, ready)
    with pytest.raises(IntegrityError):
        async with app.state.session_factory() as db, db.begin():
            await db.execute(update(ScheduleDispatch).values(**values))


async def test_expired_ack_preserves_sent_history(app, client, ready):
    from hub.schedule_delivery.acknowledgements import acknowledge
    from hub.telegram.types import TrustedEvent

    data = await enqueue(client, ready)
    fake = FakeTelegram()
    await run_delivery(app, fake)
    saved = await row(app, data["id"])
    async with app.state.session_factory() as db, db.begin():
        await db.execute(
            update(ScheduleDispatch).values(ack_expires_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    event = TrustedEvent(
        1,
        "CALLBACK",
        user_id=771001,
        chat_id=saved.chat_id,
        message_id=saved.message_id,
        payload=fake.schedule_sent[0][2],
    )
    assert await acknowledge(app.state.session_factory, event, BOT_ID) == "ACK_UNAVAILABLE"
    current = await row(app, data["id"])
    assert (
        current.status == "SENT"
        and current.ack_status == "PENDING"
        and current.finished_at == saved.finished_at
    )


async def test_unexpected_provider_exception_is_redacted(app, client, ready, caplog):
    import logging

    caplog.set_level(logging.INFO)
    data = await enqueue(client, ready)
    fake = FakeTelegram()

    async def send(chat, message, token):
        raise RuntimeError("AUDIT_PRIVATE_EXCEPTION_ADDRESS " + message + token + str(chat))

    fake.send_schedule = send
    await run_delivery(app, fake)
    assert (await row(app, data["id"])).status == "AMBIGUOUS"
    for marker in ["AUDIT_PRIVATE_EXCEPTION_ADDRESS", "ADDRESS_CANARY", "771002", "sch:"]:
        assert marker not in caplog.text


async def test_prepare_keeps_calendar_assignment_lock_order(app, client, ready):
    from hub.google_calendar.service import mutation_lock
    from hub.technicians.models import Technician

    await enqueue(client, ready)
    ticket = await delivery.claim(app.state.session_factory, BOT_ID)
    task = None
    try:
        async with app.state.session_factory() as db, db.begin():
            await mutation_lock(db)
            task = asyncio.create_task(
                delivery.prepare(
                    app.state.session_factory, ticket[0], ticket[2], app.state.settings
                )
            )
            await asyncio.sleep(0.1)
            # A calendar assignment already holding the global lock must still
            # obtain the technician lock without a cycle against preparation.
            assert await asyncio.wait_for(db.get(Technician, ready, with_for_update=True), 2)
        assert await asyncio.wait_for(task, 3)
    finally:
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_prepare_rechecks_lease_after_waiting_for_calendar_lock(app, client, ready):
    from hub.google_calendar.service import mutation_lock

    await enqueue(client, ready)
    ticket = await delivery.claim(app.state.session_factory, BOT_ID)
    async with app.state.session_factory() as db, db.begin():
        stamp = await delivery.clock(db)
        await db.execute(
            update(ScheduleDispatch).values(claim_expires_at=stamp + timedelta(seconds=0.2))
        )
    async with app.state.session_factory() as db, db.begin():
        await mutation_lock(db)
        task = asyncio.create_task(
            delivery.prepare(app.state.session_factory, ticket[0], ticket[2], app.state.settings)
        )
        await asyncio.sleep(0.4)
    assert await asyncio.wait_for(task, 3) is None
    saved = await row(app, ticket[0])
    assert saved.attempt_count == 0 and saved.provider_started_at is None
    reclaimed = await delivery.claim(app.state.session_factory, BOT_ID)
    assert reclaimed and reclaimed[2] != ticket[2]
