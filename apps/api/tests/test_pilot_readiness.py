"""Stage 10 pilot-readiness, operations, cleanup, and configuration tests."""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from hub.audit.models import AuditEvent
from hub.auth.models import ManagerSession
from hub.auth.service import create_manager
from hub.core.config import Settings
from hub.expenses.models import ExpenseRevision
from hub.google_calendar.models import GoogleOAuthAttempt
from hub.integrations.models import GpsBinding, TelegramBinding
from hub.main import create_app
from hub.ops import cli as ops_cli
from hub.ops.cli import FINGERPRINT_TABLES
from hub.ops.service import _worker_component, cleanup_expired
from hub.work_reports.models import TechnicianFormSession, WorkReportRevision
from tests.accounting_data import seed
from tests.conftest import TEST_URL
from tests.fakes import BOT_ID
from tests.test_expenses import patch_technician


async def create_technician(client):
    response = await client.post(
        "/api/technicians",
        json={"first_name": "Pilot", "last_name": "Fictional"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def requirement(profile, key):
    return next(item for item in profile["pilot_readiness"]["requirements"] if item["key"] == key)


async def test_canonical_readiness_combinations(app, client):
    profile = await create_technician(client)
    identifier = UUID(profile["id"])
    assert profile["pilot_readiness"]["ready"] is False
    assert profile["pilot_readiness"]["blocking_count"] == 3
    assert requirement(profile, "telegram_group")["status"] == "OPTIONAL"
    assert requirement(profile, "google_sheets_mirror")["status"] == "OPTIONAL"

    response = await patch_technician(
        client, identifier, accounting_timezone="America/Los_Angeles"
    )
    assert response.status_code == 200
    timezone_only = response.json()
    assert requirement(timezone_only, "accounting_timezone")["status"] == "READY"

    async with app.state.session_factory() as db, db.begin():
        db.add(
            TelegramBinding(
                technician_id=identifier,
                telegram_user_id=771001,
                bot_id=BOT_ID,
                private_status="CONNECTED",
                private_availability="AVAILABLE",
                private_generation=1,
            )
        )
    telegram_only = (await client.get(f"/api/technicians/{identifier}")).json()
    assert requirement(telegram_only, "telegram_private")["status"] == "READY"
    calendar = (await client.post("/api/calendars", json={"name": "Pilot local"})).json()
    assert (
        await client.put(
            f"/api/technicians/{identifier}/calendar", json={"calendar_id": calendar["id"]}
        )
    ).status_code == 200
    ready = (await client.get(f"/api/technicians/{identifier}")).json()
    assert ready["pilot_readiness"]["ready"] is True
    assert requirement(ready, "google_events")["status"] == "OPTIONAL"

    app.state.settings.schedule_delivery_enabled = True
    schedule_required = (await client.get(f"/api/technicians/{identifier}")).json()
    assert schedule_required["pilot_readiness"]["ready"] is False
    assert requirement(schedule_required, "telegram_group")["status"] == "NEEDS_ACTION"
    app.state.settings.schedule_delivery_enabled = False
    inactive = await patch_technician(client, identifier, status="INACTIVE")
    assert requirement(inactive.json(), "profile")["status"] == "BLOCKED"


async def test_profile_update_rejects_stale_version(client):
    profile = await create_technician(client)
    first = await client.patch(
        f"/api/technicians/{profile['id']}",
        json={"expected_updated_at": profile["updated_at"], "first_name": "First"},
    )
    assert first.status_code == 200
    stale = await client.patch(
        f"/api/technicians/{profile['id']}",
        json={"expected_updated_at": profile["updated_at"], "last_name": "Lost"},
    )
    assert stale.status_code == 409
    current = (await client.get(f"/api/technicians/{profile['id']}")).json()
    assert current["first_name"] == "First" and current["last_name"] == "Fictional"


async def test_operations_health_is_manager_only_and_truthful(app, client):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://127.0.0.1:3000"
    ) as anonymous:
        assert (await anonymous.get("/api/operations/health")).status_code == 401
    response = await client.get("/api/operations/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "PASS"
    assert body["database"]["state"] == "PASS"
    assert body["migration"]["state"] == "PASS"
    assert body["telegram_worker"]["state"] == "DISABLED"
    assert body["schedule_worker"]["state"] == "DISABLED"
    assert body["mirror_worker"]["state"] == "DISABLED"
    assert set(body["queues"]) == {"telegram", "schedule", "mirror"}


async def test_public_health_fails_closed_when_database_is_down():
    unavailable = create_app(
        Settings(
            _env_file=None,
            database_url=(
                "postgresql+asyncpg://hub:synthetic-secret@127.0.0.1:1/"
                "technician_hub_test"
            ),
            app_env="test",
            allowed_origins=["http://127.0.0.1:3000"],
        )
    )
    async with unavailable.router.lifespan_context(unavailable):
        async with AsyncClient(
            transport=ASGITransport(app=unavailable), base_url="http://127.0.0.1:3000"
        ) as probe:
            response = await probe.get("/api/health")
    assert response.status_code == 503


@pytest.mark.parametrize(
    "changes",
    [
        {"debug": True},
        {"telegram_mode": "fake"},
        {"google_mode": "fake"},
        {"allowed_origins": ["https://*"]},
        {"database_url": "postgresql+asyncpg://hub:hub_local_only@db/hub"},
    ],
)
def test_production_configuration_fails_closed(changes):
    values = {
        "_env_file": None,
        "database_url": "postgresql+asyncpg://hub:unique-production-secret@db/technician_hub",
        "app_env": "production",
        "cookie_secure": True,
        "allowed_origins": ["https://pilot.example.test"],
        **changes,
    }
    with pytest.raises(ValidationError):
        Settings(**values)


def test_schedule_configuration_requires_google():
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            database_url=TEST_URL,
            app_env="test",
            allowed_origins=["http://127.0.0.1:3000"],
            schedule_delivery_enabled=True,
            schedule_payload_encryption_key="1ajUDMfGL53YFA8iShNsP-xjjA0YvMk_0QPLePP2uKs=",
            telegram_mode="fake",
            telegram_expected_bot_id=BOT_ID,
            google_mode="disabled",
        )


def test_stale_enabled_worker_is_not_reported_running():
    assert _worker_component("RUNNING", False, disabled=False).state == "STALE"
    assert _worker_component("RUNNING", True, disabled=False).state == "RUNNING"
    assert _worker_component("RUNNING", True, disabled=True).state == "DISABLED"


def test_fingerprint_inventory_covers_restore_critical_data():
    assert {
        "managers",
        "technicians",
        "calendars",
        "telegram_bindings",
        "work_reports",
        "work_report_revisions",
        "technician_expenses",
        "expense_revisions",
        "accounting_mirror_targets",
        "accounting_mirror_refreshes",
        "telegram_outbox",
        "audit_events",
    } <= set(FINGERPRINT_TABLES)


def test_normal_compose_retains_canonical_named_volume_and_safe_backup_drill():
    root = Path(__file__).resolve().parents[3]
    compose = (root / "compose.yaml").read_text(encoding="utf-8")
    drill = (root / "scripts" / "verify_backup_restore.py").read_text(encoding="utf-8")
    assert "postgres_data:/var/lib/postgresql" in compose
    assert "postgres_data:" in compose
    assert 'DATABASE_NAME = "technician_hub_restore_test"' in drill
    assert 'compose("down", "-v", "--remove-orphans")' in drill
    assert "technician_hub" not in drill.replace("technician_hub_restore_test", "")


async def test_preflight_blocks_zero_manager_and_schema_mismatch(engine, capsys, monkeypatch):
    settings = Settings(
        _env_file=None,
        database_url=TEST_URL,
        app_env="test",
        allowed_origins=["http://127.0.0.1:3000"],
    )
    assert await ops_cli.preflight(settings) == 2
    assert "BLOCK manager" in capsys.readouterr().out
    async with async_sessionmaker(engine)() as db:
        await create_manager(db, "pilot-manager", "synthetic-password-long")
    assert await ops_cli.preflight(settings) == 0
    ready_output = capsys.readouterr().out
    assert "BLOCK" not in ready_output
    assert "hub_test_only" not in ready_output
    monkeypatch.setattr(ops_cli, "EXPECTED_ALEMBIC_HEAD", "missing-head")
    assert await ops_cli.preflight(settings) == 2
    output = capsys.readouterr().out
    assert "BLOCK migration" in output
    assert "synthetic-password-long" not in output


async def test_preflight_database_failure_is_sanitized(capsys):
    settings = Settings(
        _env_file=None,
        database_url=(
            "postgresql+asyncpg://hub:preflight-secret-canary@127.0.0.1:1/"
            "technician_hub_test"
        ),
        app_env="test",
        allowed_origins=["http://127.0.0.1:3000"],
    )
    assert await ops_cli.preflight(settings) == 2
    output = capsys.readouterr().out
    assert "BLOCK database" in output
    assert "preflight-secret-canary" not in output


async def test_cleanup_is_bounded_idempotent_and_preserves_business(app, client):
    start = date(2026, 9, 14)
    technician_id = await seed(app.state.session_factory, start)
    stamp = datetime.now(UTC)
    async with app.state.session_factory() as db, db.begin():
        manager_session = await db.scalar(select(ManagerSession))
        expired = TechnicianFormSession(
            technician_id=technician_id,
            purpose="WORK_REPORT",
            token_hash="a" * 64,
            status="OPEN",
            telegram_user_id=771001,
            bot_id=BOT_ID,
            binding_generation=1,
            created_at=stamp - timedelta(hours=2),
            expires_at=stamp - timedelta(hours=1),
            choices=[{"private": "snapshot"}],
            selected={"private": "snapshot"},
        )
        fresh = TechnicianFormSession(
            technician_id=technician_id,
            purpose="EXPENSE",
            token_hash="b" * 64,
            status="OPEN",
            telegram_user_id=771001,
            bot_id=BOT_ID,
            binding_generation=1,
            created_at=stamp,
            expires_at=stamp + timedelta(minutes=15),
            choices=[{"fresh": True}],
        )
        db.add_all(
            [
                expired,
                fresh,
                GoogleOAuthAttempt(
                    state_hash="c" * 64,
                    manager_id=manager_session.manager_id,
                    session_id=manager_session.id,
                    encrypted_verifier="v1:synthetic-ciphertext",
                    expires_at=stamp - timedelta(minutes=1),
                    mode="CONNECT",
                ),
            ]
        )
    async with app.state.session_factory() as db:
        before = (
            await db.scalar(select(func.count()).select_from(WorkReportRevision)),
            await db.scalar(select(func.count()).select_from(ExpenseRevision)),
            await db.scalar(select(func.count()).select_from(AuditEvent)),
        )
        dry = await cleanup_expired(db, apply=False, batch_size=1)
        await db.rollback()
        assert dry.expired_form_snapshots == 1
    async with app.state.session_factory() as db, db.begin():
        applied = await cleanup_expired(db, apply=True, batch_size=100)
        assert applied.expired_form_snapshots == 1
        assert applied.expired_oauth_verifiers == 1
    async with app.state.session_factory() as db, db.begin():
        old = await db.get(TechnicianFormSession, expired.id)
        current = await db.get(TechnicianFormSession, fresh.id)
        oauth = await db.scalar(select(GoogleOAuthAttempt))
        assert old.status == "EXPIRED" and old.choices is None and old.selected is None
        assert current.status == "OPEN" and current.choices == [{"fresh": True}]
        assert oauth.encrypted_verifier is None
        again = await cleanup_expired(db, apply=True)
        assert again.expired_form_snapshots == again.expired_oauth_verifiers == 0
        after = (
            await db.scalar(select(func.count()).select_from(WorkReportRevision)),
            await db.scalar(select(func.count()).select_from(ExpenseRevision)),
            await db.scalar(select(func.count()).select_from(AuditEvent)),
        )
        assert after == before


async def test_provider_state_constraints_reject_impossible_rows(app, client):
    profile = await create_technician(client)
    identifier = UUID(profile["id"])
    async with app.state.session_factory() as db:
        with pytest.raises(IntegrityError):
            async with db.begin():
                db.add(
                    TelegramBinding(
                        technician_id=identifier,
                        private_status="CONNECTED",
                        private_availability="AVAILABLE",
                    )
                )
    async with app.state.session_factory() as db:
        with pytest.raises(IntegrityError):
            async with db.begin():
                db.add(
                    GpsBinding(
                        technician_id=identifier,
                        provider="NONE",
                        status="CONNECTED",
                    )
                )
