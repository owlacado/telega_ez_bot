"""Run the actual audit rekey migration over preserved synthetic legacy history."""

from importlib import import_module

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from sqlalchemy import select, text

from hub.work_reports import service
from hub.work_reports.models import WorkReport, WorkReportRevision
from hub.work_reports.schemas import ReportInput
from tests.test_calendar_events import assigned as assigned
from tests.test_calendar_events import item
from tests.test_google_calendar import google as google
from tests.test_work_reports import PAYLOAD, selected
from tests.test_work_reports import ready as ready


@pytest.mark.parametrize("collision", [False, True])
async def test_canonical_migration_preserves_or_refuses_legacy_history(
    app, client, ready, google, monkeypatch, collision
):
    canonical = service.canonical_job
    monkeypatch.setattr(service, "canonical_job", lambda job: job)
    google.events = [
        item(
            "old-instance",
            recurringEventId="series",
            originalStartTime={"dateTime": "2026-09-17T08:00:00-04:00"},
        )
    ]
    first, _, _ = await selected(app, client)
    cached, _, _ = await selected(app, client)
    receipt = await service.submit(app.state.session_factory, first, ReportInput(**PAYLOAD))
    if collision:
        google.events = [
            item(
                "reencoded-instance",
                recurringEventId="series",
                originalStartTime={"dateTime": "2026-09-17T12:00:00Z"},
            )
        ]
        second, _, _ = await selected(app, client)
        await service.submit(app.state.session_factory, second, ReportInput(**PAYLOAD))
    monkeypatch.setattr(service, "canonical_job", canonical)
    async with app.state.session_factory() as db:
        snapshots = (await db.execute(select(WorkReportRevision.__table__))).all()
        old_keys = (await db.execute(select(WorkReport.id, WorkReport.occurrence_key))).all()

    def upgrade(connection):
        migration = import_module(
            "migrations.versions.e5f509180003_canonical_recurring_occurrences"
        )
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()

    if collision:
        with pytest.raises(RuntimeError, match="WORK_REPORT_OCCURRENCE_COLLISION"):
            async with app.state.engine.begin() as connection:
                await connection.run_sync(upgrade)
    else:
        async with app.state.engine.begin() as connection:
            await connection.run_sync(upgrade)
        with pytest.raises(HTTPException, match="already has"):
            await service.submit(app.state.session_factory, cached, ReportInput(**PAYLOAD))
    async with app.state.session_factory() as db:
        assert (await db.execute(select(WorkReportRevision.__table__))).all() == snapshots
        keys = (await db.execute(select(WorkReport.id, WorkReport.occurrence_key))).all()
        assert (keys == old_keys) is collision
        assert await db.scalar(
            text("SELECT tgenabled FROM pg_trigger WHERE tgname='work_report_identity_immutable'")
        ) in {"O", b"O"}
        assert await db.get(WorkReport, receipt.report_id)
