"""Independent Stage 5 adversarial probes; isolated PostgreSQL and fake providers."""

import asyncio
import logging
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError

from hub.audit.models import AuditEvent
from hub.auth.models import Manager, ManagerSession
from hub.auth.security import now
from hub.integrations.models import TelegramBinding
from hub.technicians.models import Technician
from hub.work_reports import service
from hub.work_reports.models import TechnicianFormSession, WorkReport, WorkReportRevision
from hub.work_reports.schemas import ReportInput
from tests.test_calendar_events import assigned as assigned
from tests.test_google_calendar import google as google
from tests.test_work_reports import BASE, PAYLOAD, counts, issue, opened, selected
from tests.test_work_reports import ready as ready


async def test_copied_bearer_is_transferable_without_manager_or_telegram_browser_identity(
    app, client, ready
):
    _, headers, _ = await selected(app, client)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://127.0.0.1:3000",
        headers={**headers, "Origin": "http://127.0.0.1:3000", "X-Hub-Request": "1"},
    ) as unrelated:
        assert not unrelated.cookies
        assert (await unrelated.post(BASE + "/submit", json=PAYLOAD)).status_code == 200
        assert (await unrelated.get(f"/api/technicians/{ready}/work-reports")).status_code == 401
    assert await counts(app) == (1, 1)


@pytest.mark.parametrize("skew", [-86400, 86400])
async def test_expiry_uses_database_not_worker_process_clock(app, client, ready, monkeypatch, skew):
    token, _, _ = await selected(app, client)
    wall = now()
    monkeypatch.setattr(service, "now", lambda: wall + timedelta(seconds=skew), raising=False)
    # A valid DB deadline stays valid despite an incorrect API process clock.
    async with app.state.session_factory() as db, db.begin():
        await service.authorize(db, token)
    async with app.state.session_factory() as db, db.begin():
        await db.execute(
            update(TechnicianFormSession).values(
                created_at=wall - timedelta(hours=1), expires_at=wall - timedelta(seconds=1)
            )
        )
    with pytest.raises(HTTPException):
        await service.submit(app.state.session_factory, token, ReportInput(**PAYLOAD))
    assert await counts(app) == (0, 0)


async def test_expiry_during_actual_database_lock_wait(app, client, ready):
    token, _, _ = await selected(app, client)
    async with app.state.session_factory() as owner, owner.begin():
        await owner.execute(select(Technician).where(Technician.id == ready).with_for_update())
        await owner.execute(
            text(
                "UPDATE technician_form_sessions SET created_at=clock_timestamp()"
                "-interval '1 hour', expires_at=clock_timestamp()+interval '0.4 second'"
            )
        )
        pending = asyncio.create_task(
            service.submit(app.state.session_factory, token, ReportInput(**PAYLOAD))
        )
        await asyncio.sleep(0.1)
        assert not pending.done()
        await owner.execute(text("SELECT pg_sleep(0.5)"))
    with pytest.raises(HTTPException):
        await pending
    assert await counts(app) == (0, 0)


@pytest.mark.parametrize("different_sessions", [False, True])
@pytest.mark.parametrize("different_payloads", [False, True])
async def test_fifty_way_canonical_and_conflicting_retries(
    app, client, ready, different_sessions, different_payloads
):
    first, _, _ = await selected(app, client)
    second = (await selected(app, client))[0] if different_sessions else first
    payloads = [
        ReportInput(
            **{
                **PAYLOAD,
                "payment_method": "CASH_APP" if i % 2 else "CREDIT_CARD",
                "amount_closed": "1.00" if different_payloads and i % 2 else "850.10",
            }
        )
        for i in range(50)
    ]
    results = await asyncio.gather(
        *(
            service.submit(app.state.session_factory, first if i % 2 else second, p)
            for i, p in enumerate(payloads)
        ),
        return_exceptions=True,
    )
    winners = [r for r in results if not isinstance(r, Exception)]
    assert winners and len({r.report_id for r in winners}) == 1
    assert all(
        not isinstance(r, Exception) or isinstance(r, HTTPException) and r.status_code == 409
        for r in results
    )
    assert await counts(app) == (1, 1)
    async with app.state.session_factory() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "work_report.submitted")
            )
            == 1
        )
        revision = await db.scalar(select(WorkReportRevision))
        assert revision.payment_method == "CREDIT_CARD"


@pytest.mark.parametrize("value", ["0", "0.00", "1", "1.1", "1.10", "9999999999.99"])
def test_exact_money_boundaries(value):
    result = ReportInput(**{**PAYLOAD, "amount_closed": value})
    assert result.amount_closed == Decimal(value) and isinstance(result.amount_closed, Decimal)


def test_money_conversion_never_passes_through_binary_float(monkeypatch):
    from hub.work_reports import schemas

    class DecimalOnly(Decimal):
        def __new__(cls, value="0", *args, **kwargs):
            assert not isinstance(value, float), "Binary float entered financial conversion"
            return super().__new__(cls, value, *args, **kwargs)

    monkeypatch.setattr(schemas, "Decimal", DecimalOnly)
    assert ReportInput(**PAYLOAD).amount_closed == Decimal("850.10")


@pytest.mark.parametrize(
    "value", ["1,000", " 1", "1 ", "1e3", "10000000000.00", "-0.01", "١", 0, 1.1]
)
def test_money_rejected_without_coercion(value):
    with pytest.raises(ValidationError):
        ReportInput(**{**PAYLOAD, "amount_closed": value})


@pytest.mark.parametrize("platform", ["GOOGLE", "GROUPON", "FACEBOOK"])
@pytest.mark.parametrize("value", [0, 1, 100, 101, -1, 1.5, "1", 10**100, True])
def test_review_strict_counts(platform, value):
    payload = {**PAYLOAD, "reviews": {**PAYLOAD["reviews"], platform: value}}
    if type(value) is int and 0 <= value <= 100:
        assert getattr(ReportInput(**payload).reviews, platform) == value
    else:
        with pytest.raises(ValidationError):
            ReportInput(**payload)


@pytest.mark.parametrize("value", ["true", "false", "yes", 1, 0, None, [], {}])
def test_maintenance_no_coercion(value):
    with pytest.raises(ValidationError):
        ReportInput(**{**PAYLOAD, "yearly_maintenance_plan_provided": value})


@pytest.mark.parametrize(
    "field",
    [
        "technician_id",
        "calendar_id",
        "provider_event_id",
        "event_id",
        "occurrence_key",
        "operational_date",
        "title",
        "location",
        "start_time",
        "end_time",
    ],
)
async def test_all_server_facts_reject_client_override(app, client, ready, field):
    _, headers, _ = await selected(app, client)
    response = await client.post(
        BASE + "/submit", headers=headers, json={**PAYLOAD, field: "spoof"}
    )
    assert response.status_code == 422
    assert await counts(app) == (0, 0)


@pytest.mark.parametrize(
    "column,value", [("private_generation", 2), ("telegram_user_id", 777), ("bot_id", 999)]
)
async def test_each_actor_binding_dimension(app, client, ready, column, value):
    token, _, _ = await selected(app, client)
    async with app.state.session_factory() as db, db.begin():
        await db.execute(
            update(TelegramBinding)
            .where(TelegramBinding.technician_id == ready)
            .values({column: value})
        )
    with pytest.raises(HTTPException):
        await service.submit(app.state.session_factory, token, ReportInput(**PAYLOAD))


@pytest.mark.parametrize("state", ["anonymous", "expired", "inactive"])
async def test_manager_list_and_detail_authorization(app, client, ready, state):
    token, _, _ = await selected(app, client)
    result = await service.submit(app.state.session_factory, token, ReportInput(**PAYLOAD))
    async with app.state.session_factory() as db, db.begin():
        if state == "expired":
            await db.execute(update(ManagerSession).values(expires_at=now() - timedelta(seconds=1)))
        if state == "inactive":
            await db.execute(update(Manager).values(is_active=False))
    if state == "anonymous":
        client.cookies.clear()
    for path in (f"/api/technicians/{ready}/work-reports", f"/api/work-reports/{result.report_id}"):
        assert (
            await client.get(path, headers={"Authorization": f"Bearer {token}"})
        ).status_code == 401


async def test_fifty_mb_body_rejected_before_domain(app, client, ready, monkeypatch):
    async def forbidden(*args):
        pytest.fail("Oversized request reached the domain service")

    monkeypatch.setattr(service, "submit", forbidden)
    response = await client.post(BASE + "/submit", content=b"x" * (50 * 1024 * 1024))
    assert response.status_code == 413
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"


async def revision_fixture(app, client, current=2, numbers=(1, 2)):
    token, _, _ = await selected(app, client)
    receipt = await service.submit(app.state.session_factory, token, ReportInput(**PAYLOAD))
    async with app.state.session_factory() as db:
        original = await db.get(WorkReport, receipt.report_id)
        revision = await db.scalar(select(WorkReportRevision))
        values = {c.name: getattr(revision, c.name) for c in WorkReportRevision.__table__.columns}
    identifier = uuid4()
    async with app.state.session_factory() as db, db.begin():
        db.add(
            WorkReport(
                id=identifier,
                technician_id=original.technician_id,
                calendar_id=original.calendar_id,
                occurrence_key=service.digest(str(identifier)),
                current_revision_number=current,
            )
        )
        await db.flush()
        for number in numbers:
            db.add(
                WorkReportRevision(
                    **{
                        **values,
                        "id": uuid4(),
                        "report_id": identifier,
                        "revision_number": number,
                        "amount_closed": Decimal(number),
                    }
                )
            )
    return identifier


async def test_latest_selector_uses_only_pointer(app, client, ready):
    identifier = await revision_fixture(app, client)
    response = await client.get(f"/api/work-reports/{identifier}")
    assert response.json()["revision_number"] == 2 and response.json()["amount_closed"] == "2.00"
    reports = (await client.get(f"/api/technicians/{ready}/work-reports")).json()["reports"]
    assert len([r for r in reports if r["id"] == str(identifier)]) == 1


@pytest.mark.parametrize("current,numbers", [(3, (1, 3)), (1, (1, 2))])
async def test_no_revision_gaps_or_unpointed_future(app, client, ready, current, numbers):
    with pytest.raises(IntegrityError):
        await revision_fixture(app, client, current, numbers)


async def test_open_session_cannot_contain_partial_submission(app, ready):
    await issue(app)
    with pytest.raises(IntegrityError):
        async with app.state.session_factory() as db, db.begin():
            await db.execute(update(TechnicianFormSession).values(submitted_at=now()))


async def test_response_loss_durable_audit_and_history_privacy(app, client, ready, caplog):
    caplog.set_level(logging.INFO)
    token, headers, _ = await selected(app, client)
    await service.submit(app.state.session_factory, token, ReportInput(**PAYLOAD))  # receipt lost
    retry = await client.post(BASE + "/submit", headers=headers, json=PAYLOAD)
    assert retry.status_code == 200
    assert (
        await client.post(
            BASE + "/submit", headers=headers, json={**PAYLOAD, "comments": "changed"}
        )
    ).status_code == 409
    async with app.state.session_factory() as db, db.begin():
        await db.execute(
            update(Technician).where(Technician.id == ready).values(first_name="Renamed")
        )
        await db.execute(
            update(TelegramBinding)
            .where(TelegramBinding.technician_id == ready)
            .values(private_generation=2)
        )
        events = (
            await db.scalars(select(AuditEvent).where(AuditEvent.action == "work_report.submitted"))
        ).all()
        assert (
            len(events) == 1 and events[0].actor_kind == "TECHNICIAN" and events[0].actor_id is None
        )
        assert events[0].target_id == (await db.scalar(select(WorkReport.id)))
        assert all(
            x not in str(events[0].__dict__)
            for x in (token, "PRIVATE_NOTES", "ADDRESS_CANARY", "850.10")
        )
    report = (await client.get(f"/api/work-reports/{retry.json()['report_id']}")).json()
    assert "Renamed" not in report["technician_name"]
    assert all(x not in caplog.text for x in (token, "PRIVATE_NOTES", "ADDRESS_CANARY"))
    assert token not in str(report) and service.digest(token) not in str(report)
    assert await counts(app) == (1, 1)


@pytest.mark.parametrize(
    "error", ["PROVIDER_TEMPORARY_ERROR", "RATE_LIMITED", "CONNECTION_UNAVAILABLE"]
)
async def test_selected_job_has_no_provider_dependency(app, client, ready, google, error):
    from hub.google_calendar.types import ProviderError

    _, headers, form = await selected(app, client)
    google.error = ProviderError(error)
    calls = len(google.calls)
    result = await client.post(BASE + "/submit", headers=headers, json=PAYLOAD)
    assert result.status_code == 200
    google.events = []
    report = (await client.get(f"/api/work-reports/{result.json()['report_id']}")).json()
    assert report["title"] == form["jobs"][0]["title"]
    assert report["location"] == form["jobs"][0]["location"]
    assert len(google.calls) == calls


async def test_assignment_removed_before_selection_rejects_stale_choice(app, client, ready):
    _, headers, form = await opened(app, client)
    assert (await client.delete(f"/api/technicians/{ready}/calendar")).status_code == 204
    assert (
        await client.post(
            BASE + "/select", headers=headers, json={"choice_id": form["jobs"][0]["choice_id"]}
        )
    ).status_code == 409
    assert await counts(app) == (0, 0)


@pytest.mark.parametrize("day", ["2026-09-30", "2026-12-31", "2026-03-08", "2026-11-01"])
async def test_selected_operational_date_survives_midnight_month_year_dst(
    app, client, ready, google, monkeypatch, day
):
    from datetime import UTC, date, datetime
    from zoneinfo import ZoneInfo

    from hub.calendar_events import service as schedule
    from tests.test_calendar_events import item

    selected_day = date.fromisoformat(day)
    monkeypatch.setattr(
        schedule,
        "now",
        lambda: datetime.combine(selected_day, datetime.min.time(), UTC) + timedelta(hours=16),
    )
    local_start = datetime.combine(
        selected_day, datetime.min.time(), ZoneInfo("America/New_York")
    ) + timedelta(hours=8)
    google.events = [
        item(
            day=selected_day,
            start={"dateTime": local_start.isoformat()},
            end={"dateTime": (local_start + timedelta(hours=2)).isoformat()},
        )
    ]
    _, headers, form = await selected(app, client)
    # Simulate a five-minute midnight crossing against the session's DB deadline.
    issued = datetime.combine(selected_day, datetime.min.time(), UTC) + timedelta(
        hours=23, minutes=58
    )
    async with app.state.session_factory() as db, db.begin():
        await db.execute(
            update(TechnicianFormSession).values(
                created_at=issued, expires_at=issued + timedelta(minutes=15)
            )
        )

    async def after_midnight(db):
        return issued + timedelta(minutes=5)

    monkeypatch.setattr(service, "database_now", after_midnight)
    result = await client.post(BASE + "/submit", headers=headers, json=PAYLOAD)
    assert result.status_code == 200
    report = (await client.get(f"/api/work-reports/{result.json()['report_id']}")).json()
    assert report["operational_date"] == day == form["jobs"][0]["operational_date"]


async def test_thousand_issued_sessions_bound_open_but_retain_metadata(app, ready):
    for _ in range(1000):
        assert await issue(app)
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
        assert (
            await db.scalar(
                select(func.count())
                .select_from(TechnicianFormSession)
                .where(TechnicianFormSession.choices.is_not(None))
            )
            == 0
        )
    # Admission/metadata retention debt is real: bounding active forms is not a purge.


async def test_invalid_capability_spam_cannot_create_business_records(app, client, ready):
    for _ in range(1000):
        async with app.state.session_factory() as db, db.begin():
            with pytest.raises(HTTPException):
                await service.authorize(db, "z" * 43)
    assert await counts(app) == (0, 0)


async def test_manager_scaling_bounded_query_count(app, client, ready):
    from time import perf_counter

    from sqlalchemy import event

    token, _, _ = await selected(app, client)
    receipt = await service.submit(app.state.session_factory, token, ReportInput(**PAYLOAD))
    async with app.state.session_factory() as db:
        original = await db.get(WorkReport, receipt.report_id)
        revision = await db.scalar(select(WorkReportRevision))
        values = {c.name: getattr(revision, c.name) for c in WorkReportRevision.__table__.columns}
    previous = 1
    for size in (10, 100, 1000, 10000):
        async with app.state.session_factory() as db, db.begin():
            report_rows, revision_rows = [], []
            for _ in range(previous, size):
                identifier = uuid4()
                report_rows.append(
                    dict(
                        id=identifier,
                        technician_id=ready,
                        calendar_id=original.calendar_id,
                        occurrence_key=service.digest(str(identifier)),
                    )
                )
                revision_rows.append({**values, "id": uuid4(), "report_id": identifier})
            await db.execute(WorkReport.__table__.insert(), report_rows)
            await db.execute(WorkReportRevision.__table__.insert(), revision_rows)
        queries = []

        def counted(*args, queries=queries):
            queries.append(1)

        event.listen(app.state.engine.sync_engine, "before_cursor_execute", counted)
        started = perf_counter()
        try:
            response = await client.get(f"/api/technicians/{ready}/work-reports")
        finally:
            event.remove(app.state.engine.sync_engine, "before_cursor_execute", counted)
        elapsed = (perf_counter() - started) * 1000
        assert response.status_code == 200 and len(response.json()["reports"]) == min(20, size)
        assert len(queries) <= 7
        print(f"REPORT_READ rows={size} queries={len(queries)} milliseconds={elapsed:.2f}")
        previous = size


async def test_form_response_never_returns_raw_capability(app, client, ready):
    token, headers, form = await selected(app, client)
    assert token not in str(form) and service.digest(token) not in str(form)
    assert "capability" not in form and "token" not in form
    # A manager cookie cannot substitute for a bearer even when a form exists.
    assert (await client.post(BASE)).status_code == 410
    assert (await client.post(BASE + "/submit", json=PAYLOAD)).status_code == 410
    assert (await client.post(BASE + "/submit", headers=headers, json=PAYLOAD)).status_code == 200


async def test_cross_calendar_same_provider_id_does_not_collide(app, client, ready, google):
    from uuid import UUID

    from hub.calendars.models import Calendar

    token, _, _ = await selected(app, client)
    first = await service.submit(app.state.session_factory, token, ReportInput(**PAYLOAD))
    second_tech = (
        await client.post(
            "/api/technicians", json={"first_name": "Second", "last_name": "Fictional"}
        )
    ).json()
    tid = UUID(second_tech["id"])
    async with app.state.session_factory() as db, db.begin():
        report = await db.get(WorkReport, first.report_id)
        original = await db.get(Calendar, report.calendar_id)
        calendar = Calendar(
            id=uuid4(),
            name="Second fake calendar",
            source="GOOGLE",
            provider_connection_id=original.provider_connection_id,
            provider_calendar_id="audit-second-calendar",
            timezone=original.timezone,
            availability="AVAILABLE",
            access_role="owner",
        )
        db.add(calendar)
        db.add(
            TelegramBinding(
                technician_id=tid,
                telegram_user_id=771002,
                bot_id=9000001,
                private_status="CONNECTED",
                private_availability="AVAILABLE",
                private_generation=1,
            )
        )
    assert (
        await client.put(f"/api/technicians/{tid}/calendar", json={"calendar_id": str(calendar.id)})
    ).status_code == 200
    second_token = await issue(app, user=771002)
    await selected(app, client, second_token)
    await service.submit(app.state.session_factory, second_token, ReportInput(**PAYLOAD))
    assert await counts(app) == (2, 2)
    async with app.state.session_factory() as db:
        assert len(set((await db.scalars(select(WorkReportRevision.provider_event_id))).all())) == 1
        assert len(set((await db.scalars(select(WorkReport.calendar_id))).all())) == 2


async def test_calendar_lifecycle_keeps_history_and_blocks_sql_delete(app, client, ready):
    from hub.calendars.models import Calendar

    token, _, _ = await selected(app, client)
    receipt = await service.submit(app.state.session_factory, token, ReportInput(**PAYLOAD))
    async with app.state.session_factory() as db, db.begin():
        report = await db.get(WorkReport, receipt.report_id)
        await db.execute(
            update(Calendar)
            .where(Calendar.id == report.calendar_id)
            .values(availability="UNAVAILABLE", excluded_at=now())
        )
    assert (await client.get(f"/api/work-reports/{receipt.report_id}")).status_code == 200
    with pytest.raises(IntegrityError):
        async with app.state.session_factory() as db, db.begin():
            await db.execute(text("DELETE FROM calendars WHERE id=:id"), {"id": report.calendar_id})
    assert await counts(app) == (1, 1)


@pytest.mark.parametrize("payment", ["ESTIMATE", "CANCEL"])
async def test_outcome_sql_and_service_backstops(app, client, ready, payment):
    token, _, _ = await selected(app, client)
    receipt = await service.submit(
        app.state.session_factory, token, ReportInput(**{**PAYLOAD, "payment_method": payment})
    )
    async with app.state.session_factory() as db:
        original = await db.scalar(select(WorkReportRevision))
        assert original.amount_closed == Decimal("0.00")
        values = {c.name: getattr(original, c.name) for c in WorkReportRevision.__table__.columns}
    with pytest.raises(IntegrityError):
        async with app.state.session_factory() as db, db.begin():
            db.add(
                WorkReportRevision(
                    **{
                        **values,
                        "id": uuid4(),
                        "revision_number": 2,
                        "amount_closed": Decimal("1.00"),
                    }
                )
            )
            await db.flush()
    with pytest.raises(ValidationError):
        ReportInput(**{**PAYLOAD, "payment_method": payment, "amount_closed": "-1"})
    assert (await client.get(f"/api/work-reports/{receipt.report_id}")).json()[
        "amount_closed"
    ] == "0.00"


async def test_same_recurring_instant_with_different_offset_is_one_job(app, client, ready, google):
    from tests.test_calendar_events import item

    google.events = [
        item(
            "instance-one",
            recurringEventId="series",
            originalStartTime={"dateTime": "2026-09-17T08:00:00-04:00"},
        )
    ]
    token, _, _ = await selected(app, client)
    await service.submit(app.state.session_factory, token, ReportInput(**PAYLOAD))
    google.events = [
        item(
            "instance-reencoded",
            recurringEventId="series",
            originalStartTime={"dateTime": "2026-09-17T12:00:00Z"},
        )
    ]
    _, headers, form = await opened(app, client)
    assert form["jobs"][0]["submitted"] is True
    assert (
        await client.post(
            BASE + "/select", headers=headers, json={"choice_id": form["jobs"][0]["choice_id"]}
        )
    ).status_code == 409
    assert await counts(app) == (1, 1)
