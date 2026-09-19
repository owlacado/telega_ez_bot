import asyncio
import json
import statistics
import time
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import event, select, text, update

from hub.accounting import domain, service
from hub.expenses.models import ExpenseRevision, TechnicianExpense
from hub.technicians.models import Technician
from hub.work_reports.models import WorkReport, WorkReportRevision
from tests.accounting_data import GOLDEN, seed

START = date(2026, 9, 14)


@pytest.fixture
async def accounting(app):
    return await seed(app.state.session_factory, START)


async def calculate(app, tid, kind="weekly", selector=START):
    async with app.state.session_factory() as db:
        return await service.calculate(db, tid, kind, selector)


async def test_legacy_golden_week_and_every_day(app, accounting):
    week = await calculate(app, accounting)
    assert week.totals.model_dump(mode="json") == GOLDEN["weekly"]
    assert len(week.days) == 7
    for index, day in enumerate(week.days):
        assert day.totals.model_dump(mode="json") == GOLDEN["days"][index]
        daily = await calculate(app, accounting, "daily", START + timedelta(days=index))
        assert daily.totals == day.totals
    assert week.days[-1].reports[-1].revision_number == 2
    assert week.days[-1].expenses[0].revision_number == 2
    for key in [
        "gross_total",
        "expense_total",
        "report_count",
        "expense_count",
        "maintenance_count",
    ]:
        assert sum(getattr(d.totals, key) for d in week.days) == getattr(week.totals, key)
    for key in ["payments", "reviews", "closed_by"]:
        for code, value in getattr(week.totals, key).items():
            assert sum(getattr(d.totals, key)[code] for d in week.days) == value


@pytest.mark.parametrize("reports,expenses", [(False, False), (True, False), (False, True)])
async def test_empty_and_single_category(app, reports, expenses):
    tid = await seed(
        app.state.session_factory,
        START,
        reports=None if reports else [],
        expenses=None if expenses else [],
    )
    week = await calculate(app, tid)
    assert week.totals.gross_total == Decimal("1793.16" if reports else "0.00")
    assert week.totals.expense_total == Decimal("150.82" if expenses else "0.00")
    assert len(week.days) == 7


@pytest.mark.parametrize(
    "selected,start",
    [
        ("2026-01-01", "2025-12-29"),
        ("2024-02-29", "2024-02-26"),
        ("2026-03-08", "2026-03-02"),
        ("2026-11-01", "2026-10-26"),
        ("2026-09-20", "2026-09-14"),
        ("2026-09-21", "2026-09-21"),
    ],
)
def test_week_geometry(selected, start):
    assert domain.monday(date.fromisoformat(selected)) == date.fromisoformat(start)


@pytest.mark.parametrize(
    "zone,expected",
    [("America/Los_Angeles", "2026-09-20"), ("Asia/Tokyo", "2026-09-21"), (None, None)],
)
def test_today_uses_technician_zone(zone, expected):
    actual = domain.local_today(datetime(2026, 9, 21, 1, tzinfo=UTC), zone)
    assert (str(actual) if actual else None) == expected


@pytest.mark.parametrize(
    "instant",
    [
        "2026-03-08T09:59:59+00:00",
        "2026-03-08T10:00:00+00:00",
        "2026-11-01T08:59:59+00:00",
        "2026-11-01T09:00:00+00:00",
    ],
)
async def test_dst_against_postgres(app, instant):
    value = datetime.fromisoformat(instant)
    async with app.state.session_factory() as db:
        oracle = await db.scalar(
            text("SELECT (CAST(:v AS timestamptz) AT TIME ZONE 'America/Los_Angeles')::date"),
            {"v": value},
        )
    assert domain.local_today(value, "America/Los_Angeles") == oracle


async def test_missing_zone_history_inactive_and_zone_change(app, client, accounting):
    before = await calculate(app, accounting)
    async with app.state.session_factory() as db, db.begin():
        await db.execute(
            update(Technician)
            .where(Technician.id == accounting)
            .values(accounting_timezone=None, status="INACTIVE")
        )
    result = await client.get(f"/api/technicians/{accounting}/accounting/current")
    assert result.status_code == 200 and result.json()["setup_required"]
    assert result.json()["today"] is None and result.json()["weekly"] is None
    assert (await client.get(f"/api/technicians/{accounting}/accounting/daily")).status_code == 409
    history = await calculate(app, accounting)
    assert history.setup_required and history.totals == before.totals
    async with app.state.session_factory() as db, db.begin():
        await db.execute(
            update(Technician)
            .where(Technician.id == accounting)
            .values(accounting_timezone="Asia/Tokyo")
        )
    assert (await calculate(app, accounting)).totals == before.totals


@pytest.mark.parametrize(
    "suffix",
    [
        "daily?date=no",
        "daily?date=0",
        "daily?date=2026-09-14T00:00:00",
        "weekly?week_start=0",
        "daily?date=2026-02-30",
        "weekly?week_start=2026-09-15",
        "weekly?week_start=9999-12-27",
        "daily?from=1900-01-01&to=2200-01-01",
        "weekly?limit=999999",
        "current?date=2026-01-01",
    ],
)
async def test_bounded_parameters(client, accounting, suffix):
    assert (
        await client.get(f"/api/technicians/{accounting}/accounting/{suffix}")
    ).status_code == 422


@pytest.mark.parametrize("endpoint", ["daily", "weekly", "current"])
async def test_authorization(anonymous, accounting, endpoint):
    result = await anonymous.get(
        f"/api/technicians/{accounting}/accounting/{endpoint}",
        headers={"Authorization": "Bearer " + "a" * 43},
    )
    assert result.status_code == 401 and result.headers["cache-control"] == "no-store"


async def test_api_privacy_serialization_and_no_audit(app, client, accounting, caplog):
    async with app.state.session_factory() as db:
        count = await db.scalar(text("SELECT count(*) FROM audit_events"))
    response = await client.get(
        f"/api/technicians/{accounting}/accounting/weekly?week_start={START}"
    )
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert response.json()["totals"]["gross_total"] == "1793.16"
    assert "synthetic report" not in caplog.text and "synthetic expense" not in caplog.text
    async with app.state.session_factory() as db:
        assert await db.scalar(text("SELECT count(*) FROM audit_events")) == count
    assert (await client.get("/api/technicians/invalid/accounting/current")).status_code == 422
    assert (await client.get(f"/api/technicians/{uuid4()}/accounting/current")).status_code == 404


@pytest.mark.parametrize("amount", ["0.01", "9999999999.99"])
async def test_many_exact_amounts_and_identical_expenses(app, amount):
    reports = [dict(day=0, amount=amount, payment_method="CASH") for _ in range(101)]
    expenses = [dict(day=0, amount="20.01")] * 2 + [dict(day=0, amount="0.00")]
    tid = await seed(app.state.session_factory, START, reports=reports, expenses=expenses)
    result = await calculate(app, tid, "daily")
    assert result.totals.gross_total == Decimal(amount) * 101
    assert result.totals.expense_total == Decimal("40.02")
    assert result.totals.expense_count == 3


@pytest.mark.parametrize("payment", ["ESTIMATE", "CANCEL"])
async def test_corrupt_zero_outcome_fails(app, accounting, payment):
    week = await calculate(app, accounting)
    source = week.days[0].reports[0].model_dump()
    source["payment_method"] = payment
    source["amount"] = Decimal("100.01")
    with pytest.raises(ValidationError):
        domain.ReportFact(**source)


@pytest.mark.parametrize(
    "parent,revision,fk",
    [
        (WorkReport, WorkReportRevision, "report_id"),
        (TechnicianExpense, ExpenseRevision, "expense_id"),
    ],
)
async def test_corrupt_current_pointer_fails_conservatively(app, accounting, parent, revision, fk):
    async with app.state.session_factory() as db, db.begin():
        # Deliberate corruption is isolated and rolled back; no persisted disabled guard.
        await db.execute(text("SET LOCAL session_replication_role = replica"))
        identifier = await db.scalar(
            select(parent.id).where(parent.technician_id == accounting).limit(1)
        )
        await db.execute(
            update(parent).where(parent.id == identifier).values(current_revision_number=999)
        )
        # Fresh snapshot in this transaction is not allowed: exercise the same fact reader.
        with pytest.raises(ValueError, match="Missing current"):
            await service.facts(db, accounting, START, START + timedelta(days=6))
        await db.rollback()


async def test_consistent_snapshot_concurrent_insert(app, accounting, monkeypatch):
    original = service.facts

    async def interleaved(db, tid, start, end):
        assert await db.scalar(text("SHOW transaction_isolation")) == "repeatable read"
        assert await db.scalar(text("SHOW transaction_read_only")) == "on"
        await asyncio.wait_for(
            seed(
                app.state.session_factory,
                START,
                technician_id=tid,
                reports=[dict(day=0, amount="1.00", payment_method="CASH")],
                expenses=[dict(day=0, amount="2.00")],
            ),
            5,
        )
        return await original(db, tid, start, end)

    monkeypatch.setattr(service, "facts", interleaved)
    result = await calculate(app, accounting)
    assert result.totals.model_dump(mode="json") == GOLDEN["weekly"]
    monkeypatch.setattr(service, "facts", original)
    after = await calculate(app, accounting)
    assert after.totals.gross_total == Decimal("1794.16") and after.totals.expense_total == Decimal(
        "152.82"
    )


async def test_consistent_snapshot_future_correction(app, accounting, monkeypatch):
    original = service.facts

    async def interleaved(db, tid, start, end):
        async with app.state.session_factory() as writer, writer.begin():
            identifier = await writer.scalar(
                select(WorkReport.id)
                .where(WorkReport.technician_id == tid, WorkReport.current_revision_number == 1)
                .limit(1)
            )
            # Test-only future correction, transactional bypass restores automatically.
            await writer.execute(text("SET LOCAL session_replication_role = replica"))
            await writer.execute(
                text(
                    """INSERT INTO work_report_revisions SELECT
                    (jsonb_populate_record(NULL::work_report_revisions,
                    to_jsonb(r) || jsonb_build_object('id',gen_random_uuid(),
                    'revision_number',2,'amount_closed',999.99))).*
                    FROM work_report_revisions r WHERE report_id=:id AND revision_number=1"""
                ),
                {"id": identifier},
            )
            await writer.execute(
                update(WorkReport)
                .where(WorkReport.id == identifier)
                .values(current_revision_number=2)
            )
        return await original(db, tid, start, end)

    monkeypatch.setattr(service, "facts", interleaved)
    result = await calculate(app, accounting)
    assert result.totals.model_dump(mode="json") == GOLDEN["weekly"]
    monkeypatch.setattr(service, "facts", original)
    after = await calculate(app, accounting)
    assert after.totals.report_count == 11 and after.totals.gross_total != result.totals.gross_total
    assert sum(r.amount for d in after.days for r in d.reports) == after.totals.gross_total


@pytest.mark.parametrize("size", [10, 100, 1000])
async def test_query_budget_benchmark(app, size, record_property):
    rows = [
        dict(
            day=i % 7,
            amount="0.01",
            previous_amount="999.99",
            revision_number=2,
            payment_method="CASH",
        )
        for i in range(size)
    ]
    costs = [
        dict(day=i % 7, amount="0.01", previous_amount="888.88", revision_number=2)
        for i in range(size)
    ]
    tid = await seed(app.state.session_factory, START, reports=rows, expenses=costs)
    statements = []

    def track(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(app.state.engine.sync_engine, "before_cursor_execute", track)
    try:
        for kind in ["daily", "weekly"]:
            times = []
            for _ in range(3):
                statements.clear()
                started = time.perf_counter()
                result = await calculate(app, tid, kind)
                times.append((time.perf_counter() - started) * 1000)
                assert len(statements) == 4  # isolation + context/clock + reports + expenses
                assert result.totals.report_count == (size if kind == "weekly" else (size + 6) // 7)
            record_property(
                f"{kind}_{size}",
                json.dumps(
                    dict(queries=4, median_ms=statistics.median(times), worst_ms=max(times))
                ),
            )
            assert max(times) < 5000
    finally:
        event.remove(app.state.engine.sync_engine, "before_cursor_execute", track)
    async with app.state.session_factory() as db:
        query = service.current_statement(
            WorkReport, WorkReportRevision, tid, START, START + timedelta(days=6)
        )
        sql = str(query.compile(dialect=db.bind.dialect, compile_kwargs={"literal_binds": True}))
        plan = "\n".join(await db.scalars(text("EXPLAIN (ANALYZE, BUFFERS) " + sql)))
        record_property(f"plan_{size}", plan)
        # PostgreSQL may correctly prefer a sequential scan for tiny relations.
        # Require the current-revision index only for this benchmark's largest fixture.
        if size == 1000:
            assert "uq_work_report_revision" in plan


async def test_current_complete_not_recent_list(app, monkeypatch):
    tid = await seed(
        app.state.session_factory,
        START,
        reports=[dict(day=0, amount="0.01", payment_method="CASH") for _ in range(125)],
        expenses=[dict(day=0, amount="0.01") for _ in range(125)],
    )
    monkeypatch.setattr(service, "local_today", lambda instant, zone: START)
    result = await calculate(app, tid, "current", None)
    assert result.daily.totals.report_count == 125
    assert result.daily.totals.expense_count == 125
    assert result.daily.totals.gross_total == Decimal("1.25")
    assert result.weekly.totals == result.daily.totals


async def test_stored_report_date_not_submission_date(app, accounting):
    day = await calculate(app, accounting, "daily", START)
    assert len(day.reports) == 2
    assert all(r.submitted_at.date() > r.business_date for r in day.reports)
    assert day.totals.gross_total == Decimal("193.01")


async def test_no_report_from_next_or_previous_week(app, accounting):
    await seed(
        app.state.session_factory,
        START,
        technician_id=accounting,
        reports=[
            dict(day=-1, amount="999.00", payment_method="CASH"),
            dict(day=7, amount="999.00", payment_method="SUPER"),
        ],
        expenses=[dict(day=-1, amount="999.00"), dict(day=7, amount="999.00")],
    )
    assert (await calculate(app, accounting)).totals.model_dump(mode="json") == GOLDEN["weekly"]


@pytest.mark.parametrize("payment", ["ESTIMATE", "CANCEL"])
async def test_bypassed_database_zero_outcome_is_rejected(app, accounting, payment):
    async with app.state.session_factory() as db, db.begin():
        await db.execute(text("SET LOCAL session_replication_role = replica"))
        await db.execute(
            text("""ALTER TABLE work_report_revisions
            DROP CONSTRAINT ck_work_report_revisions_zero_amount""")
        )
        await db.execute(
            text("""UPDATE work_report_revisions SET
            payment_method=:payment, amount_closed=123.45
            WHERE report_id IN (SELECT id FROM work_reports WHERE technician_id=:tid)"""),
            {"payment": payment, "tid": accounting},
        )
        with pytest.raises(ValidationError, match="Invalid zero outcome"):
            await service.facts(db, accounting, START, START + timedelta(days=6))
        # Both DDL and deliberately invalid data roll back together.
        await db.rollback()
    assert (await calculate(app, accounting)).totals.model_dump(mode="json") == GOLDEN["weekly"]


async def test_unexpected_failure_never_logs_financial_content(
    client, accounting, monkeypatch, caplog
):
    async def fail(*args):
        raise RuntimeError("PRIVATE_ACCOUNTING_FAILURE_CANARY")

    monkeypatch.setattr(service, "facts", fail)
    response = await client.get(f"/api/technicians/{accounting}/accounting/daily?date={START}")
    assert response.status_code == 500
    assert response.headers["cache-control"] == "no-store"
    assert "PRIVATE_ACCOUNTING_FAILURE_CANARY" not in caplog.text + response.text
    assert "accounting result=INTERNAL_ERROR" in caplog.text
