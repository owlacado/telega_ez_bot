"""Independent adversarial checks for the approved pilot-policy boundary."""

import asyncio
import os
import subprocess
import time
from datetime import date, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from hub.audit.models import AuditEvent
from hub.auth.models import RateBucket
from hub.auth.security import now, rate_limit
from hub.core.config import Settings
from hub.expenses.models import ExpenseRevision, TechnicianExpense
from hub.ops.service import cleanup_expired
from hub.technicians.models import Technician
from hub.work_reports.models import WorkReport, WorkReportRevision
from tests.accounting_data import seed
from tests.test_api import calendar, create


async def _version(engine, identifier: UUID) -> int:
    async with engine.connect() as db:
        return await db.scalar(select(Technician.record_version).where(Technician.id == identifier))


async def test_record_version_profile_once_rollback_and_concurrent_serialization(client, engine):
    profile = await create(client)
    identifier = UUID(profile["id"])

    async with engine.begin() as db:
        await db.execute(
            text("UPDATE technicians SET first_name='First' WHERE id=:id"), {"id": identifier}
        )
        await db.execute(
            text("UPDATE technicians SET last_name='Second' WHERE id=:id"), {"id": identifier}
        )
    assert await _version(engine, identifier) == 2

    connection = await engine.connect()
    transaction = await connection.begin()
    try:
        await connection.execute(
            text("UPDATE technicians SET first_name='Rolled Back' WHERE id=:id"),
            {"id": identifier},
        )
        assert (
            await connection.scalar(
                select(Technician.record_version).where(Technician.id == identifier)
            )
            == 3
        )
    finally:
        await transaction.rollback()
        await connection.close()
    assert await _version(engine, identifier) == 2

    first, second = await engine.connect(), await engine.connect()
    first_tx, second_tx = await first.begin(), await second.begin()
    try:
        await first.execute(
            text("UPDATE technicians SET first_name='Concurrent One' WHERE id=:id"),
            {"id": identifier},
        )
        blocked = asyncio.create_task(
            second.execute(
                text("UPDATE technicians SET last_name='Concurrent Two' WHERE id=:id"),
                {"id": identifier},
            )
        )
        await asyncio.sleep(0.1)
        assert not blocked.done()
        await first_tx.commit()
        await blocked
        await second_tx.commit()
    finally:
        if first_tx.is_active:
            await first_tx.rollback()
        if second_tx.is_active:
            await second_tx.rollback()
        await first.close()
        await second.close()
    assert await _version(engine, identifier) == 4


async def test_record_version_tracks_only_effective_readiness_changes(client, engine):
    profile = await create(client)
    demo = await calendar(client, "Audit version boundary")
    identifier, calendar_id = UUID(profile["id"]), UUID(demo["id"])
    assigned = await client.put(
        f"/api/technicians/{identifier}/calendar", json={"calendar_id": str(calendar_id)}
    )
    assert assigned.status_code == 200
    baseline = await _version(engine, identifier)

    async with engine.begin() as db:
        await db.execute(
            text(
                "UPDATE calendar_assignments SET calendar_name='Historical label only' "
                "WHERE technician_id=:id AND is_active"
            ),
            {"id": identifier},
        )
        await db.execute(
            text(
                "INSERT INTO telegram_bindings "
                "(technician_id, private_status, group_status, private_generation, "
                "group_generation, private_availability, group_availability) "
                "VALUES (:id, 'NOT_CONNECTED', 'NOT_CONNECTED', 0, 0, 'UNKNOWN', 'UNKNOWN')"
            ),
            {"id": identifier},
        )
        await db.execute(
            text(
                "INSERT INTO schedule_delivery_settings (technician_id, enabled) "
                "VALUES (:id, false)"
            ),
            {"id": identifier},
        )
    assert await _version(engine, identifier) == baseline

    async with engine.begin() as db:
        await db.execute(
            text("UPDATE calendars SET availability='UNAVAILABLE' WHERE id=:calendar"),
            {"calendar": calendar_id},
        )
        await db.execute(
            text(
                "UPDATE telegram_bindings SET private_status='PENDING', "
                "private_generation=1, bot_id=9000001 WHERE technician_id=:id"
            ),
            {"id": identifier},
        )
        await db.execute(
            text("UPDATE schedule_delivery_settings SET enabled=true WHERE technician_id=:id"),
            {"id": identifier},
        )
    assert await _version(engine, identifier) == baseline + 1

    async with engine.begin() as db:
        await db.execute(
            text("UPDATE calendars SET name='Display label only' WHERE id=:calendar"),
            {"calendar": calendar_id},
        )
        await db.execute(
            text(
                "UPDATE telegram_bindings SET private_display_name='Display only' "
                "WHERE technician_id=:id"
            ),
            {"id": identifier},
        )
    assert await _version(engine, identifier) == baseline + 1
    assert (await client.get(f"/api/technicians/{identifier}")).json()["record_version"] == (
        baseline + 1
    )


async def test_record_version_google_connection_lifecycle_and_identity_guard(client, engine):
    profile = await create(client)
    identifier = UUID(profile["id"])
    connection_id, calendar_id = uuid4(), uuid4()
    async with engine.begin() as db:
        await db.execute(
            text(
                "INSERT INTO calendar_connections "
                "(id, provider, account_key, account_label, is_current, status, generation, "
                "encrypted_refresh_token, granted_scopes) "
                "VALUES (:connection, 'GOOGLE', 'audit-account', 'Audit', true, "
                "'CONNECTED', 1, 'v1:synthetic', '[]'::jsonb)"
            ),
            {"connection": connection_id},
        )
        await db.execute(
            text(
                "INSERT INTO calendars "
                "(id, name, source, provider_connection_id, provider_calendar_id, availability) "
                "VALUES (:calendar, 'Audit Google', 'GOOGLE', :connection, "
                "'audit-calendar', 'AVAILABLE')"
            ),
            {"calendar": calendar_id, "connection": connection_id},
        )
        await db.execute(
            text(
                "INSERT INTO calendar_assignments "
                "(id, technician_id, calendar_id, calendar_name, is_active) "
                "VALUES (:assignment, :technician, :calendar, 'Audit Google', true)"
            ),
            {
                "assignment": uuid4(),
                "technician": identifier,
                "calendar": calendar_id,
            },
        )
    assert await _version(engine, identifier) == 2

    async with engine.begin() as db:
        await db.execute(
            text(
                "UPDATE calendar_connections SET status='REAUTH_REQUIRED', "
                "generation=2, granted_scopes='[\"scope\"]'::jsonb WHERE id=:id"
            ),
            {"id": connection_id},
        )
        await db.execute(
            text("UPDATE calendars SET availability='UNAVAILABLE' WHERE id=:id"),
            {"id": calendar_id},
        )
    assert await _version(engine, identifier) == 3

    async with engine.begin() as db:
        await db.execute(
            text("UPDATE calendar_connections SET account_label='Display only' WHERE id=:id"),
            {"id": connection_id},
        )
    assert await _version(engine, identifier) == 3

    with pytest.raises(IntegrityError, match="TECHNICIAN_ID_DATABASE_OWNED"):
        async with engine.begin() as db:
            await db.execute(
                text("UPDATE technicians SET id=:replacement WHERE id=:id"),
                {"replacement": uuid4(), "id": identifier},
            )


async def test_legacy_pilot_profile_values_are_preserved_but_cannot_be_replaced(engine):
    identifier = uuid4()
    async with engine.begin() as db:
        await db.execute(
            text("ALTER TABLE technicians DISABLE TRIGGER trg_technicians_pilot_guard")
        )
        await db.execute(
            text(
                "INSERT INTO technicians "
                "(id, first_name, last_name, status, photo_url, driver_license_id, ssn_last4) "
                "VALUES (:id, 'Legacy', 'Synthetic', 'ACTIVE', 'https://legacy.invalid/a', "
                "'LEGACY-ID', '0123')"
            ),
            {"id": identifier},
        )
        await db.execute(text("ALTER TABLE technicians ENABLE TRIGGER trg_technicians_pilot_guard"))
        await db.execute(
            text("UPDATE technicians SET first_name='Still Legacy' WHERE id=:id"),
            {"id": identifier},
        )
        values = (
            await db.execute(
                text(
                    "SELECT photo_url, driver_license_id, ssn_last4, record_version "
                    "FROM technicians WHERE id=:id"
                ),
                {"id": identifier},
            )
        ).one()
        assert values == ("https://legacy.invalid/a", "LEGACY-ID", "0123", 2)
    with pytest.raises(IntegrityError, match="PILOT_PROFILE_DATA_COLLECTION_DISABLED"):
        async with engine.begin() as db:
            await db.execute(
                text("UPDATE technicians SET ssn_last4='9999' WHERE id=:id"),
                {"id": identifier},
            )


async def test_exact_admission_defaults_boundaries_and_concurrency(engine):
    settings = Settings(_env_file=None)
    assert (
        settings.telegram_sender_minute_limit,
        settings.telegram_sender_burst_limit,
        settings.telegram_sender_burst_seconds,
        settings.telegram_global_minute_limit,
        settings.telegram_processed_update_retention_days,
    ) == (30, 10, 10, 300, 7)
    assert (
        settings.google_oauth_manager_limit,
        settings.google_oauth_manager_window_seconds,
        settings.google_oauth_global_limit,
        settings.google_oauth_global_window_seconds,
        settings.google_manual_manager_limit,
        settings.google_manual_manager_window_seconds,
        settings.google_manual_global_limit,
        settings.google_manual_global_window_seconds,
        settings.google_oauth_attempt_retention_days,
    ) == (5, 900, 20, 3600, 6, 600, 30, 3600, 7)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    for key, limit, seconds in (
        ("audit:telegram:sender-minute", 30, 60),
        ("audit:telegram:sender-burst", 10, 10),
        ("audit:telegram:global", 300, 60),
        ("audit:google:oauth-manager", 5, 900),
        ("audit:google:oauth-global", 20, 3600),
        ("audit:google:manual-manager", 6, 600),
        ("audit:google:manual-global", 30, 3600),
    ):
        async with factory() as db, db.begin():
            for _ in range(limit):
                await rate_limit(db, key, limit=limit, seconds=seconds)
            with pytest.raises(HTTPException) as rejected:
                await rate_limit(db, key, limit=limit, seconds=seconds)
            assert rejected.value.status_code == 429

    async def contend() -> bool:
        async with factory() as db, db.begin():
            try:
                await rate_limit(db, "audit:concurrent", limit=10, seconds=60)
            except HTTPException as exc:
                assert exc.status_code == 429
                return False
            return True

    results = await asyncio.gather(*[contend() for _ in range(25)])
    assert sum(results) == 10
    async with factory() as db:
        bucket = await db.scalar(
            select(RateBucket)
            .where(RateBucket.key_hash.is_not(None))
            .order_by(RateBucket.window_start.desc())
        )
        assert bucket is not None


async def test_cleanup_never_deletes_business_revisions_or_audit_history(app):
    technician_id = await seed(
        app.state.session_factory,
        date(2024, 1, 1),
        reports=[{"day": 0, "amount": "10.00", "payment_method": "CASH"}],
        expenses=[{"day": 0, "amount": "5.00"}],
    )
    async with app.state.session_factory() as db, db.begin():
        db.add(
            AuditEvent(
                actor_kind="SYSTEM",
                action="audit.retention.synthetic",
                target_id=technician_id,
                outcome="SUCCESS",
                created_at=now() - timedelta(days=400),
            )
        )
    models = (WorkReport, WorkReportRevision, TechnicianExpense, ExpenseRevision, AuditEvent)
    async with app.state.session_factory() as db:
        before = [await db.scalar(select(func.count()).select_from(model)) for model in models]
    async with app.state.session_factory() as db, db.begin():
        await cleanup_expired(db, apply=True, batch_size=1000, settings=app.state.settings)
    async with app.state.session_factory() as db:
        after = [await db.scalar(select(func.count()).select_from(model)) for model in models]
    assert after == before and all(value > 0 for value in after)


def test_generated_contracts_and_frontend_contain_no_pilot_write_fields():
    root = Path(__file__).resolve().parents[3]
    contract_text = "\n".join(
        (root / path).read_text(encoding="utf-8")
        for path in ("packages/contracts/openapi.json", "packages/contracts/src/schema.d.ts")
    )
    for forbidden in ("photo_url", "driver_license_id", "ssn_last4"):
        assert forbidden not in contract_text
    web_source = "\n".join(
        path.read_text(encoding="utf-8") for path in (root / "apps/web/src").rglob("*.tsx")
    )
    assert "photo_url" not in web_source and "<img" not in web_source


def test_backup_rotation_removes_only_expired_script_owned_artifacts(tmp_path):
    root = Path(__file__).resolve().parents[3]
    output = tmp_path / "backups"
    output.mkdir()
    old_owned = [
        output / "technician-hub-20240101T000000Z-deadbeef.dump",
        output / "technician-hub-20240101T000000Z-deadbeef.dump.json",
    ]
    preserved = [
        output / "operator-notes.txt",
        output / "technician-hub-20240101T000000Z-deadbeef.dump.extra",
        output / "other-product-20240101.dump",
    ]
    recent_owned = output / "technician-hub-20990101T000000Z-cafebabe.dump"
    for path in [*old_owned, *preserved, recent_owned]:
        path.write_text("synthetic", encoding="utf-8")
    old_time = time.time() - 40 * 86400
    for path in [*old_owned, *preserved]:
        os.utime(path, (old_time, old_time))

    script = root / "scripts/backup-postgres.ps1"
    harness = tmp_path / "backup-harness.ps1"
    harness.write_text(
        "function global:docker {\n"
        "  $global:LASTEXITCODE = 0\n"
        "  if ($args[0] -eq 'compose' -and $args -contains 'ps') "
        "{ Write-Output 'synthetic-container'; return }\n"
        "  if ($args[0] -eq 'cp') "
        "{ Set-Content -LiteralPath $args[-1] -Value 'synthetic-dump'; return }\n"
        "}\n"
        f"& '{script}' -OutputDirectory '{output}' -RetentionDays 30\n",
        encoding="utf-8",
    )
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert not any(path.exists() for path in old_owned)
    assert all(path.exists() for path in preserved)
    assert recent_owned.exists()
    created = [
        path for path in output.glob("technician-hub-*.dump") if path.name != recent_owned.name
    ]
    assert len(created) == 1 and created[0].with_suffix(".dump.json").exists()
