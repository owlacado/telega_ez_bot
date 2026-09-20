"""Independent Stage 9 adversarial audit using fake Google and isolated PostgreSQL."""

import asyncio
import inspect
import json
import logging
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError

from hub.accounting.xlsx import WeeklyAccountingXlsxModel
from hub.accounting_mirrors import presentation, service
from hub.accounting_mirrors.models import (
    AccountingMirrorRefresh,
    AccountingMirrorTarget,
    AccountingMirrorWorkerState,
)
from hub.accounting_mirrors.presentation import all_tech_payload, individual_payload, money
from hub.accounting_mirrors.provider import (
    FORMAT_REQUEST_CHUNK,
    VALUE_BODY_BYTES,
    GoogleSheetsHttpMixin,
    SheetMetadata,
    SheetsProviderError,
    formatting_requests,
    value_chunks,
)
from hub.accounting_mirrors.worker import (
    claim,
    finalize_success,
    renew_claim_lease,
    run_once,
)
from hub.audit.models import AuditEvent
from hub.auth.models import Manager
from hub.calendars.models import Calendar
from hub.expenses.models import TechnicianExpense
from hub.google_calendar.models import CalendarConnection
from hub.work_reports.models import WorkReport
from tests.accounting_data import seed
from tests.test_accounting_mirrors import START, configure, ready_google


async def queue_sync(client, base, configured):
    response = await client.post(
        f"{base}/action?week_start={START}",
        json={"action": "SYNC", "expected_generation": configured["target_generation"]},
    )
    assert response.status_code == 200, response.text


def test_google_is_metadata_only_and_never_accounting_authority():
    from hub.accounting_mirrors import provider, worker

    provider_source = inspect.getsource(provider)
    worker_source = inspect.getsource(worker)
    assert "values.get" not in provider_source
    assert "includeGridData" not in provider_source
    assert "userEnteredValue" not in worker_source
    assert "calculate(" in worker_source and "calculate_all_weekly(" in worker_source


def test_worker_safety_structure_is_explicit():
    from hub.accounting_mirrors import worker

    source = inspect.getsource(worker)
    process_source = inspect.getsource(worker.process_claim)
    assert ".with_for_update(skip_locked=True" in source
    assert "refresh.claim_token != current.claim_token" in source
    assert "max(current.owned_rows, payload.row_count)" in source
    assert "max(current.owned_columns, payload.column_count)" in source
    assert 'current.claimed_from_status != "FAILED"' in source
    assert "target.generation == current.target_generation" in source
    assert "connection.generation == current.connection_generation" in source
    assert "async with factory()" not in process_source


async def test_transaction_rollback_cannot_separate_business_record_and_refresh(app, client):
    technician_id = await seed(app.state.session_factory, START)
    await ready_google(app)
    await configure(client, technician_id)
    async with app.state.session_factory() as db:
        calendar_id = await db.scalar(select(Calendar.id).limit(1))
    report_id, expense_id = uuid4(), uuid4()

    with pytest.raises(RuntimeError, match="audit rollback"):
        async with app.state.session_factory() as db, db.begin():
            db.add(
                WorkReport(
                    id=report_id,
                    technician_id=technician_id,
                    calendar_id=calendar_id,
                    occurrence_key="a" * 64,
                )
            )
            await service.enqueue_for_business_change(db, technician_id, START)
            raise RuntimeError("audit rollback")
    with pytest.raises(RuntimeError, match="audit rollback"):
        async with app.state.session_factory() as db, db.begin():
            db.add(TechnicianExpense(id=expense_id, technician_id=technician_id))
            await service.enqueue_for_business_change(db, technician_id, START)
            raise RuntimeError("audit rollback")

    async with app.state.session_factory() as db:
        assert await db.get(WorkReport, report_id) is None
        assert await db.get(TechnicianExpense, expense_id) is None
        assert await db.scalar(select(func.count()).select_from(AccountingMirrorRefresh)) == 0


async def test_historical_both_targets_coalesce_100_changes_without_provider(app, client):
    technician_id = await seed(app.state.session_factory, START)
    fake = await ready_google(app)
    await configure(client, technician_id, spreadsheet="individualAudit_12345")
    await configure(
        client,
        technician_id,
        all_tech=True,
        spreadsheet="allTechAudit_12345",
    )
    historical = date(2020, 1, 1)
    async with app.state.session_factory() as db, db.begin():
        for _ in range(100):
            await service.enqueue_for_business_change(db, technician_id, historical)
    async with app.state.session_factory() as db:
        rows = (await db.scalars(select(AccountingMirrorRefresh))).all()
        assert len(rows) == 2
        assert {row.week_start for row in rows} == {date(2019, 12, 30)}
        assert {row.requested_generation for row in rows} == {100}
    assert fake.sheets_calls == []


async def test_no_target_and_disabled_target_create_no_automatic_work(app, client):
    technician_id = await seed(app.state.session_factory, START)
    fake = await ready_google(app)
    async with app.state.session_factory() as db, db.begin():
        await service.enqueue_for_business_change(db, technician_id, START)
    base, configured = await configure(client, technician_id)
    response = await client.post(
        f"{base}/action?week_start={START}",
        json={"action": "DISABLE", "expected_generation": configured["target_generation"]},
    )
    assert response.status_code == 200
    async with app.state.session_factory() as db, db.begin():
        await service.enqueue_for_business_change(db, technician_id, START)
    async with app.state.session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(AccountingMirrorRefresh)) == 0
    assert fake.sheets_calls == []


async def test_spreadsheet_cannot_be_shared_by_two_logical_targets(app, client):
    technician_id = await seed(app.state.session_factory, START)
    await ready_google(app)
    spreadsheet = "exclusiveSpreadsheet_12345"
    await configure(client, technician_id, spreadsheet=spreadsheet)
    response = await client.put(
        f"/api/accounting/weekly/all/mirror?week_start={START}",
        json={"spreadsheet": spreadsheet, "replace": False},
    )
    assert response.status_code == 409
    assert "already assigned" in response.text
    async with app.state.session_factory() as db:
        connection = await db.scalar(select(CalendarConnection))
        db.add(
            AccountingMirrorTarget(
                kind="ALL_TECH",
                google_connection_id=connection.id,
                spreadsheet_id=spreadsheet,
            )
        )
        with pytest.raises(IntegrityError):
            await db.commit()


async def test_failed_attempt_cannot_fingerprint_skip_retry(app, client):
    technician_id = await seed(app.state.session_factory, START)
    fake = await ready_google(app)
    base, configured = await configure(client, technician_id)
    await queue_sync(client, base, configured)
    assert await run_once(app.state.session_factory, app.state.settings, fake, limit=1) == [True]

    async with app.state.session_factory() as db, db.begin():
        target = await db.scalar(select(AccountingMirrorTarget))
        await service.enqueue_target(db, target.id, START)
    fake.sheets_error = SheetsProviderError("PROVIDER_TEMPORARY_ERROR", retryable=True)
    assert await run_once(app.state.session_factory, app.state.settings, fake, limit=1) == [False]
    fake.sheets_error = None
    async with app.state.session_factory() as db, db.begin():
        await db.execute(
            update(AccountingMirrorRefresh).values(
                retry_at=datetime.now(UTC) - timedelta(seconds=1)
            )
        )
    before = fake.sheets_calls.count(("values", "RAW"))
    assert await run_once(app.state.session_factory, app.state.settings, fake, limit=1) == [True]
    assert fake.sheets_calls.count(("values", "RAW")) == before + 1


async def test_stale_owner_cannot_finalize_and_current_owner_renews_with_db_clock(app, client):
    technician_id = await seed(app.state.session_factory, START)
    await ready_google(app)
    await configure(client, technician_id)
    async with app.state.session_factory() as db, db.begin():
        target = await db.scalar(select(AccountingMirrorTarget))
        await service.enqueue_target(db, target.id, START)
    stale = await claim(app.state.session_factory)
    async with app.state.session_factory() as db, db.begin():
        await db.execute(
            update(AccountingMirrorRefresh).values(
                claimed_at=func.clock_timestamp() - timedelta(minutes=16),
                lease_until=func.clock_timestamp() - timedelta(minutes=1),
            )
        )
    current = await claim(app.state.session_factory)
    assert stale and current and stale.claim_token != current.claim_token
    assert await renew_claim_lease(app.state.session_factory, current)
    payload = presentation.SheetsPayload(
        title="audit",
        values=(("audit",),),
        formats=(),
        row_heights=(),
        column_widths=(),
        row_count=1,
        column_count=1,
        fingerprint="a" * 64,
        technician_count=1,
    )
    await finalize_success(
        app.state.session_factory,
        stale,
        payload,
        SheetMetadata(1, "audit", 1, 1),
    )
    async with app.state.session_factory() as db:
        refresh = await db.scalar(select(AccountingMirrorRefresh))
        assert refresh.status == "PROCESSING"
        assert refresh.claim_token == current.claim_token
        assert refresh.completed_generation == 0
        database_now = await db.scalar(select(func.clock_timestamp()))
        assert refresh.lease_until > database_now


async def test_twenty_workers_still_produce_one_active_owner(app, client):
    technician_id = await seed(app.state.session_factory, START)
    await ready_google(app)
    await configure(client, technician_id)
    async with app.state.session_factory() as db, db.begin():
        target = await db.scalar(select(AccountingMirrorTarget))
        await service.enqueue_target(db, target.id, START)
    claims = await asyncio.gather(*(claim(app.state.session_factory) for _ in range(20)))
    assert sum(item is not None for item in claims) == 1


async def test_rename_is_retained_by_sheet_id_and_delete_recreates(app, client):
    technician_id = await seed(app.state.session_factory, START)
    fake = await ready_google(app)
    base, configured = await configure(client, technician_id)
    await queue_sync(client, base, configured)
    assert await run_once(app.state.session_factory, app.state.settings, fake, limit=1) == [True]
    book = fake.spreadsheets["stage9Sheet_12345"]
    original_id = book["sheets"][0]["id"]
    book["sheets"][0]["title"] = "Manager retained rename"
    async with app.state.session_factory() as db, db.begin():
        target = await db.scalar(select(AccountingMirrorTarget))
        await service.enqueue_target(db, target.id, START)
    assert await run_once(app.state.session_factory, app.state.settings, fake, limit=1) == [True]
    assert len(book["sheets"]) == 1 and book["sheets"][0]["id"] == original_id

    book["sheets"].clear()
    async with app.state.session_factory() as db, db.begin():
        target = await db.scalar(select(AccountingMirrorTarget))
        await service.enqueue_target(db, target.id, START)
    assert await run_once(app.state.session_factory, app.state.settings, fake, limit=1) == [True]
    assert len(book["sheets"]) == 1 and book["sheets"][0]["id"] != original_id


async def test_worker_health_distinguishes_missing_stale_stopped_error_and_running(app):
    async with app.state.session_factory() as db:
        assert await service.worker_state(db) == "MISSING"
    worker_id = uuid4()
    async with app.state.session_factory() as db, db.begin():
        db.add(
            AccountingMirrorWorkerState(
                worker_id=worker_id,
                status="RUNNING",
                heartbeat_at=datetime.now(UTC) - timedelta(minutes=5),
            )
        )
    async with app.state.session_factory() as db:
        assert await service.worker_state(db) == "STALE"
    for status in ("STOPPED", "ERROR", "RUNNING"):
        async with app.state.session_factory() as db, db.begin():
            row = await db.get(AccountingMirrorWorkerState, worker_id, with_for_update=True)
            row.status = status
            row.heartbeat_at = await db.scalar(select(func.clock_timestamp()))
        async with app.state.session_factory() as db:
            assert await service.worker_state(db) == status


@pytest.mark.parametrize(
    "value,valid",
    [
        ("auditSheet_12345", True),
        (" https://docs.google.com/spreadsheets/d/auditSheet_12345/edit?gid=0 ", True),
        ("https://docs.google.com:443/spreadsheets/d/auditSheet_12345", True),
        ("https://docs.google.com.evil.invalid/spreadsheets/d/auditSheet_12345", False),
        ("https://user@docs.google.com/spreadsheets/d/auditSheet_12345", False),
        ("javascript:alert(1)", False),
        ("audit\x00Sheet_12345", False),
        ("a" * 201, False),
    ],
)
def test_spreadsheet_url_adversarial_cases(value, valid):
    if valid:
        assert service.normalize_spreadsheet_id(value) == "auditSheet_12345"
    else:
        with pytest.raises(HTTPException):
            service.normalize_spreadsheet_id(value)


async def test_value_and_format_chunk_boundaries_and_retry_from_first_chunk(monkeypatch):
    rows = tuple((index, "x") for index in range(501))
    chunks = list(value_chunks(rows))
    assert [start for start, _ in chunks] == [0, 500]
    assert sum(len(body["values"]) for _, body in chunks) == 501
    large = (("x" * 2_100_000,), ("y" * 2_100_000,))
    byte_chunks = list(value_chunks(large))
    assert len(byte_chunks) == 2
    assert all(len(json.dumps(body).encode()) <= VALUE_BODY_BYTES for _, body in byte_chunks)
    with pytest.raises(SheetsProviderError):
        list(value_chunks((("z" * (VALUE_BODY_BYTES + 1),),)))

    calls = []
    failed = False

    async def fail_second(self, method, path, access_token, body=None):
        nonlocal failed
        calls.append(path)
        if len(calls) == 2 and not failed:
            failed = True
            raise SheetsProviderError("PROVIDER_TEMPORARY_ERROR", retryable=True)
        return {}

    monkeypatch.setattr(GoogleSheetsHttpMixin, "_sheets_request", fail_second)
    provider = GoogleSheetsHttpMixin()
    with pytest.raises(SheetsProviderError):
        await provider.write_values("token", "auditSheet_12345", "audit", rows)
    await provider.write_values("token", "auditSheet_12345", "audit", rows)
    assert "A1" in calls[0] and "A1" in calls[2]

    payload = presentation.SheetsPayload(
        title="audit",
        values=(("audit",),),
        formats=tuple(
            presentation.FormatRange(i, i + 1, 0, 1, "JOB_CELL")
            for i in range(FORMAT_REQUEST_CHUNK)
        ),
        row_heights=(),
        column_widths=(),
        row_count=FORMAT_REQUEST_CHUNK,
        column_count=1,
        fingerprint="b" * 64,
        technician_count=1,
    )
    assert len(formatting_requests(1, payload, 1, 1)) == FORMAT_REQUEST_CHUNK + 1


async def test_layout_name_order_locale_timezone_and_formula_text_change_fingerprint(app):
    technician_id = await seed(app.state.session_factory, START)
    from hub.accounting.service import calculate

    async with app.state.session_factory() as db:
        accounting = await calculate(db, technician_id, "weekly", START)
    model = WeeklyAccountingXlsxModel.from_accounting(accounting)
    baseline = individual_payload(model)
    renamed = individual_payload(replace(model, technician_name="Renamed Technician"))
    assert baseline.fingerprint != renamed.fingerprint
    old_version = presentation.LAYOUT_VERSION
    try:
        presentation.LAYOUT_VERSION = old_version + "-audit"
        assert baseline.fingerprint != individual_payload(model).fingerprint
    finally:
        presentation.LAYOUT_VERSION = old_version
    second = replace(model, technician_id=uuid4(), technician_name="Second Technician")
    first_order = all_tech_payload((model, second), START)
    reverse_order = all_tech_payload((second, model), START)
    assert first_order.fingerprint != reverse_order.fingerprint
    assert baseline.title == "2026-09-14 - 2026-09-20"
    dangerous = ("=", "+1", "-1", "@cmd", "=HYPERLINK('x')", "=IMPORTXML('x')")
    assert all(isinstance(value, str) for value in dangerous)
    assert money(Decimal("1.10")) == "$1.10"


async def test_error_canaries_are_redacted_from_state_and_logs(app, client, caplog, monkeypatch):
    technician_id = await seed(app.state.session_factory, START)
    fake = await ready_google(app)
    base, configured = await configure(client, technician_id)
    await queue_sync(client, base, configured)
    canary = "TOKEN_CANARY ADDRESS_CANARY EXPENSE_CANARY CUSTOMER_CANARY"

    async def explode(*args, **kwargs):
        raise RuntimeError(canary)

    monkeypatch.setattr(fake, "get_spreadsheet_metadata", explode)
    caplog.set_level(logging.INFO)
    assert await run_once(app.state.session_factory, app.state.settings, fake, limit=1) == [False]
    async with app.state.session_factory() as db:
        refresh = await db.scalar(select(AccountingMirrorRefresh))
        assert refresh.last_error_code == "PROVIDER_TEMPORARY_ERROR"
    status = await client.get(f"{base}?week_start={START}")
    assert canary not in status.text and canary not in caplog.text


async def test_status_never_claims_synced_after_later_failure_and_keeps_last_success(app, client):
    technician_id = await seed(app.state.session_factory, START)
    fake = await ready_google(app)
    base, configured = await configure(client, technician_id)
    await queue_sync(client, base, configured)
    assert await run_once(app.state.session_factory, app.state.settings, fake, limit=1) == [True]
    first = (await client.get(f"{base}?week_start={START}")).json()
    assert first["state"] == "SYNCED" and first["last_success_at"]
    async with app.state.session_factory() as db, db.begin():
        target = await db.scalar(select(AccountingMirrorTarget))
        await service.enqueue_target(db, target.id, START)
    fake.sheets_error = SheetsProviderError("SPREADSHEET_NOT_FOUND")
    assert await run_once(app.state.session_factory, app.state.settings, fake, limit=1) == [False]
    failed = (await client.get(f"{base}?week_start={START}")).json()
    assert failed["state"] == "FAILED"
    assert failed["pending_newer_generation"]
    assert failed["last_success_at"] == first["last_success_at"]


async def test_config_actions_audit_once_and_status_polling_does_not_spam(app, client):
    technician_id = await seed(app.state.session_factory, START)
    await ready_google(app)
    base, configured = await configure(client, technician_id)
    await queue_sync(client, base, configured)
    disabled = await client.post(
        f"{base}/action?week_start={START}",
        json={"action": "DISABLE", "expected_generation": configured["target_generation"]},
    )
    enabled = await client.post(
        f"{base}/action?week_start={START}",
        json={
            "action": "ENABLE",
            "expected_generation": disabled.json()["target_generation"],
        },
    )
    await client.put(
        f"{base}?week_start={START}",
        json={"spreadsheet": "replacementAudit_12345", "replace": True},
    )
    for _ in range(5):
        assert (await client.get(f"{base}?week_start={START}")).status_code == 200
    removed = await client.post(
        f"{base}/action?week_start={START}",
        json={
            "action": "REMOVE",
            "expected_generation": enabled.json()["target_generation"] + 1,
        },
    )
    assert removed.status_code == 200
    async with app.state.session_factory() as db:
        actions = (
            await db.scalars(select(AuditEvent.action).order_by(AuditEvent.created_at))
        ).all()
    assert actions.count("accounting_mirror.configured") == 1
    assert actions.count("accounting_mirror.sync_requested") == 1
    assert actions.count("accounting_mirror.disabled") == 1
    assert actions.count("accounting_mirror.enabled") == 1
    assert actions.count("accounting_mirror.replaced") == 1
    assert actions.count("accounting_mirror.removed") == 1


async def test_mirror_routes_reject_anonymous_expired_or_inactive_manager(app, client):
    technician_id = await seed(app.state.session_factory, START)
    path = f"/api/technicians/{technician_id}/accounting/mirror?week_start={START}"
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://127.0.0.1:3000",
        headers={"Origin": "http://127.0.0.1:3000", "X-Hub-Request": "1"},
    ) as anonymous:
        assert (await anonymous.get(path)).status_code == 401
        assert (
            await anonymous.put(path, json={"spreadsheet": "unauthorized_12345"})
        ).status_code == 401
    async with app.state.session_factory() as db, db.begin():
        await db.execute(update(Manager).values(is_active=False))
    assert (await client.get(path)).status_code == 401


async def test_config_and_sync_require_exact_origin_and_csrf(app, client):
    technician_id = await seed(app.state.session_factory, START)
    await ready_google(app)
    path = f"/api/technicians/{technician_id}/accounting/mirror?week_start={START}"
    csrf = client.headers.pop("X-CSRF-Token")
    try:
        assert (await client.put(path, json={"spreadsheet": "csrfAudit_12345"})).status_code == 403
    finally:
        client.headers["X-CSRF-Token"] = csrf
    configured = await client.put(path, json={"spreadsheet": "csrfAudit_12345"})
    assert configured.status_code == 200
    action = f"/api/technicians/{technician_id}/accounting/mirror/action?week_start={START}"
    for origin in ("null", "http://127.0.0.1:3000.evil.invalid", "http://127.0.0.1:3000/path"):
        assert (
            await client.post(
                action,
                headers={"Origin": origin},
                json={
                    "action": "SYNC",
                    "expected_generation": configured.json()["target_generation"],
                },
            )
        ).status_code == 403


@pytest.mark.parametrize(
    "status,code,retryable",
    [
        (429, "RATE_LIMITED", True),
        (500, "PROVIDER_TEMPORARY_ERROR", True),
        (503, "PROVIDER_TEMPORARY_ERROR", True),
        (403, "SHEETS_PERMISSION_REQUIRED", False),
        (404, "SPREADSHEET_NOT_FOUND", False),
    ],
)
async def test_http_provider_failure_mapping_is_safe(monkeypatch, status, code, retryable):
    class Response:
        def __init__(self):
            self.status_code = status
            self.content = b"{}"
            self.headers = {"Retry-After": "180"}

        @staticmethod
        def json():
            return {"error": "TOKEN_CANARY CUSTOMER_CANARY"}

    class Session:
        trust_env = True

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        @staticmethod
        def request(*args, **kwargs):
            return Response()

    monkeypatch.setattr("hub.accounting_mirrors.provider.requests.Session", Session)
    with pytest.raises(SheetsProviderError) as captured:
        await GoogleSheetsHttpMixin().get_spreadsheet_metadata("TOKEN_CANARY", "audit_12345")
    assert captured.value.code == code
    assert captured.value.retryable is retryable
    if status == 429:
        assert captured.value.retry_after == 180
    assert "CANARY" not in str(captured.value)


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE accounting_mirror_refreshes SET lease_until=claimed_at",
        "UPDATE accounting_mirror_refreshes SET google_sheet_id=-1",
        "UPDATE accounting_mirror_refreshes SET last_success_at=clock_timestamp()",
        "UPDATE accounting_mirror_refreshes SET status='SUCCEEDED'",
    ],
)
async def test_audit_database_constraints_reject_invalid_lifecycle(app, client, sql):
    technician_id = await seed(app.state.session_factory, START)
    await ready_google(app)
    await configure(client, technician_id)
    async with app.state.session_factory() as db, db.begin():
        target = await db.scalar(select(AccountingMirrorTarget))
        await service.enqueue_target(db, target.id, START)
    current = await claim(app.state.session_factory)
    assert current
    async with app.state.session_factory() as db:
        with pytest.raises(IntegrityError):
            await db.execute(text(sql))
            await db.commit()
