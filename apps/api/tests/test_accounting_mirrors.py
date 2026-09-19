import asyncio
import inspect
import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError

from hub.accounting.xlsx import WeeklyAccountingXlsxModel
from hub.accounting_mirrors import service
from hub.accounting_mirrors.models import AccountingMirrorRefresh, AccountingMirrorTarget
from hub.accounting_mirrors.presentation import (
    all_tech_payload,
    individual_payload,
    money,
    week_title,
)
from hub.accounting_mirrors.provider import (
    ROLE_STYLES,
    SHEETS_SCOPE,
    GoogleSheetsHttpMixin,
    SheetsProviderError,
)
from hub.accounting_mirrors.worker import claim, process_claim, run_once
from hub.core.secrets import SecretCipher
from hub.google_calendar.fake import FakeCalendarProvider
from hub.google_calendar.models import CalendarConnection
from hub.google_calendar.types import SCOPE, TokenGrant
from tests.accounting_data import seed

START = date(2026, 9, 14)


async def ready_google(app):
    key = Fernet.generate_key().decode()
    app.state.settings.google_mode = "fake"
    app.state.settings.google_calendar_credential_encryption_key = SecretStr(key)
    fake = FakeCalendarProvider()
    fake.grant = TokenGrant(
        "fake-access-only", "fake-refresh-only", tuple(sorted((SCOPE, SHEETS_SCOPE)))
    )
    app.state.google_provider = fake
    async with app.state.session_factory() as db, db.begin():
        connection = CalendarConnection(
            provider="GOOGLE",
            account_key="stage9@example.invalid",
            account_label="Stage 9 fake",
            is_current=True,
            status="CONNECTED",
            generation=1,
            encrypted_refresh_token=SecretCipher(key).encrypt("fake-refresh-only"),
            granted_scopes=[SCOPE, SHEETS_SCOPE],
            connected_at=datetime.now(UTC),
        )
        db.add(connection)
    return fake


async def configure(client, technician_id, *, all_tech=False, spreadsheet="stage9Sheet_12345"):
    base = (
        "/api/accounting/weekly/all/mirror"
        if all_tech
        else f"/api/technicians/{technician_id}/accounting/mirror"
    )
    response = await client.put(
        f"{base}?week_start={START}", json={"spreadsheet": spreadsheet, "replace": False}
    )
    assert response.status_code == 200, response.text
    return base, response.json()


def test_spreadsheet_identifier_and_exact_raw_money():
    identifier = "abc_DEF-123456789"
    assert service.normalize_spreadsheet_id(identifier) == identifier
    assert (
        service.normalize_spreadsheet_id(
            f"https://docs.google.com/spreadsheets/d/{identifier}/edit#gid=0"
        )
        == identifier
    )
    assert money(Decimal("1793.16")) == "$1,793.16"
    for value in ("https://evil.invalid/spreadsheets/d/abc_DEF-123456789", "short", "a/b"):
        with pytest.raises(HTTPException):
            service.normalize_spreadsheet_id(value)


async def test_status_requires_explicit_sheets_permission(app, client):
    technician_id = await seed(app.state.session_factory, START)
    key = Fernet.generate_key().decode()
    app.state.settings.google_calendar_credential_encryption_key = SecretStr(key)
    async with app.state.session_factory() as db, db.begin():
        db.add(
            CalendarConnection(
                provider="GOOGLE",
                account_key="calendar-only@example.invalid",
                account_label="Calendar only",
                is_current=True,
                status="CONNECTED",
                generation=1,
                encrypted_refresh_token=SecretCipher(key).encrypt("refresh"),
                granted_scopes=[SCOPE],
            )
        )
    _, result = await configure(client, technician_id)
    assert result["auth_state"] == "NEEDS_PERMISSION"
    assert result["state"] == "NEEDS_PERMISSION"


async def test_manager_auth_csrf_origin_and_duplicate_week_guards(app, client):
    technician_id = await seed(app.state.session_factory, START)
    await ready_google(app)
    path = f"/api/technicians/{technician_id}/accounting/mirror?week_start={START}"
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://127.0.0.1:3000",
        headers={"Origin": "http://127.0.0.1:3000", "X-Hub-Request": "1"},
    ) as anonymous:
        assert (await anonymous.get(path)).status_code == 401
    assert (await client.get(path + f"&week_start={START}")).status_code == 422
    csrf = client.headers.pop("X-CSRF-Token")
    try:
        assert (
            await client.put(path, json={"spreadsheet": "stage9Security_12345"})
        ).status_code == 403
    finally:
        client.headers["X-CSRF-Token"] = csrf
    assert (
        await client.put(
            path,
            json={"spreadsheet": "stage9Security_12345"},
            headers={"Origin": "https://attacker.invalid"},
        )
    ).status_code == 403


async def test_individual_worker_raw_values_and_idempotent_fingerprint(app, client):
    technician_id = await seed(app.state.session_factory, START)
    fake = await ready_google(app)
    base, status = await configure(client, technician_id)
    queued = await client.post(
        f"{base}/action?week_start={START}",
        json={"action": "SYNC", "expected_generation": status["target_generation"]},
    )
    assert queued.status_code == 200 and queued.json()["state"] == "PENDING"
    assert await run_once(app.state.session_factory, app.state.settings, fake, limit=1) == [True]
    sheet = fake.inspect_sheet("stage9Sheet_12345", week_title(START))
    flattened = [cell for row in sheet["values"] for cell in row]
    assert "$1,793.16" in flattened
    assert not any(isinstance(cell, float) for cell in flattened)
    assert ("values", "RAW") in fake.sheets_calls
    calls = len(fake.sheets_calls)
    async with app.state.session_factory() as db, db.begin():
        target = await db.scalar(select(AccountingMirrorTarget))
        await service.enqueue_target(db, target.id, START)
    assert await run_once(app.state.session_factory, app.state.settings, fake, limit=1) == [True]
    assert "metadata" in fake.sheets_calls[calls:]
    assert ("values", "RAW") not in fake.sheets_calls[calls:]
    result = (await client.get(f"{base}?week_start={START}")).json()
    assert result["state"] == "SYNCED" and result["open_url"].startswith("https://docs.google.com/")


async def test_ambiguous_tab_creation_reconciles_without_duplicate(app, client):
    technician_id = await seed(app.state.session_factory, START)
    fake = await ready_google(app)
    fake.ambiguous_add_once = True
    base, status = await configure(client, technician_id)
    await client.post(
        f"{base}/action?week_start={START}",
        json={"action": "SYNC", "expected_generation": status["target_generation"]},
    )
    assert await run_once(app.state.session_factory, app.state.settings, fake, limit=1) == [False]
    async with app.state.session_factory() as db, db.begin():
        await db.execute(
            update(AccountingMirrorRefresh).values(
                retry_at=datetime.now(UTC) - timedelta(seconds=1)
            )
        )
    assert await run_once(app.state.session_factory, app.state.settings, fake, limit=1) == [True]
    assert len(fake.spreadsheets["stage9Sheet_12345"]["sheets"]) == 1


@pytest.mark.parametrize(
    "error,retry",
    [
        (SheetsProviderError("RATE_LIMITED", retryable=True, retry_after=180), True),
        (SheetsProviderError("SPREADSHEET_NOT_FOUND"), False),
        (SheetsProviderError("SHEETS_PERMISSION_REQUIRED"), False),
    ],
)
async def test_safe_provider_failure_classification(app, client, error, retry):
    technician_id = await seed(app.state.session_factory, START)
    fake = await ready_google(app)
    fake.sheets_error = error
    base, status = await configure(client, technician_id)
    await client.post(
        f"{base}/action?week_start={START}",
        json={"action": "SYNC", "expected_generation": status["target_generation"]},
    )
    assert await run_once(app.state.session_factory, app.state.settings, fake, limit=1) == [False]
    async with app.state.session_factory() as db:
        refresh = await db.scalar(select(AccountingMirrorRefresh))
        assert refresh.last_error_code == error.code
        assert (refresh.retry_at is not None) is retry
        assert "fake" not in (refresh.last_error_code or "").lower()


async def test_partial_format_failure_rebuilds_same_tab(app, client, monkeypatch):
    technician_id = await seed(app.state.session_factory, START)
    fake = await ready_google(app)
    base, status = await configure(client, technician_id)
    await client.post(
        f"{base}/action?week_start={START}",
        json={"action": "SYNC", "expected_generation": status["target_generation"]},
    )
    original = fake.batch_update_formatting
    failed = False

    async def fail_once(*args):
        nonlocal failed
        if not failed:
            failed = True
            raise SheetsProviderError("PROVIDER_TEMPORARY_ERROR", retryable=True)
        return await original(*args)

    monkeypatch.setattr(fake, "batch_update_formatting", fail_once)
    assert await run_once(app.state.session_factory, app.state.settings, fake, limit=1) == [False]
    async with app.state.session_factory() as db, db.begin():
        await db.execute(
            update(AccountingMirrorRefresh).values(
                retry_at=datetime.now(UTC) - timedelta(seconds=1)
            )
        )
    assert await run_once(app.state.session_factory, app.state.settings, fake, limit=1) == [True]
    assert fake.sheets_calls.count("add_sheet") == 1
    assert fake.sheets_calls.count(("values", "RAW")) == 2


async def test_coalescing_claims_and_stale_lease_recovery(app, client):
    technician_id = await seed(app.state.session_factory, START)
    await ready_google(app)
    await configure(client, technician_id)
    async with app.state.session_factory() as db, db.begin():
        target = await db.scalar(select(AccountingMirrorTarget))
        await service.enqueue_target(db, target.id, START)
        await service.enqueue_target(db, target.id, START)
    first = await claim(app.state.session_factory)
    assert first and first.requested_generation == 2
    assert await claim(app.state.session_factory) is None
    async with app.state.session_factory() as db, db.begin():
        await db.execute(
            update(AccountingMirrorRefresh).values(
                lease_until=datetime.now(UTC) - timedelta(seconds=1)
            )
        )
    recovered = await claim(app.state.session_factory)
    assert recovered and recovered.claim_token != first.claim_token


async def test_all_tech_grid_and_sentinel_outside_owned_range(app, client):
    technician_id = await seed(app.state.session_factory, START)
    second = await seed(app.state.session_factory, START)
    from hub.technicians.models import Technician

    async with app.state.session_factory() as db, db.begin():
        await db.execute(
            update(Technician)
            .where(Technician.id == second)
            .values(first_name="Second", last_name="Technician")
        )
    fake = await ready_google(app)
    base, status = await configure(client, technician_id, all_tech=True)
    await client.post(
        f"{base}/action?week_start={START}",
        json={"action": "SYNC", "expected_generation": status["target_generation"]},
    )
    assert await run_once(app.state.session_factory, app.state.settings, fake, limit=1) == [True]
    sheet = fake.inspect_sheet("stage9Sheet_12345", week_title(START))
    assert any("Second Technician" == cell for row in sheet["values"] for cell in row)
    owned_columns = max(len(row) for row in sheet["values"])
    sheet["values"][0].extend([""] * 3 + ["MANAGER SENTINEL"])
    async with app.state.session_factory() as db, db.begin():
        target = await db.scalar(select(AccountingMirrorTarget))
        await service.enqueue_target(db, target.id, START)
        refresh = await db.scalar(select(AccountingMirrorRefresh))
        refresh.last_successful_fingerprint = "changed"
    assert await run_once(app.state.session_factory, app.state.settings, fake, limit=1) == [True]
    assert sheet["values"][0][owned_columns + 3] == "MANAGER SENTINEL"


async def test_database_constraints_reject_bad_week_and_kind(app, client):
    technician_id = await seed(app.state.session_factory, START)
    await ready_google(app)
    await configure(client, technician_id)
    async with app.state.session_factory() as db:
        target = await db.scalar(select(AccountingMirrorTarget))
        db.add(
            AccountingMirrorRefresh(
                target_id=target.id,
                week_start=START + timedelta(days=1),
            )
        )
        with pytest.raises(IntegrityError):
            await db.commit()


async def test_target_relationship_and_singleton_constraints(app, client):
    technician_id = await seed(app.state.session_factory, START)
    await ready_google(app)
    await configure(client, technician_id)
    async with app.state.session_factory() as db:
        connection = await db.scalar(select(CalendarConnection))
    invalid = [
        {
            "kind": "INDIVIDUAL",
            "technician_id": None,
            "spreadsheet_id": "badIndividual_12345",
        },
        {
            "kind": "ALL_TECH",
            "technician_id": technician_id,
            "spreadsheet_id": "badAllTech_12345",
        },
        {
            "kind": "INDIVIDUAL",
            "technician_id": technician_id,
            "spreadsheet_id": "duplicateIndividual_12345",
        },
    ]
    for values in invalid:
        async with app.state.session_factory() as db:
            db.add(
                AccountingMirrorTarget(
                    **values,
                    google_connection_id=connection.id,
                )
            )
            with pytest.raises(IntegrityError):
                await db.commit()
    await configure(client, technician_id, all_tech=True, spreadsheet="allTechOne_12345")
    async with app.state.session_factory() as db:
        db.add(
            AccountingMirrorTarget(
                kind="ALL_TECH",
                technician_id=None,
                google_connection_id=connection.id,
                spreadsheet_id="allTechDuplicate_12345",
            )
        )
        with pytest.raises(IntegrityError):
            await db.commit()


async def test_provider_calls_happen_without_open_business_transaction(app, client, monkeypatch):
    technician_id = await seed(app.state.session_factory, START)
    fake = await ready_google(app)
    base, status = await configure(client, technician_id)
    await client.post(
        f"{base}/action?week_start={START}",
        json={"action": "SYNC", "expected_generation": status["target_generation"]},
    )
    original = fake.get_spreadsheet_metadata

    async def checked(*args):
        async with app.state.session_factory() as db:
            assert (
                await db.scalar(
                    text(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE datname = current_database() "
                        "AND state = 'idle in transaction'"
                    )
                )
                == 0
            )
        return await original(*args)

    monkeypatch.setattr(fake, "get_spreadsheet_metadata", checked)
    assert await run_once(app.state.session_factory, app.state.settings, fake, limit=1) == [True]


async def test_payload_uses_shared_week_model(app):
    technician_id = await seed(app.state.session_factory, START)
    from hub.accounting.service import calculate

    async with app.state.session_factory() as db:
        accounting = await calculate(db, technician_id, "weekly", START)
    payload = individual_payload(WeeklyAccountingXlsxModel.from_accounting(accounting))
    assert payload.title == "2026-09-14 - 2026-09-20"
    assert payload.row_count > 100 and payload.column_count == 12
    assert len(payload.fingerprint) == 64


def test_google_renderer_is_presentation_only():
    from hub.accounting_mirrors import presentation

    source = inspect.getsource(presentation)
    assert "sqlalchemy" not in source
    assert "google_calendar" not in source
    assert "SheetsProvider" not in source


def test_business_services_only_enqueue_and_never_call_google():
    from hub.expenses import service as expenses_service
    from hub.work_reports import service as work_reports_service

    for module in (expenses_service, work_reports_service):
        source = inspect.getsource(module)
        assert "GoogleSheets" not in source
        assert "google_provider" not in source
        assert "enqueue_for_business_change" in source


async def test_google_presentation_uses_canonical_totals_and_buckets(app):
    technician_id = await seed(app.state.session_factory, START)
    from hub.accounting.service import calculate

    async with app.state.session_factory() as db:
        accounting = await calculate(db, technician_id, "weekly", START)
    model = WeeklyAccountingXlsxModel.from_accounting(accounting)
    model = replace(model, totals=replace(model.totals, gross_total=Decimal("777.77")))
    flattened = [cell for row in individual_payload(model).values for cell in row]
    assert "$777.77" in flattened
    assert "Facebook" in flattened
    assert "Zelle" in flattened and "Venmo" in flattened


async def test_http_provider_uses_raw_and_shared_style_roles(monkeypatch):
    calls = []

    async def capture(self, method, path, access_token, body=None):
        calls.append((method, path, access_token, body))
        return {}

    monkeypatch.setattr(GoogleSheetsHttpMixin, "_sheets_request", capture)
    provider = GoogleSheetsHttpMixin()
    await provider.write_values(
        "access-token",
        "spreadsheet_12345",
        "2026-09-14 - 2026-09-20",
        (("=SUM(A1:A2)", "$193.01"),),
    )
    assert len(calls) == 1
    assert "valueInputOption=RAW" in calls[0][1]
    assert calls[0][3]["values"] == [["=SUM(A1:A2)", "$193.01"]]
    await provider.clear_owned_range("access-token", "spreadsheet_12345", 42, 366, 130)
    clear_requests = calls[1][3]["requests"]
    assert clear_requests[0]["updateCells"]["range"]["endRowIndex"] == 366
    assert clear_requests[0]["updateCells"]["range"]["endColumnIndex"] == 130
    assert {
        item["updateDimensionProperties"]["range"]["dimension"] for item in clear_requests[1:]
    } == {
        "ROWS",
        "COLUMNS",
    }
    assert set(ROLE_STYLES) == {
        "TECHNICIAN_TITLE",
        "WEEK_METADATA",
        "WEEK_LABEL",
        "DAY_HEADER",
        "COLUMN_HEADER",
        "JOB_CELL",
        "WRAPPED_CELL",
        "JOB_AMOUNT",
        "EXPENSE_HEADER",
        "EXPENSE_CELL",
        "EXPENSE_AMOUNT",
        "SUMMARY_CELL",
        "SUMMARY_AMOUNT",
        "SUMMARY_HEADER",
        "TOTAL_VALUE",
    }
    from hub.accounting.xlsx_styles import TECHNICIAN_TITLE, TOTAL_VALUE

    assert ROLE_STYLES["TECHNICIAN_TITLE"] is TECHNICIAN_TITLE
    assert ROLE_STYLES["TOTAL_VALUE"] is TOTAL_VALUE


async def test_long_text_and_all_tech_semantic_parity(app):
    technician_id = await seed(app.state.session_factory, START)
    from hub.accounting.service import calculate

    address = "A" * 2_000
    note = "N" * 4_000
    async with app.state.session_factory() as db:
        accounting = await calculate(db, technician_id, "weekly", START)
    model = WeeklyAccountingXlsxModel.from_accounting(accounting)
    report_day = next(index for index, day in enumerate(model.days) if day.reports)
    days = list(model.days)
    days[report_day] = replace(
        days[report_day],
        reports=(replace(days[report_day].reports[0], location=address),),
    )
    model = replace(
        model,
        days=tuple(days),
        expenses=(replace(model.expenses[0], note=note),),
    )
    individual = individual_payload(model)
    combined = all_tech_payload((model, replace(model, technician_name="Second Tech")), START)
    individual_cells = [cell for row in individual.values for cell in row]
    combined_cells = [cell for row in combined.values for cell in row]
    assert any(address in str(cell) for cell in individual_cells)
    assert note in individual_cells
    assert combined_cells.count("$1,793.16") == 2
    assert combined_cells.count(model.technician_name) == 1
    assert combined_cells.count("Second Tech") == 1
    assert combined.technician_count == 2
    assert len(json.dumps(combined.values, ensure_ascii=False).encode()) < 1_000_000


@pytest.mark.parametrize(
    "value,expected",
    [
        ("0.01", "$0.01"),
        ("193.01", "$193.01"),
        ("1793.16", "$1,793.16"),
        ("9999999999.99", "$9,999,999,999.99"),
        ("99999999999900.00", "$99,999,999,999,900.00"),
    ],
)
def test_exact_money_never_uses_binary_float(value, expected):
    rendered = money(Decimal(value))
    assert rendered == expected
    assert isinstance(rendered, str)


async def test_change_during_sync_remains_pending_then_converges(app, client):
    technician_id = await seed(app.state.session_factory, START)
    fake = await ready_google(app)
    await configure(client, technician_id)
    async with app.state.session_factory() as db, db.begin():
        target = await db.scalar(select(AccountingMirrorTarget))
        await service.enqueue_target(db, target.id, START)
    first = await claim(app.state.session_factory)
    assert first
    async with app.state.session_factory() as db, db.begin():
        await service.enqueue_target(db, first.target_id, START)
    assert await process_claim(app.state.session_factory, app.state.settings, fake, first)
    async with app.state.session_factory() as db:
        refresh = await db.scalar(select(AccountingMirrorRefresh))
        assert refresh.status == "PENDING"
        assert refresh.requested_generation == 2
        assert refresh.completed_generation == 1
    assert await run_once(app.state.session_factory, app.state.settings, fake) == [True]


@pytest.mark.parametrize("lifecycle", ["DISABLE", "REMOVE"])
async def test_lifecycle_change_during_sync_cannot_finalize_current(app, client, lifecycle):
    technician_id = await seed(app.state.session_factory, START)
    fake = await ready_google(app)
    base, configured = await configure(client, technician_id)
    await client.post(
        f"{base}/action?week_start={START}",
        json={"action": "SYNC", "expected_generation": configured["target_generation"]},
    )
    current = await claim(app.state.session_factory)
    assert current
    response = await client.post(
        f"{base}/action?week_start={START}",
        json={"action": lifecycle, "expected_generation": configured["target_generation"]},
    )
    assert response.status_code == 200
    completed = await process_claim(app.state.session_factory, app.state.settings, fake, current)
    assert completed is (lifecycle == "DISABLE")
    final = (await client.get(f"{base}?week_start={START}")).json()
    assert final["state"] == ("DISABLED" if lifecycle == "DISABLE" else "NOT_CONFIGURED")
    assert final["state"] != "SYNCED"


async def test_target_replacement_and_connection_generation_block_stale_finalize(app, client):
    technician_id = await seed(app.state.session_factory, START)
    fake = await ready_google(app)
    base, configured = await configure(client, technician_id)
    await client.post(
        f"{base}/action?week_start={START}",
        json={"action": "SYNC", "expected_generation": configured["target_generation"]},
    )
    stale = await claim(app.state.session_factory)
    assert stale
    replaced = await client.put(
        f"{base}?week_start={START}",
        json={"spreadsheet": "stage9Replacement_12345", "replace": True},
    )
    assert replaced.status_code == 200
    assert not await process_claim(app.state.session_factory, app.state.settings, fake, stale)
    assert (await client.get(f"{base}?week_start={START}")).json()["state"] == "READY"
    async with app.state.session_factory() as db, db.begin():
        target = await db.scalar(select(AccountingMirrorTarget))
        await service.enqueue_target(db, target.id, START)
    stale_connection = await claim(app.state.session_factory)
    assert stale_connection
    async with app.state.session_factory() as db, db.begin():
        connection = await db.scalar(select(CalendarConnection).with_for_update())
        connection.generation += 1
    assert await process_claim(
        app.state.session_factory, app.state.settings, fake, stale_connection
    )
    async with app.state.session_factory() as db:
        refresh = await db.scalar(select(AccountingMirrorRefresh))
        assert refresh.status == "PENDING"
        assert refresh.successful_connection_generation == stale_connection.connection_generation
    assert (await client.get(f"{base}?week_start={START}")).json()["state"] != "SYNCED"


async def test_twenty_changes_coalesce_to_one_latest_generation(app, client):
    technician_id = await seed(app.state.session_factory, START)
    await ready_google(app)
    await configure(client, technician_id)
    async with app.state.session_factory() as db, db.begin():
        for _ in range(20):
            await service.enqueue_for_business_change(db, technician_id, START)
    async with app.state.session_factory() as db:
        refreshes = (await db.scalars(select(AccountingMirrorRefresh))).all()
        assert len(refreshes) == 1
        assert refreshes[0].requested_generation == 20


@pytest.mark.parametrize("consumers", [2, 5, 10])
async def test_many_consumers_have_one_active_owner(app, client, consumers):
    technician_id = await seed(app.state.session_factory, START)
    await ready_google(app)
    await configure(client, technician_id)
    async with app.state.session_factory() as db, db.begin():
        target = await db.scalar(select(AccountingMirrorTarget))
        await service.enqueue_target(db, target.id, START)
    claims = await asyncio.gather(*(claim(app.state.session_factory) for _ in range(consumers)))
    assert sum(value is not None for value in claims) == 1


async def test_formula_text_and_scale_payloads_remain_bounded(app):
    technician_id = await seed(
        app.state.session_factory,
        START,
        reports=[dict(day=0, amount="193.01", payment_method="CASH")],
        expenses=[dict(day=0, amount="0.01")],
    )
    dangerous = "=HYPERLINK('x')\n+SUM(A1:A2)\n-WEBSERVICE('x')\n@IMPORTXML('x')"
    from hub.expenses.models import ExpenseRevision
    from hub.work_reports.models import WorkReportRevision

    async with app.state.session_factory() as db, db.begin():
        await db.execute(text("SET LOCAL session_replication_role = replica"))
        await db.execute(
            update(WorkReportRevision).values(title=dangerous, location="=cmd|' /C calc'!A0")
        )
        await db.execute(update(ExpenseRevision).values(note="=IMPORTXML('x')"))
    from hub.accounting.service import calculate

    async with app.state.session_factory() as db:
        accounting = await calculate(db, technician_id, "weekly", START)
    model = WeeklyAccountingXlsxModel.from_accounting(accounting)
    payload = individual_payload(model)
    flattened = [cell for row in payload.values for cell in row]
    assert any(dangerous in str(cell) for cell in flattened)
    assert "=IMPORTXML('x')" in flattened
    assert not any(isinstance(cell, float) for cell in flattened)
    from hub.accounting_mirrors.presentation import all_tech_payload

    for count in (1, 10, 11, 20, 21, 30, 50, 100):
        models = tuple(
            replace(model, technician_id=uuid4(), technician_name=f"Technician {index:03}")
            for index in range(count)
        )
        scaled = all_tech_payload(models, START)
        encoded = json.dumps(scaled.values, ensure_ascii=False).encode()
        assert scaled.technician_count == count
        flattened = [cell for row in scaled.values for cell in row]
        assert all(flattened.count(f"Technician {index:03}") == 1 for index in range(count))
        assert len(encoded) < 50_000_000
        assert scaled.column_count <= 130


async def test_all_tech_thirty_to_ten_shrink_clears_old_bands(app):
    technician_id = await seed(app.state.session_factory, START)
    from hub.accounting.service import calculate
    from hub.accounting_mirrors.presentation import all_tech_payload

    async with app.state.session_factory() as db:
        accounting = await calculate(db, technician_id, "weekly", START)
    model = WeeklyAccountingXlsxModel.from_accounting(accounting)
    models = tuple(
        replace(model, technician_id=uuid4(), technician_name=f"Technician {index:03}")
        for index in range(30)
    )
    old, new = all_tech_payload(models, START), all_tech_payload(models[:10], START)
    assert old.row_count > new.row_count and old.column_count == new.column_count == 130
    fake = FakeCalendarProvider()
    sheet = await fake.add_sheet(
        "access", "shrinkBook_12345", old.title, old.row_count, old.column_count
    )
    await fake.write_values("access", "shrinkBook_12345", old.title, old.values)
    await fake.batch_update_formatting(
        "access", "shrinkBook_12345", sheet.sheet_id, old, sheet.rows, sheet.columns
    )
    remote = fake.inspect_sheet("shrinkBook_12345", old.title)
    remote["values"][0].extend([""] * 3 + ["OUTSIDE SENTINEL"])
    await fake.clear_owned_range(
        "access",
        "shrinkBook_12345",
        sheet.sheet_id,
        max(old.row_count, new.row_count),
        max(old.column_count, new.column_count),
    )
    await fake.write_values("access", "shrinkBook_12345", new.title, new.values)
    await fake.batch_update_formatting(
        "access", "shrinkBook_12345", sheet.sheet_id, new, old.row_count, old.column_count
    )
    assert remote["values"][0][old.column_count + 3] == "OUTSIDE SENTINEL"
    assert not any(
        cell
        for row in remote["values"][new.row_count : old.row_count]
        for cell in row[: old.column_count]
    )


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE accounting_mirror_targets SET kind='BAD'",
        "UPDATE accounting_mirror_targets SET generation=0",
        "UPDATE accounting_mirror_refreshes SET status='BAD'",
        "UPDATE accounting_mirror_refreshes SET owned_rows=-1",
        "UPDATE accounting_mirror_refreshes SET completed_generation=requested_generation+1",
        "UPDATE accounting_mirror_refreshes SET status='PROCESSING'",
    ],
)
async def test_direct_sql_guards(app, client, sql):
    technician_id = await seed(app.state.session_factory, START)
    await ready_google(app)
    await configure(client, technician_id)
    async with app.state.session_factory() as db, db.begin():
        target = await db.scalar(select(AccountingMirrorTarget))
        await service.enqueue_target(db, target.id, START)
    async with app.state.session_factory() as db:
        with pytest.raises(IntegrityError):
            await db.execute(text(sql))
            await db.commit()
