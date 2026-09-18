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
                        "(:id,:tech,:invite,9000001,'PRIVATE_ACCOUNT','APPROVED',0,0,'QUEUED',:tech)"
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
assert ScriptDirectory.from_config(configuration).get_heads() == ["d4e509170001"]
print(
    "Stage 4 populated Stage 3 preservation, default OFF, rollback/re-upgrade, "
    "one head and zero drift passed."
)
