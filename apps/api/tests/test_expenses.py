"PostgreSQL expense security, financial integrity and concurrency tests; no live providers."

import asyncio
import logging
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import DBAPIError

from hub.audit.models import AuditEvent
from hub.expenses import service
from hub.expenses.models import ExpenseRevision, TechnicianExpense
from hub.expenses.schemas import ExpenseInput
from hub.integrations.models import TelegramBinding
from hub.technicians.models import Technician
from hub.telegram.transport import parse_update
from hub.telegram.types import TrustedEvent
from hub.telegram.updates import process_update
from hub.work_reports import service as forms
from hub.work_reports.models import TechnicianFormSession
from tests.fakes import BOT_ID, BOT_USERNAME, FakeTelegram

BASE = "/api/technician-forms/expense"
PAYLOAD = {
    "expense_type": "Home Depot materials",
    "amount": "47.23",
    "note": "PRIVATE_EXPENSE_CANARY <script>alert(1)</script>",
}


@pytest.fixture
async def ready(app, client):
    tech = (
        await client.post(
            "/api/technicians", json={"first_name": "Expense", "last_name": "Fictional"}
        )
    ).json()
    tid = UUID(tech["id"])
    response = await client.patch(
        f"/api/technicians/{tid}", json={"accounting_timezone": "America/Los_Angeles"}
    )
    assert response.status_code == 200, response.text
    async with app.state.session_factory() as db, db.begin():
        db.add(
            TelegramBinding(
                technician_id=tid,
                telegram_user_id=771001,
                bot_id=BOT_ID,
                private_status="CONNECTED",
                private_availability="AVAILABLE",
                private_generation=1,
            )
        )
    return tid


async def issue(app, **changes):
    event = TrustedEvent(
        100, "COMMAND", chat_id=771001, user_id=771001, chat_type="private", command="/expenses"
    )
    async with app.state.session_factory() as db, db.begin():
        return await service.issue(db, replace(event, **changes), BOT_ID, app.state.settings)


async def send(app, token, payload=None):
    return await service.submit(
        app.state.session_factory, token, ExpenseInput(**(payload or PAYLOAD))
    )


async def counts(app):
    async with app.state.session_factory() as db:
        return tuple(
            [
                await db.scalar(select(func.count()).select_from(m))
                for m in (TechnicianExpense, ExpenseRevision)
            ]
        )


async def test_complete_flow_privacy_manager_retention(app, client, ready, caplog):
    caplog.set_level(logging.INFO)
    token = await issue(app)
    headers = {"Authorization": f"Bearer {token}"}
    opened = await client.post(BASE, headers=headers)
    assert opened.status_code == 200, opened.text
    assert opened.json()["accounting_timezone"] == "America/Los_Angeles"
    assert token not in opened.text
    async with app.state.session_factory() as db:
        value = await db.scalar(select(TechnicianFormSession))
        assert value.token_hash == forms.digest(token) and value.purpose == "EXPENSE"
        assert value.expires_at - value.created_at == timedelta(
            seconds=app.state.settings.work_report_session_seconds
        )
    result = await client.post(BASE + "/submit", headers=headers, json=PAYLOAD)
    assert result.status_code == 200, result.text
    assert (
        await client.post(BASE + "/submit", headers=headers, json=PAYLOAD)
    ).json() == result.json()
    assert (
        await client.post(BASE + "/submit", headers=headers, json={**PAYLOAD, "amount": "2.00"})
    ).status_code == 409
    listing = await client.get(f"/api/technicians/{ready}/expenses")
    assert listing.status_code == 200, listing.text
    data = listing.json()
    assert data["today_total"] == "47.23" and data["today_count"] == 1
    assert data["expenses"][0]["revision_number"] == 1
    detail = await client.get(f"/api/expenses/{result.json()['expense_id']}")
    assert detail.json() == data["expenses"][0]
    for response in (opened, result, listing, detail):
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["referrer-policy"] == "no-referrer"
        assert token not in response.text and forms.digest(token) not in response.text
    profile = (await client.get(f"/api/technicians/{ready}")).json()
    deleted = await client.request(
        "DELETE",
        f"/api/technicians/{ready}",
        json={"confirmation": "DELETE", "expected_updated_at": profile["updated_at"]},
    )
    assert deleted.status_code == 409
    await client.patch(f"/api/technicians/{ready}", json={"status": "INACTIVE"})
    assert (await client.get(f"/api/expenses/{result.json()['expense_id']}")).status_code == 200
    assert (await client.post(BASE + "/submit", headers=headers, json=PAYLOAD)).status_code == 410
    async with app.state.session_factory() as db:
        audits = str([r.__dict__ for r in (await db.scalars(select(AuditEvent))).all()])
    for secret in (token, forms.digest(token), PAYLOAD["note"], PAYLOAD["expense_type"]):
        assert secret not in caplog.text and secret not in audits


@pytest.mark.parametrize("amount", ["0", "0.01", "9999999999.99", "47.23"])
async def test_money_exact_database(app, ready, amount):
    result = await send(app, await issue(app), {**PAYLOAD, "amount": amount})
    async with app.state.session_factory() as db:
        row = await db.scalar(
            select(ExpenseRevision).where(ExpenseRevision.expense_id == result.expense_id)
        )
        assert row.amount == Decimal(amount) and isinstance(row.amount, Decimal)


@pytest.mark.parametrize(
    "amount",
    [
        "-1",
        "-0.01",
        "NaN",
        "Infinity",
        "1e2",
        1.2,
        0,
        True,
        "1,00",
        "1.001",
        "10000000000.00",
        "１２",
        " 1.00 ",
        ".01",
        "1.",
    ],
)
def test_money_rejected(amount):
    with pytest.raises(ValidationError):
        ExpenseInput(**{**PAYLOAD, "amount": amount})


@pytest.mark.parametrize(
    "kind", ["", " ", "<script>", "Gas\nParking", "Gas\x00", "Gas\u202e", "x" * 101]
)
def test_invalid_types(kind):
    with pytest.raises(ValidationError):
        ExpenseInput(**{**PAYLOAD, "expense_type": kind})


@pytest.mark.parametrize(
    "kind", ["Gas", "Parking", "Toll", "Tools", "Misc", "Home Depot materials", "Ä費用"]
)
def test_free_text_preserves_case(kind):
    assert ExpenseInput(**{**PAYLOAD, "expense_type": f"  {kind}  "}).expense_type == kind


def test_note_plain_text_bounded():
    assert (
        ExpenseInput(**{**PAYLOAD, "note": "  <script>\n*text*\u202e\x01  "}).note
        == "<script>\n*text*"
    )
    with pytest.raises(ValidationError):
        ExpenseInput(**{**PAYLOAD, "note": "x" * 4001})


@pytest.mark.parametrize(
    "field,value",
    [
        ("technician_id", str(uuid4())),
        ("expense_date", "2020-01-01"),
        ("accounting_timezone", "UTC"),
        ("receipt_url", "javascript:alert(1)"),
        ("category", "GAS"),
    ],
)
async def test_no_client_identity_date_receipt(app, client, ready, field, value):
    response = await client.post(
        BASE + "/submit",
        headers={"Authorization": f"Bearer {await issue(app)}"},
        json={**PAYLOAD, field: value},
    )
    assert response.status_code == 422 and await counts(app) == (0, 0)


@pytest.mark.parametrize(
    "changes",
    [
        {"chat_type": "group"},
        {"user_id": 9911},
        {"user_is_bot": True},
        {"anonymous": True},
        {"chat_id": -771001},
        {"kind": "CALLBACK"},
    ],
)
async def test_wrong_actor(app, ready, changes):
    assert await issue(app, **changes) is None


async def test_manager_cookie_not_capability_and_purpose_isolation(app, client, ready):
    assert (await client.post(BASE + "/submit", json=PAYLOAD)).status_code == 410
    expense_token = await issue(app)
    assert (
        await client.post(
            "/api/technician-forms/work-report",
            headers={"Authorization": f"Bearer {expense_token}"},
        )
    ).status_code == 410
    event = TrustedEvent(100, "COMMAND", chat_id=771001, user_id=771001, chat_type="private")
    async with app.state.session_factory() as db, db.begin():
        token = await forms.issue(db, event, BOT_ID, app.state.settings)
    assert (
        await client.post(BASE, headers={"Authorization": f"Bearer {token}"})
    ).status_code == 410
    client.cookies.clear()
    assert (
        await client.get(
            f"/api/technicians/{ready}/expenses",
            headers={"Authorization": f"Bearer {expense_token}"},
        )
    ).status_code == 401
    assert (
        await client.post(
            BASE + "/submit", headers={"Authorization": f"Bearer {expense_token}"}, json=PAYLOAD
        )
    ).status_code == 200


@pytest.mark.parametrize("change", ["expiry", "rebind", "inactive", "revoke"])
async def test_stale_session_rejected(app, ready, change):
    token = await issue(app)
    async with app.state.session_factory() as db, db.begin():
        if change == "expiry":
            await db.execute(
                text(
                    "UPDATE technician_form_sessions SET "
                    "created_at=clock_timestamp()-interval '2 hours', "
                    "expires_at=clock_timestamp()-interval '1 hour'"
                )
            )
        elif change == "rebind":
            await db.execute(update(TelegramBinding).values(private_generation=2))
        elif change == "inactive":
            await db.execute(update(Technician).values(status="INACTIVE"))
        else:
            await db.execute(update(TechnicianFormSession).values(status="REVOKED"))
    with pytest.raises(HTTPException) as error:
        await send(app, token)
    assert error.value.status_code == 410
    assert await counts(app) == (0, 0)


async def test_missing_timezone_and_admission(app, client, ready):
    for _ in range(8):
        await issue(app)
    async with app.state.session_factory() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(TechnicianFormSession)
                .where(TechnicianFormSession.status == "OPEN")
            )
            == 5
        )
    assert (
        await client.patch(f"/api/technicians/{ready}", json={"accounting_timezone": "Not/AZone"})
    ).status_code == 422
    token = await issue(app)
    await client.patch(f"/api/technicians/{ready}", json={"accounting_timezone": None})
    assert await issue(app) is None
    with pytest.raises(HTTPException) as error:
        await send(app, token)
    assert error.value.status_code == 409


@pytest.mark.parametrize(
    "instant,zone,day",
    [
        ("2026-08-21T06:59:59+00:00", "America/Los_Angeles", "2026-08-20"),
        ("2026-08-21T07:00:00+00:00", "America/Los_Angeles", "2026-08-21"),
        ("2026-03-08T10:01:00+00:00", "America/Los_Angeles", "2026-03-08"),
        ("2026-11-01T09:01:00+00:00", "America/Los_Angeles", "2026-11-01"),
        ("2026-08-21T23:30:00+00:00", "Asia/Tokyo", "2026-08-22"),
    ],
)
def test_date_timezone_dst(instant, zone, day):
    assert service.local_date(datetime.fromisoformat(instant), zone).isoformat() == day


async def test_submit_date_not_issue_date_and_receipt_after_expiry(app, ready, monkeypatch):
    instant = datetime(2030, 8, 21, 6, 59, tzinfo=UTC)

    async def clock(db):
        return instant

    monkeypatch.setattr(forms, "database_now", clock)
    token = await issue(app)
    opened = await service.open_form(app.state.session_factory, token)
    assert opened.expense_date.isoformat() == "2030-08-20"
    instant += timedelta(minutes=2)
    result = await send(app, token)
    async with app.state.session_factory() as db:
        revision = await db.scalar(select(ExpenseRevision))
        assert revision.expense_date.isoformat() == "2030-08-21"
        assert revision.submitted_at == instant
    instant += timedelta(hours=2)
    assert (await send(app, token)).expense_id == result.expense_id


async def test_concurrent_20_identical_and_two_real_same_value(app, ready):
    token = await issue(app)
    results = await asyncio.gather(*(send(app, token) for _ in range(20)))
    assert len({r.expense_id for r in results}) == 1
    assert await counts(app) == (1, 1)
    other = await send(app, await issue(app))
    assert other.expense_id != results[0].expense_id
    assert await counts(app) == (2, 2)


@pytest.mark.parametrize("action", ["inactive", "rebind", "delete"])
async def test_lifecycle_lock_race(app, ready, action):
    token = await issue(app)
    async with app.state.session_factory() as db, db.begin():
        await db.get(Technician, ready, with_for_update=True)
        task = asyncio.create_task(send(app, token))
        await asyncio.sleep(0.05)
        assert not task.done()
        if action == "inactive":
            await db.execute(update(Technician).values(status="INACTIVE"))
        elif action == "rebind":
            await db.execute(update(TelegramBinding).values(private_generation=2))
        else:
            await db.execute(text("DELETE FROM technicians WHERE id=:id"), {"id": ready})
    with pytest.raises(HTTPException):
        await task
    assert await counts(app) == (0, 0)


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE expense_revisions SET amount=2",
        "DELETE FROM expense_revisions",
        "UPDATE technician_expenses SET technician_id=gen_random_uuid()",
        "DELETE FROM technician_expenses",
        "DELETE FROM technicians",
    ],
)
async def test_history_immutable_direct_sql(app, ready, sql):
    await send(app, await issue(app))
    with pytest.raises(DBAPIError):
        async with app.state.session_factory() as db, db.begin():
            await db.execute(text(sql))
    assert await counts(app) == (1, 1)


@pytest.mark.parametrize(
    "field,value",
    [
        ("amount", "-0.01"),
        ("amount", "NaN"),
        ("expense_type", ""),
        ("expense_type", "<b>Gas</b>"),
        ("note", "x" * 4001),
        ("revision_number", 2),
        ("accounting_timezone", "Bad/Zone"),
        ("expense_date", "2000-01-01"),
    ],
)
async def test_database_constraints(app, ready, field, value):
    await send(app, await issue(app))
    async with app.state.session_factory() as db:
        rev = await db.scalar(select(ExpenseRevision))
        fields = {c.name: getattr(rev, c.name) for c in ExpenseRevision.__table__.columns}
    fields.update(id=uuid4(), expense_id=uuid4(), **{field: value})
    if field == "expense_date":
        fields[field] = datetime.fromisoformat(value).date()
    if field == "amount":
        fields[field] = Decimal(value)
    with pytest.raises(DBAPIError):
        async with app.state.session_factory() as db, db.begin():
            db.add(TechnicianExpense(id=fields["expense_id"], technician_id=ready))
            await db.flush()
            db.add(ExpenseRevision(**fields))
    assert await counts(app) == (1, 1)


@pytest.mark.parametrize(
    "assignment",
    [
        "status='INVALID'",
        "purpose='BAD'",
        "status='SUBMITTED'",
        "submitted_at=clock_timestamp()",
        "payload_hash='abc'",
    ],
)
async def test_partial_session_db(app, ready, assignment):
    await issue(app)
    with pytest.raises(DBAPIError):
        async with app.state.session_factory() as db, db.begin():
            await db.execute(text(f"UPDATE technician_form_sessions SET {assignment}"))


async def test_list_total_not_truncated_and_manager_during_submit(app, client, ready):
    for _ in range(22):
        await send(app, await issue(app))
    listing = (await client.get(f"/api/technicians/{ready}/expenses?limit=2")).json()
    assert len(listing["expenses"]) == 2 and listing["today_count"] == 22
    assert Decimal(listing["today_total"]) == Decimal("47.23") * 22
    token = await issue(app)
    result, response = await asyncio.gather(
        send(app, token), client.get(f"/api/technicians/{ready}/expenses")
    )
    assert response.status_code == 200
    data = response.json()
    assert Decimal(data["today_total"]) == Decimal("47.23") * data["today_count"]
    assert data["today_count"] in {22, 23}


async def test_http_size_and_errors_private(app, client, ready, monkeypatch, caplog):
    token = await issue(app)
    headers = {"Authorization": f"Bearer {token}"}
    response = await client.post(
        BASE + "/submit", headers=headers, json={**PAYLOAD, "note": "x" * 40000}
    )
    assert response.status_code == 413

    async def broken(*args):
        raise RuntimeError(PAYLOAD["note"] + token)

    monkeypatch.setattr(service, "submit", broken)
    response = await client.post(BASE + "/submit", headers=headers, json=PAYLOAD)
    assert response.status_code == 500 and response.headers["cache-control"] == "no-store"
    assert (
        token not in caplog.text + response.text
        and PAYLOAD["note"] not in caplog.text + response.text
    )


async def test_telegram_expenses_entry(app, ready):
    result = await process_update(
        app.state.session_factory,
        FakeTelegram(),
        TrustedEvent(
            987, "COMMAND", chat_id=771001, user_id=771001, chat_type="private", command="/expenses"
        ),
        BOT_ID,
        settings=app.state.settings,
    )
    assert result.outcome == "EXPENSE_FORM" and "/technician/expense#" in result.reply
    for command in ("Expenses", "/expenses"):
        event = parse_update(
            {
                "update_id": 988,
                "message": {
                    "message_id": 1,
                    "text": command,
                    "chat": {"id": 771001, "type": "private"},
                    "from": {"id": 771001, "is_bot": False},
                },
            },
            BOT_USERNAME,
        )
        assert event.command == "/expenses"


def test_money_never_converted_through_float():
    from decimal import FloatOperation, localcontext

    with localcontext() as context:
        context.traps[FloatOperation] = True
        assert ExpenseInput(**{**PAYLOAD, "amount": "9999999999.99"}).amount == Decimal(
            "9999999999.99"
        )


async def test_expense_revoke_scope(app, client, ready):
    token = await issue(app)
    async with app.state.session_factory() as db:
        session = await db.scalar(select(TechnicianFormSession))
    assert (
        await client.post(f"/api/technicians/{ready}/work-report-sessions/{session.id}/revoke")
    ).status_code == 404
    assert (
        await client.post(f"/api/technicians/{ready}/expense-sessions/{session.id}/revoke")
    ).status_code == 204
    with pytest.raises(HTTPException):
        await send(app, token)


async def test_orphan_duplicate_future_revision_and_session_owner(app, ready):
    result = await send(app, await issue(app))
    async with app.state.session_factory() as db:
        row = await db.scalar(select(ExpenseRevision))
        values = {c.name: getattr(row, c.name) for c in ExpenseRevision.__table__.columns}
    for replacement in (
        {"id": uuid4()},
        {"id": uuid4(), "revision_number": 2},
        {"id": uuid4(), "expense_id": uuid4()},
    ):
        with pytest.raises(DBAPIError):
            async with app.state.session_factory() as db, db.begin():
                db.add(ExpenseRevision(**{**values, **replacement}))
    with pytest.raises(DBAPIError):
        async with app.state.session_factory() as db, db.begin():
            db.add(TechnicianExpense(technician_id=ready))
    # Valid parent FKs are insufficient: the session must own this expense.
    with pytest.raises(DBAPIError):
        async with app.state.session_factory() as db, db.begin():
            other = Technician(first_name="Other", last_name="Fictional")
            db.add(other)
            await db.flush()
            db.add(
                TechnicianFormSession(
                    technician_id=other.id,
                    purpose="EXPENSE",
                    token_hash="b" * 64,
                    status="SUBMITTED",
                    telegram_user_id=100,
                    bot_id=BOT_ID,
                    binding_generation=1,
                    expires_at=datetime.now(UTC) + timedelta(minutes=15),
                    expense_id=result.expense_id,
                    payload_hash="a" * 64,
                    submitted_at=datetime.now(UTC),
                )
            )
    assert await counts(app) == (1, 1)


async def test_latest_only_selector_uses_current_revision(app, client, ready):
    instant = datetime.now(UTC)
    async with app.state.session_factory() as db, db.begin():
        expense = TechnicianExpense(id=uuid4(), technician_id=ready, current_revision_number=2)
        db.add(expense)
        await db.flush()
        for number, amount in ((1, "10.00"), (2, "20.00")):
            db.add(
                ExpenseRevision(
                    expense_id=expense.id,
                    revision_number=number,
                    technician_name="Fictional",
                    expense_date=service.local_date(instant, "America/Los_Angeles"),
                    accounting_timezone="America/Los_Angeles",
                    expense_type="Parking",
                    amount=Decimal(amount),
                    note="Synthetic future history selector",
                    submitted_at=instant,
                )
            )
    response = await client.get(f"/api/technicians/{ready}/expenses")
    assert response.status_code == 200
    assert response.json()["today_total"] == "20.00"
    assert response.json()["today_count"] == 1
    assert response.json()["expenses"][0]["revision_number"] == 2
