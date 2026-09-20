"""Destructive schema checks run ONLY on the local disposable test database."""

import asyncio
import os
import subprocess
import sys
import uuid
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

root = Path(__file__).resolve().parents[1]
url = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://hub:hub_test_only@127.0.0.1:5437/technician_hub_test"
)
parsed = make_url(url)
if parsed.database != "technician_hub_test" or parsed.host not in {
    "127.0.0.1",
    "localhost",
    "test-db",
}:
    raise SystemExit("Refusing migration checks outside local technician_hub_test.")
env = {**os.environ, "DATABASE_URL": url}


def alembic(*arguments):
    subprocess.run(
        [sys.executable, "-m", "alembic", *arguments], cwd=root / "apps/api", env=env, check=True
    )


tech, calendar, assignment = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


async def fixture(check=False):
    engine = create_async_engine(url, hide_parameters=True)
    try:
        async with engine.begin() as db:
            if check:
                row = (
                    await db.execute(
                        text("SELECT id,first_name,status FROM technicians WHERE id=:id"),
                        {"id": tech},
                    )
                ).one()
                assert row == (tech, "Migration fixture", "ACTIVE")
                assert (
                    await db.scalar(
                        text("SELECT name FROM calendars WHERE id=:id"), {"id": calendar}
                    )
                    == "Migration fixture calendar"
                )
                assert (
                    await db.scalar(
                        text("SELECT calendar_id FROM calendar_assignments WHERE id=:id"),
                        {"id": assignment},
                    )
                    == calendar
                )
                assert (
                    await db.scalar(
                        text(
                            "SELECT telegram_group_chat_id FROM telegram_bindings "
                            "WHERE technician_id=:id"
                        ),
                        {"id": tech},
                    )
                    == -1001234567890
                )
                assert (
                    await db.scalar(
                        text("SELECT count(*) FROM gps_bindings WHERE technician_id=:id"),
                        {"id": tech},
                    )
                    == 1
                )
            else:
                await db.execute(
                    text(
                        "INSERT INTO technicians (id,first_name,last_name) "
                        "VALUES (:id,'Migration fixture','Fictional')"
                    ),
                    {"id": tech},
                )
                await db.execute(
                    text(
                        "INSERT INTO calendars (id,name) VALUES (:id,'Migration fixture calendar')"
                    ),
                    {"id": calendar},
                )
                await db.execute(
                    text(
                        "INSERT INTO calendar_assignments "
                        "(id,technician_id,calendar_id,calendar_name) "
                        "VALUES (:id,:tech,:cal,'Migration fixture calendar')"
                    ),
                    {"id": assignment, "tech": tech, "cal": calendar},
                )
                await db.execute(
                    text(
                        "INSERT INTO telegram_bindings "
                        "(technician_id,telegram_user_id,telegram_group_chat_id) "
                        "VALUES (:id,1234567890,-1001234567890)"
                    ),
                    {"id": tech},
                )
                await db.execute(
                    text("INSERT INTO gps_bindings (technician_id) VALUES (:id)"), {"id": tech}
                )
    finally:
        await engine.dispose()


alembic("upgrade", "head")


async def reset_stage2_test_fixtures():
    # This script already requires a disposable, local test DB and drops all schema below.
    engine = create_async_engine(url, hide_parameters=True)
    try:
        async with engine.begin() as db:
            if await db.scalar(text("SELECT to_regclass('calendar_connections')")):
                await db.execute(
                    text("TRUNCATE calendar_connections, google_oauth_attempts CASCADE")
                )
    finally:
        await engine.dispose()


asyncio.run(reset_stage2_test_fixtures())


# This script is already destructive and guarded to the disposable TEST database.
# Remove audit test history explicitly before exercising historical rollback paths.
async def clear_test_delivery_history():
    engine = create_async_engine(url, hide_parameters=True)
    try:
        async with engine.begin() as db:
            if await db.scalar(text("SELECT to_regclass('technician_expenses')")):
                await db.execute(
                    text(
                        "TRUNCATE technician_form_sessions, expense_revisions, technician_expenses"
                    )
                )
                await db.execute(text("UPDATE technicians SET accounting_timezone=NULL"))
            if await db.scalar(text("SELECT to_regclass('work_reports')")):
                await db.execute(
                    text("TRUNCATE technician_form_sessions, work_report_revisions, work_reports")
                )
            if await db.scalar(text("SELECT to_regclass('schedule_dispatches')")):
                await db.execute(
                    text("TRUNCATE schedule_dispatches, schedule_auto_decisions CASCADE")
                )
    finally:
        await engine.dispose()


asyncio.run(clear_test_delivery_history())
alembic("downgrade", "base")
alembic("upgrade", "head")
alembic("check")
print("Fresh database upgrade and drift passed.")
alembic("downgrade", "base")
alembic("upgrade", "863590d3075e")
asyncio.run(fixture())
alembic("upgrade", "head")
asyncio.run(fixture(check=True))
alembic("downgrade", "863590d3075e")
asyncio.run(fixture(check=True))
alembic("upgrade", "head")
asyncio.run(fixture(check=True))
alembic("check")
alembic("current")
print("Stage 0 data preserved through Stage 1 upgrade / downgrade / upgrade.")


async def stage1_record(seed=False):
    engine = create_async_engine(url, hide_parameters=True)
    try:
        async with engine.begin() as db:
            if seed:
                await db.execute(
                    text(
                        "INSERT INTO managers (id,username,password_hash) "
                        "VALUES (:id,'migration-sentinel','not-a-valid-login-hash')"
                    ),
                    {"id": tech},
                )
                await db.execute(
                    text(
                        "INSERT INTO audit_events "
                        "(id,actor_id,actor_kind,action,target_id,outcome) "
                        "VALUES (:id,:target,'MANAGER','migration.sentinel',:target,'SUCCESS')"
                    ),
                    {"id": calendar, "target": tech},
                )
            else:
                assert (
                    await db.scalar(
                        text("SELECT username FROM managers WHERE id=:id"), {"id": tech}
                    )
                    == "migration-sentinel"
                )
                assert (
                    await db.scalar(
                        text("SELECT action FROM audit_events WHERE id=:id"), {"id": calendar}
                    )
                    == "migration.sentinel"
                )
    finally:
        await engine.dispose()


# Preserve independently installed Stage 1 and audited Stage 0 databases.
alembic("downgrade", "base")
alembic("upgrade", "4344e0e76774")
asyncio.run(fixture())
asyncio.run(stage1_record(seed=True))
alembic("upgrade", "head")
asyncio.run(fixture(check=True))
asyncio.run(stage1_record())
alembic("downgrade", "4344e0e76774")
asyncio.run(fixture(check=True))
asyncio.run(stage1_record())
alembic("upgrade", "head")
asyncio.run(stage1_record())
alembic("downgrade", "base")
alembic("upgrade", "a04e70c92001")
asyncio.run(fixture())
alembic("upgrade", "head")
asyncio.run(fixture(check=True))
alembic("check")
print("Existing Stage 1 and audited Stage 0 upgrade paths and Stage 1 data preservation passed.")


async def completion_fixture(seed=False, upgraded=True):
    engine = create_async_engine(url, hide_parameters=True)
    try:
        async with engine.begin() as db:
            if seed:
                await db.execute(
                    text(
                        "INSERT INTO telegram_invitations "
                        "(id,technician_id,bot_id,purpose,token_hash,expected_generation,"
                        "expected_private_generation,expires_at,created_by_manager_id) "
                        "VALUES (:id,:tech,9000001,'PRIVATE_ACCOUNT',:hash,0,0,"
                        "now()+interval '15 minutes',:tech)"
                    ),
                    {"id": assignment, "tech": tech, "hash": "0" * 64},
                )
                await db.execute(
                    text(
                        "INSERT INTO telegram_outbox "
                        "(id,technician_id,invitation_id,bot_id,destination,kind,generation,"
                        "private_generation,state,requested_by) VALUES "
                        "(:id,:tech,:invite,9000001,'PRIVATE_ACCOUNT',"
                        "'APPROVED',0,0,'QUEUED',:tech)"
                    ),
                    {"id": calendar, "tech": tech, "invite": assignment},
                )
            else:
                expected = "PRIVATE_TELEGRAM" if upgraded else "PRIVATE_ACCOUNT"
                assert (
                    await db.scalar(
                        text("SELECT purpose FROM telegram_invitations WHERE id=:id"),
                        {"id": assignment},
                    )
                    == expected
                )
                assert (
                    await db.scalar(
                        text("SELECT destination FROM telegram_outbox WHERE id=:id"),
                        {"id": calendar},
                    )
                    == expected
                )
                if upgraded:
                    assert (
                        await db.scalar(
                            text("SELECT automatic FROM telegram_invitations WHERE id=:id"),
                            {"id": assignment},
                        )
                        is False
                    )
                    assert (
                        await db.scalar(
                            text(
                                "SELECT column_default FROM information_schema.columns "
                                "WHERE table_name='telegram_invitations' "
                                "AND column_name='automatic'"
                            )
                        )
                        == "true"
                    )
    finally:
        await engine.dispose()


alembic("downgrade", "base")
alembic("upgrade", "d6c2f8a14001")
asyncio.run(fixture())
asyncio.run(stage1_record(seed=True))
asyncio.run(completion_fixture(seed=True))
alembic("upgrade", "head")
asyncio.run(fixture(check=True))
asyncio.run(stage1_record())
asyncio.run(completion_fixture())
alembic("downgrade", "d6c2f8a14001")
asyncio.run(completion_fixture(upgraded=False))
alembic("upgrade", "head")
asyncio.run(completion_fixture())
alembic("check")
alembic("heads")
print("Populated reconciliation upgrade preserves pending review credentials and queued delivery.")


async def stage2_fixture(check=False):
    engine = create_async_engine(url, hide_parameters=True)
    try:
        async with engine.begin() as db:
            if not check:
                await db.execute(
                    text(
                        "INSERT INTO calendar_connections "
                        "(id,account_key,account_label,status,granted_scopes) "
                        "VALUES (:id,'migration-account','Migration account','DISCONNECTED','[]')"
                    ),
                    {"id": tech},
                )
                await db.execute(
                    text(
                        "UPDATE calendars SET source='GOOGLE',provider_connection_id=:connection, "
                        "provider_calendar_id='migration-google',excluded_at=now(), "
                        "availability='UNAVAILABLE' WHERE id=:id"
                    ),
                    {"connection": tech, "id": calendar},
                )
            row = (
                await db.execute(
                    text(
                        "SELECT c.source,c.provider_calendar_id,"
                        "c.excluded_at IS NOT NULL,a.calendar_id "
                        "FROM calendars c JOIN calendar_assignments a ON a.calendar_id=c.id "
                        "WHERE c.id=:id"
                    ),
                    {"id": calendar},
                )
            ).one()
            assert row == ("GOOGLE", "migration-google", True, calendar)
            constraints = set(
                (
                    await db.scalars(
                        text(
                            "SELECT conname FROM pg_constraint WHERE conrelid='calendars'::regclass"
                        )
                    )
                ).all()
            )
            assert {
                "ck_calendars_provider_identity",
                "ck_calendars_availability",
                "uq_calendar_provider_identity",
            } <= constraints
    finally:
        await engine.dispose()


asyncio.run(stage2_fixture())
# The additive audit revision supports rollback with provider data intact.
alembic("downgrade", "0a542f68aa75")
asyncio.run(stage2_fixture(check=True))
alembic("upgrade", "head")
asyncio.run(stage2_fixture(check=True))
refused = subprocess.run(
    [sys.executable, "-m", "alembic", "downgrade", "e7b310920001"],
    cwd=root / "apps/api",
    env=env,
    capture_output=True,
    text=True,
)
assert refused.returncode != 0 and "Stage 2 provider data exists" in refused.stderr
asyncio.run(stage2_fixture(check=True))
alembic("check")
print(
    "Stage 2 populated catalog/history preserved; destructive downgrade refused; checks verified."
)


# Stage 3 rollback must burn pending event upgrades; ordinary attempts remain intact.
manager_id, session_id = uuid.uuid4(), uuid.uuid4()
upgrade_id, ordinary_id = uuid.uuid4(), uuid.uuid4()


async def stage3_attempts(check=False):
    engine = create_async_engine(url, hide_parameters=True)
    try:
        async with engine.begin() as db:
            if not check:
                await db.execute(
                    text(
                        "INSERT INTO managers (id,username,password_hash) "
                        "VALUES (:id,'migration-events','not-a-login-hash')"
                    ),
                    {"id": manager_id},
                )
                await db.execute(
                    text(
                        "INSERT INTO manager_sessions (id,manager_id,token_hash,expires_at) "
                        "VALUES (:id,:manager,:hash,now()+interval '1 hour')"
                    ),
                    {"id": session_id, "manager": manager_id, "hash": uuid.uuid4().hex * 2},
                )
                for identifier, upgrade in [(upgrade_id, True), (ordinary_id, False)]:
                    await db.execute(
                        text(
                            "INSERT INTO google_oauth_attempts "
                            "(id,state_hash,manager_id,session_id,encrypted_verifier,expires_at,"
                            "mode,request_event_access) "
                            "VALUES (:id,:hash,:manager,:session,'v1:inert-migration-fixture',"
                            "now()+interval '10 minutes','RECONNECT',:upgrade)"
                        ),
                        {
                            "id": identifier,
                            "hash": uuid.uuid4().hex * 2,
                            "manager": manager_id,
                            "session": session_id,
                            "upgrade": upgrade,
                        },
                    )
            else:
                rows = (
                    await db.execute(
                        text(
                            "SELECT id,consumed_at IS NOT NULL,encrypted_verifier "
                            "FROM google_oauth_attempts WHERE id IN (:upgrade,:ordinary)"
                        ),
                        {"upgrade": upgrade_id, "ordinary": ordinary_id},
                    )
                ).all()
                found = {row[0]: row[1:] for row in rows}
                assert found[upgrade_id] == (True, None)
                assert found[ordinary_id] == (False, "v1:inert-migration-fixture")
    finally:
        await engine.dispose()


asyncio.run(stage3_attempts())
alembic("downgrade", "b2917d804e12")
asyncio.run(stage3_attempts(check=True))
alembic("upgrade", "head")
asyncio.run(stage3_attempts(check=True))
alembic("check")
print("Stage 3 upgrade-attempt downgrade burns verifier; re-upgrade and drift passed.")


# Stage 4 adds only durable delivery tables; populated Stage 3 data survives rollback.
async def stage4_counts(setting=False):
    engine = create_async_engine(url, hide_parameters=True)
    try:
        async with engine.begin() as db:
            if setting:
                await db.execute(
                    text("INSERT INTO schedule_delivery_settings (technician_id) VALUES (:id)"),
                    {"id": tech},
                )
                assert (
                    await db.scalar(
                        text(
                            "SELECT enabled FROM schedule_delivery_settings WHERE technician_id=:id"
                        ),
                        {"id": tech},
                    )
                    is False
                )
            return tuple(
                [
                    await db.scalar(text(f"SELECT count(*) FROM {table}"))
                    for table in (
                        "technicians",
                        "calendars",
                        "calendar_assignments",
                        "calendar_connections",
                        "google_oauth_attempts",
                    )
                ]
            )
    finally:
        await engine.dispose()


stage3_counts = asyncio.run(stage4_counts(setting=True))
alembic("downgrade", "c3e410a20917")
assert asyncio.run(stage4_counts()) == stage3_counts
alembic("upgrade", "head")
assert asyncio.run(stage4_counts()) == stage3_counts
alembic("check")

configuration = Config(str(root / "apps/api/alembic.ini"))
configuration.set_main_option("script_location", str(root / "apps/api/migrations"))
assert ScriptDirectory.from_config(configuration).get_heads() == ["fba609190001"]
print(
    "Stage 4 populated Stage 3 preservation, default OFF, rollback/re-upgrade, "
    "one head and zero drift passed."
)


# A populated original Stage 4 database upgrades without altering legacy content.
alembic("downgrade", "d4e509170001")
legacy_dispatch = uuid.uuid4()


async def legacy_history(action):
    engine = create_async_engine(url, hide_parameters=True)
    try:
        async with engine.begin() as db:
            if action == "insert":
                await db.execute(
                    text("""
                    INSERT INTO schedule_dispatches
                    (id,technician_id,target_date,trigger,destination,status,source_version,
                     fingerprint,job_count,encrypted_payload,payload_expires_at,attempt_count,
                     available_at,delivery_deadline,finished_at,ack_status,bot_id,
                     telegram_user_id,chat_id,private_generation,group_generation)
                    VALUES (:id,:tech,'2026-09-18','MANUAL','PRIVATE','FAILED',:hash,:hash,
                            0,'v1:inert-audit-migration',now()+interval '7 days',1,
                            now(),now()+interval '1 hour',now(),'NOT_SENT',9000001,
                            771001,771001,1,1)
                """),
                    {"id": legacy_dispatch, "tech": tech, "hash": "a" * 64},
                )
            elif action == "check":
                row = (
                    await db.execute(
                        text("""
                    SELECT status,encrypted_payload,requested_destination,fallback_reason
                    FROM schedule_dispatches WHERE id=:id
                """),
                        {"id": legacy_dispatch},
                    )
                ).one()
                assert row == ("FAILED", "v1:inert-audit-migration", None, None)
                assert (
                    await db.scalar(text("SELECT version_num FROM alembic_version"))
                    == "fba609190001"
                )
            else:
                await db.execute(
                    text("DELETE FROM schedule_dispatches WHERE id=:id"), {"id": legacy_dispatch}
                )
    finally:
        await engine.dispose()


asyncio.run(legacy_history("insert"))
alembic("upgrade", "head")
asyncio.run(legacy_history("check"))
refused = subprocess.run(
    [sys.executable, "-m", "alembic", "downgrade", "c3e410a20917"],
    cwd=root / "apps/api",
    env=env,
    capture_output=True,
    text=True,
)
assert refused.returncode != 0 and "SCHEDULE_HISTORY_ROLLBACK_REFUSED" in refused.stderr
asyncio.run(legacy_history("check"))
asyncio.run(legacy_history("remove"))
alembic("check")
print("Audit migration preserves populated Stage 4; populated rollback refuses atomically.")


async def stage5_history(action):
    from datetime import date
    from decimal import Decimal

    from hub.work_reports.models import WorkReport, WorkReportRevision
    from sqlalchemy import insert

    engine = create_async_engine(url, hide_parameters=True)
    try:
        async with engine.begin() as db:
            if action == "insert":
                await db.execute(
                    insert(WorkReport).values(
                        id=stage5_report,
                        technician_id=tech,
                        calendar_id=calendar,
                        occurrence_key="b" * 64,
                    )
                )
                await db.execute(
                    insert(WorkReportRevision).values(
                        report_id=stage5_report,
                        revision_number=1,
                        technician_name="Migration fictional technician",
                        operational_date=date(2026, 9, 18),
                        start_time="08:00",
                        end_time="09:00",
                        sequence=1,
                        title="Migration fictional job",
                        location="Test address",
                        provider_event_id="test-occurrence",
                        amount_closed=Decimal("123.45"),
                        payment_method="CASH",
                        closed_by="MYSELF",
                        comments="Migration sentinel",
                        yearly_maintenance_plan_provided=False,
                        google_reviews=1,
                        groupon_reviews=0,
                        facebook_reviews=2,
                    )
                )
            elif action == "check":
                assert await db.scalar(
                    text("SELECT amount_closed FROM work_report_revisions WHERE report_id=:id"),
                    {"id": stage5_report},
                ) == Decimal("123.45")
                assert (
                    await db.scalar(text("SELECT version_num FROM alembic_version"))
                    == "fba609190001"
                )
            else:
                await db.execute(
                    text("TRUNCATE technician_form_sessions, work_report_revisions, work_reports")
                )
    finally:
        await engine.dispose()


stage5_report = uuid.uuid4()
asyncio.run(stage5_history("insert"))
refused = subprocess.run(
    [sys.executable, "-m", "alembic", "downgrade", "d4e509170002"],
    cwd=root / "apps/api",
    env=env,
    capture_output=True,
    text=True,
)
assert refused.returncode != 0 and "WORK_REPORT_HISTORY_ROLLBACK_REFUSED" in refused.stderr
asyncio.run(stage5_history("check"))
asyncio.run(stage5_history("remove"))
alembic("downgrade", "d4e509170002")
alembic("upgrade", "head")
asyncio.run(fixture(check=True))
alembic("check")
print("Stage 5 populated report rollback refused; empty round-trip preserves Stage 4 data.")


# Stage 6 forward migration retains a populated audited Stage 5 report.
alembic("downgrade", "e5f509180003")
asyncio.run(stage5_history("insert"))
alembic("upgrade", "head")
asyncio.run(stage5_history("check"))


async def stage6_history(action):
    from datetime import UTC, datetime
    from decimal import Decimal

    from hub.expenses.models import ExpenseRevision, TechnicianExpense
    from sqlalchemy import insert

    engine = create_async_engine(url, hide_parameters=True)
    try:
        async with engine.begin() as db:
            if action == "insert":
                await db.execute(
                    insert(TechnicianExpense).values(id=expense_id, technician_id=tech)
                )
                instant = datetime(2026, 9, 18, 12, tzinfo=UTC)
                await db.execute(
                    insert(ExpenseRevision).values(
                        expense_id=expense_id,
                        revision_number=1,
                        technician_name="Migration fictional",
                        expense_date=instant.date(),
                        accounting_timezone="UTC",
                        expense_type="Parking",
                        amount=Decimal("20.01"),
                        note="Synthetic migration sentinel",
                        submitted_at=instant,
                    )
                )
            elif action == "check":
                assert await db.scalar(
                    text("SELECT amount FROM expense_revisions WHERE expense_id=:id"),
                    {"id": expense_id},
                ) == Decimal("20.01")
                assert (
                    await db.scalar(text("SELECT version_num FROM alembic_version"))
                    == "fba609190001"
                )
            else:
                await db.execute(
                    text(
                        "TRUNCATE technician_form_sessions, expense_revisions, technician_expenses"
                    )
                )
    finally:
        await engine.dispose()


expense_id = uuid.uuid4()
asyncio.run(stage6_history("insert"))
# Audit successor has a lossless populated round-trip to the Stage 6 schema.
alembic("downgrade", "f6e609180001")
alembic("upgrade", "head")
asyncio.run(stage6_history("check"))
refused = subprocess.run(
    [sys.executable, "-m", "alembic", "downgrade", "e5f509180003"],
    cwd=root / "apps/api",
    env=env,
    capture_output=True,
    text=True,
)
assert refused.returncode != 0 and "EXPENSE_HISTORY_ROLLBACK_REFUSED" in refused.stderr
asyncio.run(stage6_history("check"))
asyncio.run(stage5_history("check"))
asyncio.run(stage6_history("remove"))
alembic("downgrade", "e5f509180003")
alembic("upgrade", "head")
asyncio.run(stage5_history("check"))
asyncio.run(fixture(check=True))
alembic("check")
print(
    "Stage 6 populated Stage 5 preserved; expense rollback refused; empty expense "
    "roundtrip and zero drift passed."
)


async def stage9_mirror_fixture(action):
    engine = create_async_engine(url, hide_parameters=True)
    try:
        async with engine.begin() as db:
            if action == "insert":
                await db.execute(
                    text(
                        "INSERT INTO accounting_mirror_targets "
                        "(id,kind,technician_id,google_connection_id,spreadsheet_id) "
                        "VALUES (:id,'INDIVIDUAL',:tech,:connection,'migrationSheet_12345')"
                    ),
                    {"id": assignment, "tech": tech, "connection": tech},
                )
            elif action == "check":
                row = (
                    await db.execute(
                        text(
                            "SELECT kind,technician_id,spreadsheet_id "
                            "FROM accounting_mirror_targets WHERE id=:id"
                        ),
                        {"id": assignment},
                    )
                ).one()
                assert row == ("INDIVIDUAL", tech, "migrationSheet_12345")
                assert (
                    await db.scalar(text("SELECT version_num FROM alembic_version"))
                    == "fba609190001"
                )
            else:
                await db.execute(
                    text("DELETE FROM accounting_mirror_targets WHERE id=:id"),
                    {"id": assignment},
                )
    finally:
        await engine.dispose()


# Stage 8 data upgrades additively. Populated mirror configuration blocks destructive rollback,
# while an empty Stage 9 schema supports the project's reviewable downgrade/re-upgrade policy.
alembic("downgrade", "f6e609180002")
alembic("upgrade", "head")
asyncio.run(fixture(check=True))
asyncio.run(stage5_history("check"))
asyncio.run(stage9_mirror_fixture("insert"))
asyncio.run(stage9_mirror_fixture("check"))
refused = subprocess.run(
    [sys.executable, "-m", "alembic", "downgrade", "f6e609180002"],
    cwd=root / "apps/api",
    env=env,
    capture_output=True,
    text=True,
)
assert refused.returncode != 0 and "ACCOUNTING_MIRROR_DATA_REVIEW_REQUIRED" in refused.stderr
asyncio.run(stage9_mirror_fixture("check"))
asyncio.run(stage9_mirror_fixture("remove"))
alembic("downgrade", "f6e609180002")
asyncio.run(fixture(check=True))
alembic("upgrade", "head")
asyncio.run(fixture(check=True))
asyncio.run(stage5_history("check"))
alembic("check")
alembic("heads")
print(
    "Stage 9 populated Stage 8 preservation, destructive-data rollback refusal, "
    "empty round-trip, one head, and zero drift passed."
)


async def stage10_provider_invariants(check=False):
    engine = create_async_engine(url, hide_parameters=True)
    try:
        async with engine.begin() as db:
            if not check:
                await db.execute(
                    text(
                        "UPDATE telegram_bindings SET private_status='CONNECTED', "
                        "telegram_user_id=1234567890, bot_id=9000001, private_generation=1, "
                        "private_availability='AVAILABLE' WHERE technician_id=:id"
                    ),
                    {"id": tech},
                )
            row = (
                await db.execute(
                    text(
                        "SELECT private_status,telegram_user_id,private_generation,"
                        "private_availability FROM telegram_bindings WHERE technician_id=:id"
                    ),
                    {"id": tech},
                )
            ).one()
            assert row == ("CONNECTED", 1234567890, 1, "AVAILABLE")
            if check:
                constraints = set(
                    (
                        await db.scalars(
                            text(
                                "SELECT conname FROM pg_constraint "
                                "WHERE conrelid='telegram_bindings'::regclass"
                            )
                        )
                    ).all()
                )
                assert {
                    "ck_telegram_bindings_private_connected_identity",
                    "ck_telegram_bindings_group_connected_identity",
                    "ck_telegram_bindings_group_available_current_private",
                } <= constraints
    finally:
        await engine.dispose()


asyncio.run(stage10_provider_invariants())
alembic("downgrade", "faa609190001")
asyncio.run(stage10_provider_invariants())
alembic("upgrade", "head")
asyncio.run(stage10_provider_invariants(check=True))
alembic("check")
alembic("heads")
print(
    "Stage 10 populated provider state survives constraint rollback/re-upgrade; "
    "one head and zero drift passed."
)
