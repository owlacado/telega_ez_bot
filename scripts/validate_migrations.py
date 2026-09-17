"""Destructive schema checks run ONLY on the local disposable test database."""

import asyncio
import os
import subprocess
import sys
import uuid
from pathlib import Path

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
