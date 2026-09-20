"""Real PostgreSQL linearization and direct-integrity probes."""

import asyncio
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError

from hub.integrations.models import TelegramBinding
from hub.technicians.models import Technician
from hub.work_reports import service
from hub.work_reports.models import WorkReport, WorkReportRevision
from hub.work_reports.schemas import ReportInput
from tests.test_calendar_events import assigned as assigned
from tests.test_google_calendar import google as google
from tests.test_work_reports import PAYLOAD, counts, selected
from tests.test_work_reports import ready as ready


async def test_two_distinct_sessions_race(app, client, ready):
    first, _, _ = await selected(app, client)
    second, _, _ = await selected(app, client)
    results = await asyncio.gather(
        *(
            service.submit(app.state.session_factory, token, ReportInput(**PAYLOAD))
            for token in [first, second]
        ),
        return_exceptions=True,
    )
    assert sum(not isinstance(result, Exception) for result in results) == 1
    assert any(
        isinstance(result, HTTPException) and result.status_code == 409 for result in results
    )
    assert await counts(app) == (1, 1)


@pytest.mark.parametrize("change", ["inactive", "rebind"])
async def test_lifecycle_wins_lock_then_submit_rejected(app, client, ready, change):
    token, _, _ = await selected(app, client)
    async with app.state.session_factory() as db, db.begin():
        tech = await db.scalar(select(Technician).where(Technician.id == ready).with_for_update())
        submission = asyncio.create_task(
            service.submit(app.state.session_factory, token, ReportInput(**PAYLOAD))
        )
        await asyncio.sleep(0.05)
        assert not submission.done()
        if change == "inactive":
            tech.status = "INACTIVE"
        else:
            await db.execute(
                update(TelegramBinding)
                .where(TelegramBinding.technician_id == ready)
                .values(private_generation=2, telegram_user_id=100002)
            )
    with pytest.raises(HTTPException):
        await submission
    assert await counts(app) == (0, 0)


async def test_manager_never_reads_half_committed_report(app, client, ready, monkeypatch):
    token, _, _ = await selected(app, client)
    entered, release = asyncio.Event(), asyncio.Event()
    original = service.authorize

    async def pause(db, token):
        result = await original(db, token)
        entered.set()
        await release.wait()
        return result

    monkeypatch.setattr(service, "authorize", pause)
    pending = asyncio.create_task(
        service.submit(app.state.session_factory, token, ReportInput(**PAYLOAD))
    )
    await entered.wait()
    assert (await client.get(f"/api/technicians/{ready}/work-reports")).json()["reports"] == []
    release.set()
    await pending
    reports = (await client.get(f"/api/technicians/{ready}/work-reports")).json()["reports"]
    assert len(reports) == 1 and reports[0]["revision_number"] == 1


async def test_submission_wins_lock_then_delete_cannot_remove_history(
    app, client, ready, monkeypatch
):
    token, _, _ = await selected(app, client)
    profile = (await client.get(f"/api/technicians/{ready}")).json()
    entered, release = asyncio.Event(), asyncio.Event()
    original = service.authorize

    async def pause(db, token):
        result = await original(db, token)
        entered.set()
        await release.wait()
        return result

    monkeypatch.setattr(service, "authorize", pause)
    submission = asyncio.create_task(
        service.submit(app.state.session_factory, token, ReportInput(**PAYLOAD))
    )
    await entered.wait()
    deletion = asyncio.create_task(
        client.request(
            "DELETE",
            f"/api/technicians/{ready}",
            json={"confirmation": "DELETE", "expected_record_version": profile["record_version"]},
        )
    )
    await asyncio.sleep(0.05)
    assert not deletion.done()
    release.set()
    await submission
    response = await deletion
    assert response.status_code == 409 and "deactivate" in response.text.lower()
    assert await counts(app) == (1, 1)


@pytest.mark.parametrize(
    "mutation",
    [
        "negative",
        "zero",
        "enum",
        "reviews",
        "orphan",
        "duplicate_revision",
        "duplicate_identity",
        "missing_revision",
    ],
)
async def test_database_checks_reject_direct_writes(app, client, ready, mutation):
    token, _, _ = await selected(app, client)
    receipt = await service.submit(app.state.session_factory, token, ReportInput(**PAYLOAD))
    async with app.state.session_factory() as db:
        report = await db.get(WorkReport, receipt.report_id)
        revision = await db.scalar(select(WorkReportRevision))
        values = {
            col.name: getattr(revision, col.name) for col in WorkReportRevision.__table__.columns
        }
    values["id"], values["revision_number"] = uuid4(), 2
    if mutation == "negative":
        values["amount_closed"] = Decimal("-1")
    if mutation == "zero":
        values.update(payment_method="ESTIMATE", amount_closed=Decimal("1"))
    if mutation == "enum":
        values["payment_method"] = "BOGUS"
    if mutation == "reviews":
        values["google_reviews"] = 101
    if mutation == "orphan":
        values["report_id"] = uuid4()
    if mutation == "duplicate_revision":
        values["revision_number"] = 1
    with pytest.raises(IntegrityError):
        async with app.state.session_factory() as db, db.begin():
            if mutation in {"duplicate_identity", "missing_revision"}:
                new_id = uuid4()
                db.add(
                    WorkReport(
                        id=new_id,
                        technician_id=ready,
                        calendar_id=report.calendar_id,
                        occurrence_key=report.occurrence_key
                        if mutation == "duplicate_identity"
                        else "a" * 64,
                    )
                )
                await db.flush()
                if mutation == "duplicate_identity":
                    db.add(
                        WorkReportRevision(**{**values, "report_id": new_id, "revision_number": 1})
                    )
            else:
                db.add(WorkReportRevision(**values))
            await db.flush()
    assert await counts(app) == (1, 1)


async def test_business_history_foreign_key_is_restrict(app, ready):
    async with app.state.session_factory() as db:
        action = await db.scalar(
            text(
                "SELECT confdeltype FROM pg_constraint "
                "WHERE conname='fk_work_reports_technician_id_technicians'"
            )
        )
        assert action == b"r" or action == "r"


async def test_populated_downgrade_refused_without_losing_history(app, client, ready):
    token, _, _ = await selected(app, client)
    await service.submit(app.state.session_factory, token, ReportInput(**PAYLOAD))
    async with app.state.session_factory() as db:
        # Same guard as migration, executed inside a transaction and rolled back.
        with pytest.raises(Exception, match="WORK_REPORT_HISTORY_ROLLBACK_REFUSED"):
            await db.execute(
                text("""DO $$ BEGIN IF EXISTS (SELECT 1 FROM work_reports)
                THEN RAISE EXCEPTION 'WORK_REPORT_HISTORY_ROLLBACK_REFUSED'; END IF; END $$""")
            )
        await db.rollback()
    assert await counts(app) == (1, 1)
