import hashlib
import time
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import event, select, text, update
from sqlalchemy.exc import DBAPIError

from hub.accounting import domain, service
from hub.auth.models import Manager
from hub.calendars.models import Calendar
from hub.expenses.models import ExpenseRevision, TechnicianExpense
from hub.technicians.models import Technician
from hub.work_reports.models import WorkReport, WorkReportRevision
from tests.accounting_data import GOLDEN, seed

START = date(2026, 9, 14)
PAYMENTS = ("CASH", "ZELLE", "CHECK", "CREDIT_CARD", "VENMO", "SUPER", "ESTIMATE", "CANCEL")
REVIEWS = ("GOOGLE", "GROUPON", "FACEBOOK")
CLOSERS = ("MYSELF", "CALL_CENTER")
FIXTURE = Path(__file__).parent / "fixtures/accounting_legacy_week.json"


def independent_totals(day, reports, expenses):
    selected_reports = [item for item in reports if item["day"] == day]
    selected_expenses = [item for item in expenses if item["day"] == day]
    payments = {code: Decimal("0.00") for code in PAYMENTS}
    reviews = {code: 0 for code in REVIEWS}
    closers = {code: 0 for code in CLOSERS}
    for item in selected_reports:
        payments[item["payment_method"]] += Decimal(item["amount"])
        for code in REVIEWS:
            reviews[code] += item[code.lower()]
        closers[item["closed_by"]] += 1
    return {
        "gross_total": format(sum(payments.values(), Decimal("0.00")), ".2f"),
        "expense_total": format(
            sum((Decimal(item["amount"]) for item in selected_expenses), Decimal("0.00")),
            ".2f",
        ),
        "report_count": len(selected_reports),
        "expense_count": len(selected_expenses),
        "maintenance_count": sum(item["maintenance"] for item in selected_reports),
        "reviews": reviews,
        "payments": {key: format(value, ".2f") for key, value in payments.items()},
        "closed_by": closers,
    }


def report_fact(amount="0.01", **values):
    return domain.ReportFact(
        id=uuid4(),
        revision_number=1,
        business_date=START,
        sequence=values.get("sequence", 1),
        start_time="09:00",
        end_time="10:00",
        title="Synthetic audit job",
        location="Synthetic audit location",
        comments="",
        amount=Decimal(amount),
        payment_method=values.get("payment_method", "CASH"),
        closed_by=values.get("closed_by", "MYSELF"),
        google_reviews=values.get("google_reviews", 0),
        groupon_reviews=values.get("groupon_reviews", 0),
        facebook_reviews=values.get("facebook_reviews", 0),
        maintenance=values.get("maintenance", False),
        submitted_at=datetime(2026, 9, 14, 12, tzinfo=UTC),
    )


async def calculate(app, technician_id, kind="weekly", selector=START):
    async with app.state.session_factory() as db:
        return await service.calculate(db, technician_id, kind, selector)


def test_static_golden_fixture_has_independent_component_oracle():
    assert hashlib.sha256(FIXTURE.read_bytes()).hexdigest() == (
        "fe63e310648391effa3dd582fbc1f771b6ae7c5d2bf4ca9f085fd70a16ed0789"
    )
    assert [
        (
            item["day"],
            item["legacy_payment"],
            item["payment_method"],
            item["amount"],
            item["google"],
            item["groupon"],
            item["facebook"],
            item["maintenance"],
            item["closed_by"],
            item["revision_number"],
            item["previous_amount"],
        )
        for item in GOLDEN["reports"]
    ] == [
        (0, "CASH", "CASH", "100.01", 3, 1, 2, True, "MYSELF", 1, None),
        (0, "CREDIT_CARD", "CREDIT_CARD", "93.00", 0, 0, 0, False, "CALL_CENTER", 1, None),
        (1, "ZELLE", "ZELLE", "200.02", 1, 0, 0, False, "MYSELF", 1, None),
        (1, "CHECK", "CHECK", "300.03", 0, 2, 0, True, "CALL_CENTER", 1, None),
        (3, "SUPER", "SUPER", "400.04", 0, 0, 3, False, "MYSELF", 1, None),
        (3, "VENMO", "VENMO", "500.05", 0, 0, 0, False, "CALL_CENTER", 1, None),
        (4, "ESTIMATE", "ESTIMATE", "0.00", 1, 0, 0, False, "MYSELF", 1, None),
        (4, "CANCEL", "CANCEL", "0.00", 0, 0, 1, False, "CALL_CENTER", 1, None),
        (6, "CASH", "CASH", "0.01", 0, 0, 0, False, "MYSELF", 1, None),
        (6, "CASH_APP", "CREDIT_CARD", "50.00", 0, 0, 0, False, "MYSELF", 1, None),
        (6, "CASH", "CASH", "150.00", 2, 0, 1, True, "CALL_CENTER", 2, "100.00"),
    ]
    assert [
        (item["day"], item["amount"], item["revision_number"], item["previous_amount"])
        for item in GOLDEN["expenses"]
    ] == [
        (0, "47.23", 1, None),
        (0, "38.59", 1, None),
        (5, "20.00", 1, None),
        (5, "20.00", 1, None),
        (5, "0.00", 1, None),
        (6, "25.00", 2, "40.00"),
    ]
    reconstructed = [
        independent_totals(day, GOLDEN["reports"], GOLDEN["expenses"]) for day in range(7)
    ]
    assert reconstructed == GOLDEN["days"]
    assert reconstructed[0] == {
        "gross_total": "193.01",
        "expense_total": "85.82",
        "report_count": 2,
        "expense_count": 2,
        "maintenance_count": 1,
        "reviews": {"GOOGLE": 3, "GROUPON": 1, "FACEBOOK": 2},
        "payments": {
            "CASH": "100.01",
            "ZELLE": "0.00",
            "CHECK": "0.00",
            "CREDIT_CARD": "93.00",
            "VENMO": "0.00",
            "SUPER": "0.00",
            "ESTIMATE": "0.00",
            "CANCEL": "0.00",
        },
        "closed_by": {"MYSELF": 1, "CALL_CENTER": 1},
    }
    weekly = {
        "gross_total": format(sum(Decimal(day["gross_total"]) for day in reconstructed), ".2f"),
        "expense_total": format(sum(Decimal(day["expense_total"]) for day in reconstructed), ".2f"),
        "report_count": sum(day["report_count"] for day in reconstructed),
        "expense_count": sum(day["expense_count"] for day in reconstructed),
        "maintenance_count": sum(day["maintenance_count"] for day in reconstructed),
        "reviews": {code: sum(day["reviews"][code] for day in reconstructed) for code in REVIEWS},
        "payments": {
            code: format(
                sum((Decimal(day["payments"][code]) for day in reconstructed), Decimal("0.00")),
                ".2f",
            )
            for code in PAYMENTS
        },
        "closed_by": {
            code: sum(day["closed_by"][code] for day in reconstructed) for code in CLOSERS
        },
    }
    assert weekly == GOLDEN["weekly"]


async def test_current_report_revision_replaces_every_business_fact(app):
    technician_id = await seed(
        app.state.session_factory,
        START,
        reports=[
            {
                "day": 1,
                "amount": "125.00",
                "previous_amount": "100.00",
                "payment_method": "CREDIT_CARD",
                "revision_number": 2,
                "facebook": 1,
                "closed_by": "CALL_CENTER",
            }
        ],
        expenses=[{"day": 1, "amount": "25.00", "previous_amount": "40.00", "revision_number": 2}],
    )
    async with app.state.session_factory() as db, db.begin():
        await db.execute(text("SET LOCAL session_replication_role = replica"))
        report_id = await db.scalar(
            select(WorkReport.id).where(WorkReport.technician_id == technician_id)
        )
        await db.execute(
            update(WorkReportRevision)
            .where(
                WorkReportRevision.report_id == report_id,
                WorkReportRevision.revision_number == 1,
            )
            .values(
                operational_date=START,
                payment_method="CASH",
                amount_closed=Decimal("100.00"),
                google_reviews=1,
                facebook_reviews=0,
                yearly_maintenance_plan_provided=True,
                closed_by="MYSELF",
            )
        )
    old_day = await calculate(app, technician_id, "daily", START)
    current_day = await calculate(app, technician_id, "daily", START + timedelta(days=1))
    assert old_day.totals.report_count == 0 and old_day.totals.gross_total == 0
    assert current_day.totals.gross_total == Decimal("125.00")
    assert current_day.totals.payments["CASH"] == 0
    assert current_day.totals.payments["CREDIT_CARD"] == Decimal("125.00")
    assert current_day.totals.reviews == {"GOOGLE": 0, "GROUPON": 0, "FACEBOOK": 1}
    assert current_day.totals.closed_by == {"MYSELF": 0, "CALL_CENTER": 1}
    assert current_day.totals.maintenance_count == 0
    assert current_day.totals.report_count == 1
    assert current_day.totals.expense_total == Decimal("25.00")
    assert current_day.totals.expense_count == 1


async def test_review_aggregate_can_exceed_per_report_limit(app):
    technician_id = await seed(
        app.state.session_factory,
        START,
        reports=[
            {"day": 0, "amount": "0.01", "payment_method": "CASH", "google": 100},
            {"day": 0, "amount": "0.01", "payment_method": "CASH", "google": 100},
        ],
        expenses=[],
    )
    result = await calculate(app, technician_id, "daily")
    assert result.totals.reviews == {"GOOGLE": 200, "GROUPON": 0, "FACEBOOK": 0}


@pytest.mark.parametrize("count,expected", [(10, "0.10"), (100, "1.00"), (10_000, "100.00")])
def test_repeated_cents_are_exact(count, expected):
    reports = tuple(report_fact(sequence=index + 1) for index in range(count))
    assert domain.aggregate(reports, ()).model_dump(mode="json")["gross_total"] == expected


def test_large_aggregate_exceeds_javascript_safe_integer_cents_exactly():
    reports = tuple(report_fact("9999999999.99", sequence=index + 1) for index in range(10_000))
    totals = domain.aggregate(reports, ())
    assert totals.gross_total == Decimal("99999999999900.00")
    assert totals.model_dump(mode="json")["gross_total"] == "99999999999900.00"
    assert int(totals.gross_total * 100) > 2**53 - 1
    with pytest.raises(ValidationError, match="frozen"):
        totals.gross_total = Decimal("0.00")


async def test_ten_thousand_current_facts_with_retained_history(app, record_property):
    technician_id = await seed(app.state.session_factory, START, reports=[], expenses=[])
    async with app.state.session_factory() as db, db.begin():
        calendar_id = await db.scalar(select(Calendar.id).limit(1))
        await db.execute(text("SET LOCAL session_replication_role = replica"))
        await db.execute(
            text(
                """INSERT INTO work_reports
                (id, technician_id, calendar_id, occurrence_key, current_revision_number)
                SELECT ('10000000-0000-4000-8000-' || lpad(gs::text,12,'0'))::uuid,
                       :technician_id, :calendar_id, lpad(gs::text,64,'0'), 2
                FROM generate_series(1,10000) AS gs"""
            ),
            {"technician_id": technician_id, "calendar_id": calendar_id},
        )
        await db.execute(
            text(
                """INSERT INTO work_report_revisions
                (id, report_id, revision_number, technician_name, operational_date,
                 start_time, end_time, sequence, title, location, provider_event_id,
                 recurring_event_id, original_start_time, amount_closed, payment_method,
                 closed_by, comments, yearly_maintenance_plan_provided, google_reviews,
                 groupon_reviews, facebook_reviews, submitted_at)
                SELECT ('20000000-0000-4000-8000-' || lpad(gs::text,12,'0'))::uuid,
                       ('10000000-0000-4000-8000-' || lpad(gs::text,12,'0'))::uuid,
                       1, 'Accounting Synthetic', CAST(:day AS date), '09:00', '10:00', gs,
                       'Historical', 'Synthetic', gs::text, NULL, NULL, 9999999999.99,
                       'SUPER', 'CALL_CENTER', '', true, 100, 100, 100,
                       CAST(:submitted_at AS timestamptz)
                FROM generate_series(1,10000) AS gs
                UNION ALL
                SELECT ('30000000-0000-4000-8000-' || lpad(gs::text,12,'0'))::uuid,
                       ('10000000-0000-4000-8000-' || lpad(gs::text,12,'0'))::uuid,
                       2, 'Accounting Synthetic', CAST(:day AS date), '09:00', '10:00', gs,
                       'Current', 'Synthetic', gs::text, NULL, NULL, 0.01,
                       'CASH', 'MYSELF', '', false, 0, 0, 0,
                       CAST(:submitted_at AS timestamptz)
                FROM generate_series(1,10000) AS gs"""
            ),
            {"day": START, "submitted_at": datetime(2026, 9, 14, 12, tzinfo=UTC)},
        )
        await db.execute(
            text(
                """INSERT INTO technician_expenses
                (id, technician_id, current_revision_number)
                SELECT ('40000000-0000-4000-8000-' || lpad(gs::text,12,'0'))::uuid,
                       :technician_id, 2
                FROM generate_series(1,10000) AS gs"""
            ),
            {"technician_id": technician_id},
        )
        await db.execute(
            text(
                """INSERT INTO expense_revisions
                (id, expense_id, revision_number, technician_name, expense_date,
                 accounting_timezone, expense_type, amount, note, submitted_at)
                SELECT ('50000000-0000-4000-8000-' || lpad(gs::text,12,'0'))::uuid,
                       ('40000000-0000-4000-8000-' || lpad(gs::text,12,'0'))::uuid,
                       1, 'Accounting Synthetic', CAST(:day AS date),
                       'America/Los_Angeles', 'Historical', 9999999999.99, '',
                       CAST(:submitted_at AS timestamptz)
                FROM generate_series(1,10000) AS gs
                UNION ALL
                SELECT ('60000000-0000-4000-8000-' || lpad(gs::text,12,'0'))::uuid,
                       ('40000000-0000-4000-8000-' || lpad(gs::text,12,'0'))::uuid,
                       2, 'Accounting Synthetic', CAST(:day AS date),
                       'America/Los_Angeles', 'Current', 0.01, '',
                       CAST(:submitted_at AS timestamptz)
                FROM generate_series(1,10000) AS gs"""
            ),
            {"day": START, "submitted_at": datetime(2026, 9, 14, 12, tzinfo=UTC)},
        )
    statements = []

    def track(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(app.state.engine.sync_engine, "before_cursor_execute", track)
    try:
        started = time.perf_counter()
        result = await calculate(app, technician_id)
        elapsed_ms = (time.perf_counter() - started) * 1000
    finally:
        event.remove(app.state.engine.sync_engine, "before_cursor_execute", track)
    record_property("accounting_10000_current_with_history_ms", str(round(elapsed_ms, 2)))
    assert len(statements) == 4
    assert result.totals.report_count == 10_000
    assert result.totals.gross_total == Decimal("100.00")
    assert result.totals.expense_count == 10_000
    assert result.totals.expense_total == Decimal("100.00")
    assert result.totals.payments["SUPER"] == 0
    assert result.totals.reviews == {"GOOGLE": 0, "GROUPON": 0, "FACEBOOK": 0}
    assert elapsed_ms < 5000
    async with app.state.session_factory() as db:
        report_query = service.current_statement(
            WorkReport, WorkReportRevision, technician_id, START, START + timedelta(days=6)
        )
        expense_query = service.current_statement(
            TechnicianExpense,
            ExpenseRevision,
            technician_id,
            START,
            START + timedelta(days=6),
        )
        report_sql = str(
            report_query.compile(dialect=db.bind.dialect, compile_kwargs={"literal_binds": True})
        )
        expense_sql = str(
            expense_query.compile(dialect=db.bind.dialect, compile_kwargs={"literal_binds": True})
        )
        report_plan = "\n".join(await db.scalars(text("EXPLAIN (ANALYZE, BUFFERS) " + report_sql)))
        expense_plan = "\n".join(
            await db.scalars(text("EXPLAIN (ANALYZE, BUFFERS) " + expense_sql))
        )
    assert "uq_work_report_revision" in report_plan
    assert "uq_expense_revision" in expense_plan


async def test_query_budget_is_constant_with_one_thousand_historical_revisions(app):
    technician_id = await seed(app.state.session_factory, START, reports=[], expenses=[])
    async with app.state.session_factory() as db, db.begin():
        calendar_id = await db.scalar(select(Calendar.id).limit(1))
        await db.execute(text("SET LOCAL session_replication_role = replica"))
        parameters = {
            "technician_id": technician_id,
            "calendar_id": calendar_id,
            "day": START,
            "submitted_at": datetime(2026, 9, 14, 12, tzinfo=UTC),
        }
        await db.execute(
            text(
                """INSERT INTO work_reports
                (id, technician_id, calendar_id, occurrence_key, current_revision_number)
                VALUES ('70000000-0000-4000-8000-000000000001', :technician_id,
                        :calendar_id, repeat('7',64), 1001)"""
            ),
            parameters,
        )
        await db.execute(
            text(
                """INSERT INTO work_report_revisions
                (id, report_id, revision_number, technician_name, operational_date,
                 start_time, end_time, sequence, title, location, provider_event_id,
                 amount_closed, payment_method, closed_by, comments,
                 yearly_maintenance_plan_provided, google_reviews, groupon_reviews,
                 facebook_reviews, submitted_at)
                SELECT ('70000001-0000-4000-8000-' || lpad(gs::text,12,'0'))::uuid,
                       '70000000-0000-4000-8000-000000000001', gs,
                       'Accounting Synthetic', CAST(:day AS date), '09:00', '10:00', 1,
                       'Synthetic', 'Synthetic', gs::text,
                       CASE WHEN gs=1001 THEN 0.01 ELSE 9999999999.99 END,
                       CASE WHEN gs=1001 THEN 'CASH' ELSE 'SUPER' END,
                       'MYSELF', '', false, CASE WHEN gs=1001 THEN 0 ELSE 100 END,
                       0, 0, CAST(:submitted_at AS timestamptz)
                FROM generate_series(1,1001) AS gs"""
            ),
            parameters,
        )
        await db.execute(
            text(
                """INSERT INTO technician_expenses
                (id, technician_id, current_revision_number)
                VALUES ('80000000-0000-4000-8000-000000000001', :technician_id, 1001)"""
            ),
            parameters,
        )
        await db.execute(
            text(
                """INSERT INTO expense_revisions
                (id, expense_id, revision_number, technician_name, expense_date,
                 accounting_timezone, expense_type, amount, note, submitted_at)
                SELECT ('80000001-0000-4000-8000-' || lpad(gs::text,12,'0'))::uuid,
                       '80000000-0000-4000-8000-000000000001', gs,
                       'Accounting Synthetic', CAST(:day AS date),
                       'America/Los_Angeles', 'Synthetic',
                       CASE WHEN gs=1001 THEN 0.01 ELSE 9999999999.99 END,
                       '', CAST(:submitted_at AS timestamptz)
                FROM generate_series(1,1001) AS gs"""
            ),
            parameters,
        )
    statements = []

    def track(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(app.state.engine.sync_engine, "before_cursor_execute", track)
    try:
        result = await calculate(app, technician_id)
    finally:
        event.remove(app.state.engine.sync_engine, "before_cursor_execute", track)
    assert len(statements) == 4
    assert result.totals.report_count == 1
    assert result.totals.expense_count == 1
    assert result.totals.gross_total == Decimal("0.01")
    assert result.totals.expense_total == Decimal("0.01")


@pytest.mark.parametrize("offset", range(7))
async def test_weekly_api_accepts_only_monday(client, app, offset):
    technician_id = await seed(app.state.session_factory, START, reports=[], expenses=[])
    selected = START + timedelta(days=offset)
    response = await client.get(
        f"/api/technicians/{technician_id}/accounting/weekly?week_start={selected}"
    )
    assert response.status_code == (200 if offset == 0 else 422)


@pytest.mark.parametrize(
    "suffix",
    [
        "daily?date=2026-09-14&date=2026-09-15",
        "weekly?week_start=2026-09-14&week_start=2026-09-21",
        "daily?date=",
        "weekly?week_start=",
        "daily?date=America%2FLos_Angeles",
        "weekly?week_start=America%2FLos_Angeles",
        "daily?date=" + "9" * 10_000,
    ],
)
async def test_duplicate_and_oversized_selectors_are_rejected(client, app, suffix):
    technician_id = await seed(app.state.session_factory, START, reports=[], expenses=[])
    response = await client.get(f"/api/technicians/{technician_id}/accounting/{suffix}")
    assert response.status_code == 422
    assert response.headers["cache-control"] == "no-store"


async def test_inactive_manager_session_cannot_read_accounting(app, client, credentials):
    technician_id = await seed(app.state.session_factory, START, reports=[], expenses=[])
    async with app.state.session_factory() as db, db.begin():
        await db.execute(
            update(Manager).where(Manager.id == credentials["id"]).values(is_active=False)
        )
    response = await client.get(f"/api/technicians/{technician_id}/accounting/current")
    assert response.status_code == 401
    assert response.headers["cache-control"] == "no-store"


async def test_accounting_snapshot_is_database_enforced_read_only(app):
    technician_id = await seed(app.state.session_factory, START, reports=[], expenses=[])
    async with app.state.session_factory() as db:
        await service.calculate(db, technician_id, "daily", START)
        assert await db.scalar(text("SHOW transaction_isolation")) == "repeatable read"
        assert await db.scalar(text("SHOW transaction_read_only")) == "on"
        with pytest.raises(DBAPIError) as failure:
            await db.execute(
                update(Technician)
                .where(Technician.id == technician_id)
                .values(first_name="Forbidden")
            )
        assert getattr(failure.value.orig, "sqlstate", None) == "25006"
        await db.rollback()


def test_timezone_midnight_and_week_boundary_are_per_technician():
    instant = datetime(2026, 9, 21, 6, 30, tzinfo=UTC)
    new_york = domain.local_today(instant, "America/New_York")
    los_angeles = domain.local_today(instant, "America/Los_Angeles")
    assert (new_york, los_angeles) == (date(2026, 9, 21), date(2026, 9, 20))
    assert domain.monday(new_york) == date(2026, 9, 21)
    assert domain.monday(los_angeles) == date(2026, 9, 14)


def test_accounting_sources_have_no_float_or_invented_financial_metric():
    root = Path(__file__).resolve().parents[2]
    sources = [
        root / "api/hub/accounting/domain.py",
        root / "api/hub/accounting/service.py",
        root / "api/hub/accounting/router.py",
        root / "web/src/components/accounting.tsx",
    ]
    content = "\n".join(path.read_text(encoding="utf-8") for path in sources)
    for forbidden in (
        "float(",
        "parseFloat(",
        "Number(",
        "toFixed(",
        "Math.round",
        ">Net<",
        ">Profit<",
        ">Payout<",
        "Take Home",
        "Technician Pay",
        ">Margin<",
    ):
        assert forbidden not in content
