"""Independent Stage 6 adversarial probes against isolated PostgreSQL."""

import asyncio
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import DBAPIError

from hub.expenses import service
from hub.expenses.models import ExpenseRevision, TechnicianExpense
from hub.expenses.schemas import ExpenseInput
from hub.technicians.models import Technician
from hub.work_reports import service as forms
from hub.work_reports.models import TechnicianFormSession
from tests.test_expenses import BASE, PAYLOAD, counts, issue, send
from tests.test_expenses import ready as ready_fixture

ready = ready_fixture


@pytest.mark.parametrize(
    "amount",
    [
        "1.001",
        "1.009",
        "-0.001",
        "9999999999.991",
        "10000000000",
        "-1",
        "NaN",
        "Infinity",
        "-Infinity",
    ],
)
async def test_sql_never_rounds_invalid_money(app, ready, amount):
    await send(app, await issue(app))
    with pytest.raises(DBAPIError):
        async with app.state.session_factory() as db, db.begin():
            identifier = uuid4()
            await db.execute(
                text("INSERT INTO technician_expenses(id,technician_id) VALUES (:id,:tid)"),
                {"id": identifier, "tid": ready},
            )
            await db.execute(
                text("""INSERT INTO expense_revisions
            (id,expense_id,revision_number,technician_name,expense_date,accounting_timezone,expense_type,amount,note,submitted_at)
            SELECT
gen_random_uuid(),:id,1,technician_name,expense_date,accounting_timezone,expense_type,CAST(:amount
AS numeric),note,submitted_at FROM expense_revisions LIMIT 1"""),
                {"id": identifier, "amount": amount},
            )
    assert await counts(app) == (1, 1)


ZONES = [
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
    "America/Phoenix",
]


@pytest.mark.parametrize("zone", ZONES)
@pytest.mark.parametrize("day", ["2030-03-10", "2030-11-03", "2030-08-21"])
async def test_timezone_midnight_dst_postgres_oracle(app, ready, zone, day):
    # An independent PG oracle, with the session timezone deliberately set elsewhere.
    start = datetime.fromisoformat(day).replace(tzinfo=ZoneInfo(zone)).astimezone(UTC)
    async with app.state.session_factory() as db:
        await db.execute(text("SET TIME ZONE 'Asia/Tokyo'"))
        for offset in [-1, 0, 3600, 7200, 10800, 86399, 86400]:
            instant = start + timedelta(seconds=offset)
            expected = await db.scalar(
                text("SELECT (CAST(:instant AS timestamptz) AT TIME ZONE :zone)::date"),
                {"instant": instant, "zone": zone},
            )
            assert service.local_date(instant, zone) == expected
        assert service.local_date(start - timedelta(seconds=1), zone) < service.local_date(
            start, zone
        )


@pytest.mark.parametrize(
    "zone,expected",
    [
        ("America/New_York", "2030-08-21"),
        ("America/Chicago", "2030-08-20"),
        ("America/Denver", "2030-08-20"),
        ("America/Los_Angeles", "2030-08-20"),
        ("America/Phoenix", "2030-08-20"),
        ("Etc/GMT+5", "2030-08-20"),
    ],
)
def test_same_utc_instant_distinct_local_days(zone, expected):
    assert (
        service.local_date(datetime(2030, 8, 21, 4, 30, tzinfo=UTC), zone).isoformat() == expected
    )


async def test_timezone_change_preserves_snapshot(app, client, ready, monkeypatch):
    instant = datetime(2030, 8, 21, 4, 30, tzinfo=UTC)

    async def clock(db):
        return instant

    monkeypatch.setattr(forms, "database_now", clock)
    await client.patch(
        f"/api/technicians/{ready}", json={"accounting_timezone": "America/New_York"}
    )
    first = await send(app, await issue(app))
    await client.patch(f"/api/technicians/{ready}", json={"accounting_timezone": "America/Denver"})
    second = await send(app, await issue(app))
    a = (await client.get(f"/api/expenses/{first.expense_id}")).json()
    b = (await client.get(f"/api/expenses/{second.expense_id}")).json()
    assert (a["accounting_timezone"], a["expense_date"]) == ("America/New_York", "2030-08-21")
    assert (b["accounting_timezone"], b["expense_date"]) == ("America/Denver", "2030-08-20")


@pytest.mark.parametrize(
    "zone",
    [
        "",
        " ",
        "Invalid/Zone",
        "../UTC",
        "America/\u202eDenver",
        "Factory",
        "localtime",
        "posix/America/New_York",
        "right/America/New_York",
    ],
)
async def test_invalid_or_environment_timezone_rejected(client, ready, zone):
    assert (
        await client.patch(f"/api/technicians/{ready}", json={"accounting_timezone": zone})
    ).status_code == 422


async def test_missing_timezone_direct_http_and_local_date(app, client, ready):
    token = await issue(app)
    await client.patch(f"/api/technicians/{ready}", json={"accounting_timezone": None})
    for suffix, payload in [("", None), ("/submit", PAYLOAD)]:
        response = await client.post(
            BASE + suffix, headers={"Authorization": f"Bearer {token}"}, json=payload
        )
        assert response.status_code == 409
    with pytest.raises(HTTPException):
        service.local_date(datetime.now(UTC), None)
    assert await issue(app) is None
    assert await counts(app) == (0, 0)


async def test_expiry_crossed_while_waiting_for_lock(app, ready):
    token = await issue(app)
    async with app.state.session_factory() as db, db.begin():
        await db.execute(
            text(
                "UPDATE technician_form_sessions "
                "SET expires_at=clock_timestamp()+interval '1 second'"
            )
        )
    async with app.state.session_factory() as db, db.begin():
        await db.get(Technician, ready, with_for_update=True)
        tasks = [asyncio.create_task(send(app, token)) for _ in range(4)]
        await db.execute(text("SELECT pg_sleep(1.1)"))
        assert not any(task.done() for task in tasks)
    results = await asyncio.gather(*tasks, return_exceptions=True)
    assert all(isinstance(r, HTTPException) and r.status_code == 410 for r in results)
    assert await counts(app) == (0, 0)


async def test_just_before_expiry_and_distinct_concurrent_sessions(app, ready, monkeypatch):
    tokens = [await issue(app) for _ in range(5)]
    async with app.state.session_factory() as db:
        cutoff = await db.scalar(select(func.min(TechnicianFormSession.expires_at)))

    async def clock(db):
        return cutoff - timedelta(microseconds=1)

    monkeypatch.setattr(forms, "database_now", clock)
    results = await asyncio.gather(*(send(app, token) for token in tokens))
    assert len({r.expense_id for r in results}) == 5
    assert await counts(app) == (5, 5)


async def test_submit_first_delete_waits_then_fails(app, ready, monkeypatch):
    token = await issue(app)
    locked, release = asyncio.Event(), asyncio.Event()
    original = forms.authorize

    async def pause(*args, **kwargs):
        result = await original(*args, **kwargs)
        locked.set()
        await release.wait()
        return result

    monkeypatch.setattr(forms, "authorize", pause)
    submission = asyncio.create_task(send(app, token))
    await asyncio.wait_for(locked.wait(), 5)

    async def delete():
        async with app.state.session_factory() as db, db.begin():
            await db.execute(text("DELETE FROM technicians WHERE id=:id"), {"id": ready})

    deletion = asyncio.create_task(delete())
    await asyncio.sleep(0.05)
    assert not deletion.done()
    release.set()
    await submission
    with pytest.raises(DBAPIError):
        await deletion
    assert await counts(app) == (1, 1)


@pytest.mark.parametrize("amount", ["0", "0.00", "0.01", "1", "1.1", "1.10", "9999999999.99"])
def test_exact_money_forms(amount):
    assert ExpenseInput(expense_type="Gas", amount=amount).amount == Decimal(amount)


@pytest.mark.parametrize(
    "amount",
    [
        "-Infinity",
        "1E3",
        "1e3",
        "1,000",
        pytest.param("1" * 100000, id="huge-number"),
        "\u0661.00",
        1,
        1.0,
    ],
)
def test_rejected_money_forms(amount):
    with pytest.raises(ValidationError):
        ExpenseInput(expense_type="Gas", amount=amount)


@pytest.mark.parametrize("kind", ["gas", "Gas", "GAS", "**Parking**"])
def test_case_and_markdown_are_literal(kind):
    assert ExpenseInput(expense_type=kind, amount="0").expense_type == kind


@pytest.mark.parametrize(
    "note",
    [
        pytest.param("x" * 4000, id="4000-ascii"),
        pytest.param("\U0001f527" * 4000, id="4000-emoji"),
        pytest.param("line1\nline2\tcolumn", id="multiline"),
        pytest.param("<script>synthetic-PII</script>", id="literal-html"),
    ],
)
def test_notes_boundary_unicode_literal(note):
    assert ExpenseInput(expense_type="Gas", amount="0", note=note).note == note


async def test_multi_megabyte_request_rejected(client, ready):
    response = await client.post(
        BASE + "/submit",
        content=b'{"note":"' + b"x" * 3_000_000 + b'"}',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413


@pytest.mark.parametrize(
    "changes",
    [
        {"chat_type": "supergroup"},
        {"chat_type": "channel"},
        {"chat_type": None},
        {"user_id": None},
        {"chat_id": None},
    ],
)
async def test_private_only_malformed(app, ready, changes):
    assert await issue(app, **changes) is None


async def test_thousand_shared_sessions_bounded_open_retained_metadata(app, ready):
    for index in range(1000):
        if index % 2:
            await issue(app)
        else:
            from hub.telegram.types import TrustedEvent
            from tests.fakes import BOT_ID

            async with app.state.session_factory() as db, db.begin():
                await forms.issue(
                    db,
                    TrustedEvent(
                        index, "COMMAND", user_id=771001, chat_id=771001, chat_type="private"
                    ),
                    BOT_ID,
                    app.state.settings,
                )
    async with app.state.session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(TechnicianFormSession)) == 1000
        assert (
            await db.scalar(
                select(func.count())
                .select_from(TechnicianFormSession)
                .where(TechnicianFormSession.status == "OPEN")
            )
            == 5
        )


@pytest.mark.parametrize("size", [10, 100, 1000, 10000])
async def test_expense_read_scale(app, ready, size, record_property):
    async with app.state.session_factory() as db, db.begin():
        # Set-based synthetic seeding; every parent/revision guard remains enabled.
        await db.execute(
            text("""WITH parents AS (
          INSERT INTO technician_expenses(id,technician_id)
          SELECT gen_random_uuid(),:tid FROM generate_series(1,:size) RETURNING id)
          INSERT INTO
expense_revisions(id,expense_id,revision_number,technician_name,expense_date,accounting_timezone,expense_type,amount,note,submitted_at)
          SELECT gen_random_uuid(),id,1,'Scale Fictional',(clock_timestamp() AT TIME ZONE
'America/Los_Angeles')::date,'America/Los_Angeles','Gas',1.01,'',clock_timestamp() FROM
parents"""),
            {"tid": ready, "size": size},
        )
    async with app.state.session_factory() as db:
        tech = await db.get(Technician, ready)
        engine = db.bind.sync_engine
        queries = []

        def observe(*args):
            queries.append(args[2])

        event.listen(engine, "before_cursor_execute", observe)
        try:
            start = time.perf_counter()
            result = await service.list_expenses(db, tech, 20)
            list_ms = (time.perf_counter() - start) * 1000
            assert result.today_count == size and result.today_total == Decimal("1.01") * size
            assert len(result.expenses) == min(20, size)
            assert len(queries) == 2  # database clock plus one coherent projection
            assert list_ms < 5000, "Expense read regressed to pathological scaling"
            queries.clear()
            start = time.perf_counter()
            row = (
                await db.execute(
                    service.current_expenses().where(TechnicianExpense.id == result.expenses[0].id)
                )
            ).one()
            assert service.expense_view(*row).amount == Decimal("1.01")
            detail_ms = (time.perf_counter() - start) * 1000
            assert len(queries) == 1
            record_property(
                "performance", f"{size}:list={list_ms:.2f}ms/detail={detail_ms:.2f}ms/queries=2+1"
            )
        finally:
            event.remove(engine, "before_cursor_execute", observe)


async def test_expiry_rechecked_at_submission_instant(app, ready, monkeypatch):
    token = await issue(app)
    async with app.state.session_factory() as db:
        cutoff = await db.scalar(select(TechnicianFormSession.expires_at))
    ticks = iter([cutoff - timedelta(microseconds=1), cutoff])

    async def clock(db):
        return next(ticks)

    monkeypatch.setattr(forms, "database_now", clock)
    with pytest.raises(HTTPException) as error:
        await send(app, token)
    assert error.value.status_code == 410
    assert await counts(app) == (0, 0)


async def test_timezone_choices_authenticated_supported_and_summary(client, app, ready):
    response = await client.get("/api/accounting-timezones")
    assert response.status_code == 200
    assert set(ZONES) <= set(response.json())
    assert not {"Factory", "localtime"} & set(response.json())
    async with app.state.session_factory() as db:
        supported = set(await db.scalars(text("SELECT name FROM pg_timezone_names")))
    assert set(response.json()) <= supported
    listing = (await client.get("/api/technicians")).json()
    assert listing[0]["accounting_timezone"] == "America/Los_Angeles"
    client.cookies.clear()
    assert (await client.get("/api/accounting-timezones")).status_code == 401


async def test_missing_timezone_bot_truthful_and_no_enumeration(app, client, ready):
    from hub.telegram.types import TrustedEvent
    from hub.telegram.updates import process_update
    from tests.fakes import BOT_ID, FakeTelegram

    await client.patch(f"/api/technicians/{ready}", json={"accounting_timezone": None})
    for user in [771001, 555000]:
        result = await process_update(
            app.state.session_factory,
            FakeTelegram(),
            TrustedEvent(
                user,
                "COMMAND",
                user_id=user,
                chat_id=user,
                chat_type="private",
                command="/expenses",
            ),
            BOT_ID,
            settings=app.state.settings,
        )
        assert result.outcome == "UNAVAILABLE"
        assert "accounting timezone" in result.reply
        assert str(ready) not in result.reply and "/technician/expense#" not in result.reply


@pytest.mark.parametrize("zone", ZONES)
async def test_server_submission_uses_explicit_zone(app, client, ready, monkeypatch, zone):
    instant = datetime(2030, 8, 21, 4, 30, tzinfo=UTC)

    async def clock(db):
        return instant

    monkeypatch.setattr(forms, "database_now", clock)
    assert (
        await client.patch(f"/api/technicians/{ready}", json={"accounting_timezone": zone})
    ).status_code == 200
    result = await send(app, await issue(app))
    async with app.state.session_factory() as db:
        row = await db.scalar(
            select(ExpenseRevision).where(ExpenseRevision.expense_id == result.expense_id)
        )
        expected = await db.scalar(
            text("SELECT (CAST(:instant AS timestamptz) AT TIME ZONE :zone)::date"),
            {"instant": instant, "zone": zone},
        )
        assert row.expense_date == expected and row.accounting_timezone == zone
        assert row.submitted_at == instant
