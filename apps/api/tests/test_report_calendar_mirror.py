"""Report mirror uses disposable PostgreSQL and instrumented fake provider only."""

import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import event, func, select, text

from hub.calendars.models import Calendar
from hub.google_calendar.models import CalendarConnection
from hub.google_calendar.types import REPORT_WRITE_SCOPE, ProviderError
from hub.report_mirror import worker
from hub.report_mirror.models import ReportCalendarMirror
from hub.report_mirror.presentation import END, START, merge
from hub.telegram.models import TelegramOutbox
from hub.work_reports.models import WorkReport, WorkReportRevision
from tests.test_work_reports import BASE, PAYLOAD, selected
from tests.test_work_reports import assigned as assigned
from tests.test_work_reports import google as google
from tests.test_work_reports import ready as ready


async def setup(app, client, ready, google, monkeypatch):
    _, headers, _ = await selected(app, client)
    response = await client.post(BASE + "/submit", headers=headers, json=PAYLOAD)
    assert response.status_code == 200
    report_id = UUID(response.json()["report_id"])
    async with app.state.session_factory() as db, db.begin():
        intent = await db.get(ReportCalendarMirror, report_id)
        assert intent and intent.status == "PENDING"
        connection = await db.get(CalendarConnection, intent.connection_id)
        connection.granted_scopes = [*connection.granted_scopes, REPORT_WRITE_SCOPE]
        google.grant = replace(google.grant, scopes=tuple(connection.granted_scopes))
        calendar = await db.get(Calendar, intent.calendar_id)
        calendar.access_role = "writer"
    source = {
        "id": intent.provider_event_id,
        "etag": '"v1"',
        "description": "Manual notes\r\n  exact whitespace \t",
        "status": "confirmed",
    }
    calls = []
    active = set()

    def begin(connection):
        active.add(connection)

    def end(connection):
        active.discard(connection)

    engine = app.state.session_factory.kw["bind"].sync_engine
    event.listen(engine, "begin", begin)
    event.listen(engine, "commit", end)
    event.listen(engine, "rollback", end)

    refresh = google.refresh_credentials

    async def safe_refresh(*args, **kwargs):
        assert not active
        return await refresh(*args, **kwargs)

    monkeypatch.setattr(google, "refresh_credentials", safe_refresh)

    async def get(token, calendar_id, event_id):
        assert not active
        assert (calendar_id, event_id) == (intent.provider_calendar_id, intent.provider_event_id)
        calls.append("get")
        return deepcopy(source)

    async def patch(token, calendar_id, event_id, etag, description):
        assert not active
        assert (calendar_id, event_id) == (intent.provider_calendar_id, intent.provider_event_id)
        assert etag == source["etag"]
        calls.append("patch")
        source.update(description=description, etag='"v2"')
        return deepcopy(source)

    monkeypatch.setattr(google, "get_report_event", get, raising=False)
    monkeypatch.setattr(google, "patch_report_description", patch, raising=False)
    return report_id, source, calls, patch


async def retry(app, report_id):
    async with app.state.session_factory() as db, db.begin():
        row = await db.get(ReportCalendarMirror, report_id)
        row.available_at = await db.scalar(select(func.clock_timestamp())) - timedelta(seconds=1)


async def revision(app, report_id):
    async with app.state.session_factory() as db, db.begin():
        report = await db.get(WorkReport, report_id, with_for_update=True)
        old = await db.scalar(
            select(WorkReportRevision).where(WorkReportRevision.report_id == report_id)
        )
        values = {
            c.name: getattr(old, c.name)
            for c in WorkReportRevision.__table__.columns
            if c.name not in {"id", "submitted_at"}
        }
        values.update(revision_number=2, amount_closed=Decimal("450.00"), comments="Updated notes")
        db.add(WorkReportRevision(**values))
        await db.flush()
        # Existing correction workflows are deferred. Simulate a future authorized canonical
        # revision in this disposable fixture without weakening production history triggers.
        await db.execute(
            text("ALTER TABLE work_reports DISABLE TRIGGER work_report_identity_immutable")
        )
        report.current_revision_number = 2
        await db.flush()
        await db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        await db.execute(
            text("ALTER TABLE work_reports ENABLE TRIGGER work_report_identity_immutable")
        )


async def test_first_revision_manual_bytes_and_exact_target(
    app, client, ready, google, monkeypatch
):
    rid, source, calls, _ = await setup(app, client, ready, google, monkeypatch)
    manual = source["description"]
    await worker.run_once(app.state.session_factory, app.state.settings, google)
    assert calls == ["get", "patch"]
    assert source["description"].startswith(manual + "\n\n" + START)
    assert source["description"].count(START) == source["description"].count(END) == 1
    assert "771001" not in source["description"] and str(rid) not in source["description"]
    source["description"] += "\r\nManual suffix  "
    await revision(app, rid)
    await worker.run_once(app.state.session_factory, app.state.settings, google)
    assert source["description"].startswith(manual + "\n\n")
    assert source["description"].endswith("\r\nManual suffix  ")
    assert "$450.00" in source["description"] and "$850.10" not in source["description"]
    assert source["description"].count(START) == 1
    async with app.state.session_factory() as db:
        mirror = await db.get(ReportCalendarMirror, rid)
        assert mirror.status == "SYNCED" and mirror.synced_revision == 2


@pytest.mark.parametrize("ambiguous", [False, True])
async def test_failure_isolated_and_refetch_reconciles_without_append(
    app, client, ready, google, monkeypatch, ambiguous
):
    rid, source, calls, patch = await setup(app, client, ready, google, monkeypatch)

    async def failure(*args):
        if ambiguous:
            await patch(*args)
        raise ProviderError("PROVIDER_TEMPORARY_ERROR")

    monkeypatch.setattr(google, "patch_report_description", failure)
    await worker.run_once(app.state.session_factory, app.state.settings, google)
    async with app.state.session_factory() as db:
        assert await db.get(WorkReport, rid)
        assert (await db.get(ReportCalendarMirror, rid)).status == "BLOCKED"
        assert await db.scalar(select(TelegramOutbox).where(TelegramOutbox.report_id == rid))
    await retry(app, rid)
    monkeypatch.setattr(google, "patch_report_description", patch)
    await worker.run_once(app.state.session_factory, app.state.settings, google)
    assert source["description"].count(START) == 1
    assert calls.count("patch") == 1
    assert calls.count("get") == 2


async def test_concurrent_workers_and_crash_expiry(app, client, ready, google, monkeypatch):
    rid, source, calls, _ = await setup(app, client, ready, google, monkeypatch)
    claims = await asyncio.gather(
        worker.claim(app.state.session_factory), worker.claim(app.state.session_factory)
    )
    assert sum(c is not None for c in claims) == 1
    original = next(c for c in claims if c)
    async with app.state.session_factory() as db, db.begin():
        row = await db.get(ReportCalendarMirror, rid)
        row.lease_until = await db.scalar(select(func.clock_timestamp())) - timedelta(seconds=1)
    await worker.run_once(app.state.session_factory, app.state.settings, google)
    await worker.finish(app.state.session_factory, original, error="STALE_OWNER")
    async with app.state.session_factory() as db:
        assert (await db.get(ReportCalendarMirror, rid)).status == "SYNCED"
    assert calls.count("patch") == 1


@pytest.mark.parametrize(
    "change", ["scope", "switch", "calendar", "event", "cancelled", "readonly", "malformed"]
)
async def test_source_permission_and_identity_fail_closed(
    app, client, ready, google, monkeypatch, change
):
    rid, source, calls, _ = await setup(app, client, ready, google, monkeypatch)
    async with app.state.session_factory() as db, db.begin():
        mirror = await db.get(ReportCalendarMirror, rid)
        connection = await db.get(CalendarConnection, mirror.connection_id)
        calendar = await db.get(Calendar, mirror.calendar_id)
        if change == "scope":
            connection.granted_scopes = []
        if change == "switch":
            connection.is_current = False
            connection.status = "DISCONNECTED"
            connection.encrypted_refresh_token = None
        if change == "calendar":
            calendar.excluded_at = await db.scalar(select(func.now()))
        if change == "readonly":
            calendar.access_role = "reader"
    if change == "event":
        source["id"] = "wrong-event"
    if change == "cancelled":
        source["status"] = "cancelled"
    if change == "malformed":
        source["description"] += START
    await worker.run_once(app.state.session_factory, app.state.settings, google)
    assert "patch" not in calls
    async with app.state.session_factory() as db:
        assert (await db.get(ReportCalendarMirror, rid)).status == "BLOCKED"


async def test_etag_conflict_refetch_preserves_new_notes(app, client, ready, google, monkeypatch):
    rid, source, calls, patch = await setup(app, client, ready, google, monkeypatch)

    async def conflict(*args):
        source["description"] += "\nConcurrent dispatcher note"
        source["etag"] = '"changed"'
        raise ProviderError("EVENT_CHANGED")

    monkeypatch.setattr(google, "patch_report_description", conflict)
    await worker.run_once(app.state.session_factory, app.state.settings, google)
    await retry(app, rid)
    monkeypatch.setattr(google, "patch_report_description", patch)
    await worker.run_once(app.state.session_factory, app.state.settings, google)
    assert "Concurrent dispatcher note" in source["description"]
    assert source["description"].count(START) == 1


@pytest.mark.parametrize("text", ["", "  text\r\n", "<b>customer</b> & \t"])
def test_managed_merge_preserves_outside_bytes(text):
    a = START + "old" + END
    b = START + "new" + END
    assert merge(text + a + text, b) == text + b + text
    assert merge(text + a + text + a + text, b) == text + b + text + text
    assert merge(merge(text, b), b) == merge(text, b)


async def test_explicit_write_scope_upgrade_same_account(app, client, ready, google):
    base = "/api/calendar-connections/google"
    state = (await client.get(base)).json()
    result = await client.post(
        base + "/start",
        json={
            "mode": "RECONNECT",
            "expected_connection_id": state["id"],
            "expected_generation": state["generation"],
            "request_report_write_access": True,
            "request_event_access": True,
        },
    )
    assert result.status_code == 200
    completed = await client.get(result.json()["authorization_url"])
    assert completed.status_code == 303 and "connected" in completed.headers["location"]
    state = (await client.get(base)).json()
    assert REPORT_WRITE_SCOPE in state["granted_scopes"]


async def test_revision_during_get_is_reconciled_before_patch(
    app, client, ready, google, monkeypatch
):
    rid, source, calls, _ = await setup(app, client, ready, google, monkeypatch)
    original = google.get_report_event

    async def concurrent(*args):
        value = await original(*args)
        await revision(app, rid)
        return value

    monkeypatch.setattr(google, "get_report_event", concurrent)
    await worker.run_once(app.state.session_factory, app.state.settings, google)
    assert "patch" not in calls
    monkeypatch.setattr(google, "get_report_event", original)
    await retry(app, rid)
    await worker.run_once(app.state.session_factory, app.state.settings, google)
    assert "$450.00" in source["description"]


async def test_http_boundary_encoded_identity_etag_description_only(monkeypatch):
    from types import SimpleNamespace

    import requests

    from hub.google_calendar.provider import GoogleCalendarProvider

    seen = []

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def patch(self, url, **kwargs):
            seen.append((url, kwargs))
            return SimpleNamespace(status_code=200, json=lambda: {"id": "event/id"})

    monkeypatch.setattr(requests, "Session", Session)
    provider = object.__new__(GoogleCalendarProvider)
    await provider.patch_report_description(
        "fake-access-only", "calendar@example.invalid", "event/id", '"etag"', "Exact\r\nnotes"
    )
    url, options = seen[0]
    assert url.endswith("calendar%40example.invalid/events/event%2Fid")
    assert options["headers"]["If-Match"] == '"etag"'
    assert options["json"] == {"description": "Exact\r\nnotes"}
    assert options["params"] == {"sendUpdates": "none"}
    assert options["allow_redirects"] is False


async def test_invalid_report_creates_no_durable_mirror_intent(app, client, ready, google):
    _, headers, _ = await selected(app, client)
    # Canonical form validation fails before the transaction can persist a report or intent.
    result = await client.post(
        BASE + "/submit", headers=headers, json={**PAYLOAD, "amount_closed": "-1.00"}
    )
    assert result.status_code == 422
    async with app.state.session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(ReportCalendarMirror)) == 0
        assert await db.scalar(select(func.count()).select_from(WorkReport)) == 0


async def test_report_mirror_claim_target_cannot_be_redirected(
    app, client, ready, google, monkeypatch
):
    from sqlalchemy.exc import DBAPIError

    rid, _, _, _ = await setup(app, client, ready, google, monkeypatch)
    async with app.state.session_factory() as db:
        mirror = await db.get(ReportCalendarMirror, rid)
        mirror.provider_event_id = "different-event"
        with pytest.raises(DBAPIError):
            await db.commit()


async def test_business_rollback_also_rolls_back_triggered_intent(
    app, client, ready, google, monkeypatch
):
    from hub.work_reports import service

    _, headers, _ = await selected(app, client)

    observed = []

    async def fail_before_commit(db, *args):
        await db.flush()
        observed.append(await db.scalar(select(func.count()).select_from(ReportCalendarMirror)))
        raise RuntimeError("synthetic transaction failure")

    monkeypatch.setattr(service, "enqueue_for_business_change", fail_before_commit)
    response = await client.post(BASE + "/submit", headers=headers, json=PAYLOAD)
    assert response.status_code == 500 and "synthetic" not in response.text
    assert observed == [1]
    async with app.state.session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(ReportCalendarMirror)) == 0
        assert await db.scalar(select(func.count()).select_from(WorkReport)) == 0


async def test_existing_google_worker_runs_report_lane_despite_sheets_failure(
    app, google, monkeypatch
):
    from hub.accounting_mirrors import worker as mirrors

    instance = mirrors.Worker(app.state.session_factory, app.state.settings, google)
    called = []

    async def sheets(*args):
        raise RuntimeError("synthetic sheets lane failure")

    async def reports(*args):
        called.append("report")
        instance.stop.set()
        return []

    monkeypatch.setattr(mirrors, "run_once", sheets)
    monkeypatch.setattr(worker, "run_once", reports)
    await instance.run()
    assert called == ["report"]
