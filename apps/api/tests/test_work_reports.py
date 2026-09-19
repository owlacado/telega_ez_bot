"""Stage 5 PostgreSQL, fake providers, and adversarial submission contracts."""

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
from sqlalchemy.exc import IntegrityError

from hub.audit.models import AuditEvent
from hub.auth.security import now
from hub.integrations.models import TelegramBinding
from hub.technicians.models import Technician
from hub.telegram.types import TrustedEvent
from hub.telegram.updates import process_update
from hub.work_reports import service
from hub.work_reports.models import TechnicianFormSession, WorkReport, WorkReportRevision
from hub.work_reports.schemas import ReportInput
from tests.fakes import BOT_ID, FakeTelegram
from tests.test_calendar_events import assigned as assigned
from tests.test_calendar_events import item
from tests.test_google_calendar import google as google

BASE = "/api/technician-forms/work-report"
PAYLOAD = dict(
    amount_closed="850.10",
    payment_method="CASH",
    closed_by="MYSELF",
    comments="PRIVATE_NOTES <script>alert(1)</script> 😀\u202e",
    yearly_maintenance_plan_provided=True,
    reviews=dict(GOOGLE=2, GROUPON=1, FACEBOOK=3),
)


@pytest.fixture
async def ready(app, client, assigned, google):
    tid = UUID(assigned[0]["id"])
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
    google.events = [
        item(location="ADDRESS_CANARY", description="DESCRIPTION_CANARY"),
        item("fake", title="fake job"),
        item("cancel", status="cancelled"),
    ]
    return tid


async def issue(app, user=771001, **changes):
    event = TrustedEvent(
        100, "COMMAND", chat_id=user, user_id=user, chat_type="private", command="/report"
    )
    async with app.state.session_factory() as db, db.begin():
        return await service.issue(db, replace(event, **changes), BOT_ID, app.state.settings)


async def opened(app, client, token=None):
    token = token or await issue(app)
    headers = {"Authorization": f"Bearer {token}"}
    response = await client.post(BASE, headers=headers)
    assert response.status_code == 200, response.text
    return token, headers, response.json()


async def selected(app, client, token=None):
    token, headers, form = await opened(app, client, token)
    response = await client.post(
        BASE + "/select", headers=headers, json={"choice_id": form["jobs"][0]["choice_id"]}
    )
    assert response.status_code == 200, response.text
    return token, headers, form


async def counts(app):
    async with app.state.session_factory() as db:
        return tuple(
            [
                await db.scalar(select(func.count()).select_from(model))
                for model in (WorkReport, WorkReportRevision)
            ]
        )


async def test_full_flow_snapshot_privacy_receipt_manager_retention(
    app, client, ready, google, caplog
):
    caplog.set_level(logging.INFO)
    token, headers, form = await selected(app, client)
    assert len(form["jobs"]) == 1
    assert "provider_event_id" not in str(form) and "DESCRIPTION_CANARY" not in str(form)
    async with app.state.session_factory() as db:
        session = await db.scalar(select(TechnicianFormSession))
        assert session.token_hash == service.digest(token) and session.token_hash != token
        assert token not in str(session.__dict__)
    google.events = []  # Subsequent provider state cannot rewrite selected work.
    result = await client.post(BASE + "/submit", headers=headers, json=PAYLOAD)
    assert result.status_code == 200, result.text
    assert result.headers["cache-control"] == "no-store"
    assert (
        await client.post(BASE + "/submit", headers=headers, json=PAYLOAD)
    ).json() == result.json()
    changed = await client.post(
        BASE + "/submit", headers=headers, json={**PAYLOAD, "amount_closed": "1.00"}
    )
    assert changed.status_code == 409 and "FORM_ALREADY_SUBMITTED" in changed.text
    assert await counts(app) == (1, 1)
    reports = await client.get(f"/api/technicians/{ready}/work-reports")
    report = reports.json()["reports"][0]
    assert report["amount_closed"] == "850.10" and report["reviews"] == PAYLOAD["reviews"]
    assert report["operational_date"] == "2026-09-17" and report["revision_number"] == 1
    assert "\u202e" not in report["comments"] and report["yearly_maintenance_plan_provided"]
    assert report["location"] == "ADDRESS_CANARY"
    assert (await client.get(f"/api/work-reports/{report['id']}")).json() == report
    profile = (await client.get(f"/api/technicians/{ready}")).json()
    deleted = await client.request(
        "DELETE",
        f"/api/technicians/{ready}",
        json={"confirmation": "DELETE", "expected_updated_at": profile["updated_at"]},
    )
    assert deleted.status_code == 409 and "business records" in deleted.text
    assert (
        await client.patch(f"/api/technicians/{ready}", json={"status": "INACTIVE"})
    ).status_code == 200
    assert (await client.get(f"/api/work-reports/{report['id']}")).status_code == 200
    assert (await client.post(BASE, headers=headers)).status_code == 410
    assert (
        token not in caplog.text
        and "PRIVATE_NOTES" not in caplog.text
        and "ADDRESS_CANARY" not in caplog.text
    )
    async with app.state.session_factory() as db:
        events = (
            await db.scalars(select(AuditEvent).where(AuditEvent.action.like("work_report.%")))
        ).all()
        assert len(events) == 2
        assert "PRIVATE_NOTES" not in str([e.__dict__ for e in events])


@pytest.mark.parametrize(
    "method",
    ["CASH", "ZELLE", "CHECK", "CREDIT_CARD", "CASH_APP", "VENMO", "SUPER", "ESTIMATE", "CANCEL"],
)
def test_exact_legacy_payment_and_money(method):
    value = ReportInput(**{**PAYLOAD, "payment_method": method})
    assert isinstance(value.amount_closed, Decimal)
    assert value.amount_closed == Decimal("0.00" if method in {"ESTIMATE", "CANCEL"} else "850.10")
    assert value.payment_method == ("CREDIT_CARD" if method == "CASH_APP" else method)


@pytest.mark.parametrize(
    "value",
    [
        -1,
        1.25,
        True,
        "NaN",
        "Infinity",
        "-1",
        "1e2",
        "1.001",
        "10000000000",
        "",
        " ",
        "١٠",
        "0.10000000000000001",
    ],
)
def test_money_rejects_invalid_and_float(value):
    with pytest.raises(ValidationError):
        ReportInput(**{**PAYLOAD, "amount_closed": value})


@pytest.mark.parametrize(
    "extra",
    [
        {"technician_id": str(uuid4())},
        {"calendar_id": str(uuid4())},
        {"event_id": "spoof"},
        {"title": "spoof"},
        {"closed_by": "OTHER"},
        {"payment_method": "OTHER"},
        {"comments": "x" * 4001},
        {"reviews": dict(GOOGLE=101, GROUPON=0, FACEBOOK=0)},
        {"reviews": dict(GOOGLE=True, GROUPON=0, FACEBOOK=0)},
        {"reviews": dict(GOOGLE=0, GROUPON=0, FACEBOOK=0, YELP=2)},
    ],
)
async def test_payload_spoof_and_bounds(app, client, ready, extra):
    _, headers, _ = await selected(app, client)
    assert (
        await client.post(BASE + "/submit", headers=headers, json={**PAYLOAD, **extra})
    ).status_code == 422
    assert await counts(app) == (0, 0)


@pytest.mark.parametrize(
    "change",
    [
        dict(user_id=2),
        dict(chat_type="group"),
        dict(chat_id=2),
        dict(user_is_bot=True),
        dict(anonymous=True),
    ],
)
async def test_issue_requires_trusted_private_actor(app, ready, change):
    assert await issue(app, **change) is None


async def test_two_sessions_twenty_race_and_lost_response(app, client, ready):
    token, _, _ = await selected(app, client)
    second, _, _ = await selected(app, client)
    payload = ReportInput(**PAYLOAD)
    results = await asyncio.gather(
        *(service.submit(app.state.session_factory, token, payload) for _ in range(20))
    )
    assert len({r.report_id for r in results}) == 1
    with pytest.raises(HTTPException, match="already has"):
        await service.submit(app.state.session_factory, second, payload)
    assert await counts(app) == (1, 1)


@pytest.mark.parametrize("mutation", ["expire", "revoke", "rebind", "inactive", "disconnect"])
async def test_invalidated_form_fails_closed(app, client, ready, mutation):
    _, headers, _ = await selected(app, client)
    async with app.state.session_factory() as db, db.begin():
        if mutation == "expire":
            await db.execute(
                update(TechnicianFormSession).values(
                    created_at=now() - timedelta(hours=1), expires_at=now() - timedelta(seconds=1)
                )
            )
        elif mutation == "revoke":
            await db.execute(update(TechnicianFormSession).values(status="REVOKED"))
        elif mutation == "inactive":
            await db.execute(
                update(Technician).where(Technician.id == ready).values(status="INACTIVE")
            )
        else:
            await db.execute(
                update(TelegramBinding)
                .where(TelegramBinding.technician_id == ready)
                .values(
                    private_generation=2, telegram_user_id=771002 if mutation == "rebind" else None
                )
            )
    assert (await client.post(BASE + "/submit", headers=headers, json=PAYLOAD)).status_code == 410
    assert await counts(app) == (0, 0)


async def test_unlisted_job_no_jobs_and_manager_cookie_not_capability(app, client, ready, google):
    assert (await client.post(BASE)).status_code == 410
    _, headers, _ = await opened(app, client)
    assert (
        await client.post(BASE + "/select", headers=headers, json={"choice_id": str(uuid4())})
    ).status_code == 410
    google.events = []
    _, _, form = await opened(app, client)
    assert form["jobs"] == []


async def test_snapshot_outage_reassignment_midnight(app, client, ready, google, monkeypatch):
    _, headers, form = await selected(app, client)
    from hub.google_calendar.types import ProviderError

    google.error = ProviderError("PROVIDER_TEMPORARY_ERROR")
    calls_before = len(google.calls)
    assert (await client.delete(f"/api/technicians/{ready}/calendar")).status_code == 204
    # 23:58 -> 00:03 in the job calendar's America/New_York timezone.
    before_midnight = datetime(2026, 9, 18, 3, 58, tzinfo=UTC)
    async with app.state.session_factory() as db, db.begin():
        await db.execute(
            update(TechnicianFormSession).values(
                created_at=before_midnight, expires_at=before_midnight + timedelta(minutes=15)
            )
        )

    async def database_clock(db):
        return before_midnight + timedelta(minutes=5)

    monkeypatch.setattr(service, "database_now", database_clock)
    result = await client.post(BASE + "/submit", headers=headers, json=PAYLOAD)
    assert result.status_code == 200, result.text
    report = (await client.get(f"/api/work-reports/{result.json()['report_id']}")).json()
    assert report["operational_date"] == form["jobs"][0]["operational_date"]
    assert len(google.calls) == calls_before


@pytest.mark.parametrize("payment", ["ESTIMATE", "CANCEL"])
async def test_malicious_nonzero_outcome_persists_zero(app, client, ready, payment):
    _, headers, _ = await selected(app, client)
    response = await client.post(
        BASE + "/submit",
        headers=headers,
        json={**PAYLOAD, "payment_method": payment, "amount_closed": "999.99"},
    )
    assert response.status_code == 200
    async with app.state.session_factory() as db:
        revision = await db.scalar(select(WorkReportRevision))
        assert revision.payment_method == payment
        assert revision.amount_closed == Decimal("0.00")


async def test_duplicate_json_fields_rejected(app, client, ready):
    token = await issue(app)
    response = await client.post(
        BASE + "/submit",
        headers={"Authorization": f"Bearer {token}"},
        content='{"reviews":{"GOOGLE":1,"GOOGLE":2}}',
    )
    assert response.status_code == 422
    assert await counts(app) == (0, 0)


async def test_recurrence_instances_independent(app, client, ready, google):
    google.events = [
        item(
            "instance-a",
            recurringEventId="series",
            originalStartTime={"dateTime": "2026-09-17T08:00:00-04:00"},
        ),
        item(
            "instance-b",
            hour="12:00",
            recurringEventId="series",
            originalStartTime={"dateTime": "2026-09-17T12:00:00-04:00"},
        ),
    ]
    token, headers, form = await selected(app, client)
    assert (await client.post(BASE + "/submit", headers=headers, json=PAYLOAD)).status_code == 200
    _, second_headers, second = await opened(app, client)
    assert second["jobs"][0]["submitted"]
    assert (
        await client.post(
            BASE + "/select",
            headers=second_headers,
            json={"choice_id": second["jobs"][1]["choice_id"]},
        )
    ).status_code == 200
    assert (
        await client.post(BASE + "/submit", headers=second_headers, json=PAYLOAD)
    ).status_code == 200
    assert await counts(app) == (2, 2)


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE work_report_revisions SET amount_closed=0",
        "DELETE FROM work_report_revisions",
        "UPDATE work_reports SET occurrence_key=repeat('x',64)",
        "DELETE FROM technicians",
        "UPDATE technician_form_sessions SET payload_hash=repeat('x',64)",
    ],
)
async def test_direct_sql_immutable_history_and_retention(app, client, ready, sql):
    _, headers, _ = await selected(app, client)
    assert (await client.post(BASE + "/submit", headers=headers, json=PAYLOAD)).status_code == 200
    with pytest.raises(IntegrityError):
        async with app.state.session_factory() as db, db.begin():
            await db.execute(text(sql))
    assert await counts(app) == (1, 1)


async def test_rollback_before_commit_recoverable_and_no_confirmation_coupling(
    app, client, ready, monkeypatch
):
    token, headers, _ = await selected(app, client)
    original_audit = service.audit

    def crash(*args, **kwargs):
        raise RuntimeError("test interruption")

    monkeypatch.setattr(service, "audit", crash)
    with pytest.raises(RuntimeError):
        await service.submit(app.state.session_factory, token, ReportInput(**PAYLOAD))
    assert await counts(app) == (0, 0)
    monkeypatch.setattr(service, "audit", original_audit)
    assert (await client.post(BASE + "/submit", headers=headers, json=PAYLOAD)).status_code == 200
    assert await counts(app) == (1, 1)


async def test_bot_command_deduplicated_and_no_secret_repr(app, ready):
    event = TrustedEvent(
        200, "COMMAND", user_id=771001, chat_id=771001, chat_type="private", command="/report"
    )
    result = await process_update(
        app.state.session_factory, FakeTelegram(), event, BOT_ID, settings=app.state.settings
    )
    assert result.outcome == "WORK_REPORT_FORM" and "#" in result.reply
    assert result.reply not in repr(result)
    duplicate = await process_update(
        app.state.session_factory, FakeTelegram(), event, BOT_ID, settings=app.state.settings
    )
    assert duplicate.outcome == "DUPLICATE"


async def test_manager_auth_body_limit_and_no_test_routes(app, client, ready):
    token = await issue(app)
    client.cookies.clear()
    assert (
        await client.get(
            f"/api/technicians/{ready}/work-reports", headers={"Authorization": f"Bearer {token}"}
        )
    ).status_code == 401
    assert (
        await client.post(
            BASE + "/submit", headers={"Authorization": f"Bearer {token}"}, content="x" * 33000
        )
    ).status_code == 413
    assert not any(
        any(word in path for word in ("fake", "simulate", "debug"))
        for path in app.openapi()["paths"]
    )
