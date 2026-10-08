"""Provider-silent Render summaries and verified migration execution."""

import asyncio
import re
import subprocess
import sys
from pathlib import Path

from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from hub.core import migrations
from hub.core.migrations import release_migration_head
from hub.ops.service import operations_health

API_DIRECTORY = Path(__file__).resolve().parents[1]


def identifier(value, pattern):
    return value if isinstance(value, str) and re.fullmatch(pattern, value) else "UNAVAILABLE"


def head_label(heads):
    if not heads:
        return "NONE"
    try:
        known = {
            revision.revision
            for revision in ScriptDirectory(str(migrations.MIGRATIONS_DIRECTORY)).walk_revisions()
        }
    except Exception:
        return "UNAVAILABLE"
    return ", ".join(head if head in known else "UNKNOWN" for head in heads)


def engine_for(settings):
    return create_async_engine(
        settings.database_url, hide_parameters=True, connect_args={"timeout": 5}
    )


async def database_heads(db):
    # An empty database is a supported first-deployment migration starting point.
    if await db.scalar(text("SELECT to_regclass('alembic_version')")) is None:
        return []
    return list((await db.scalars(text("SELECT version_num FROM alembic_version"))).all())


async def read_heads(settings):
    engine = engine_for(settings)
    try:
        async with async_sessionmaker(engine)() as db:
            return await database_heads(db)
    finally:
        await engine.dispose()


def telegram_configuration(settings):
    if settings.telegram_mode == "disabled":
        return "DISABLED"
    token = settings.telegram_token_file
    available = bool(settings.telegram_bot_token) or bool(token and Path(token).is_file())
    return "CONFIGURED" if available else "BLOCK"


async def status(settings):
    print("Technician Hub status (providers are not contacted)")
    print("App version: " + identifier(settings.app_version, r"[0-9]+\.[0-9]+\.[0-9]+"))
    print("Release commit: " + identifier(settings.release_commit, r"[0-9a-f]{40}|development"))
    expected, actual, database, health = None, None, "UNAVAILABLE", None
    try:
        expected = release_migration_head()
    except Exception:
        pass
    try:
        engine = engine_for(settings)
        try:
            async with async_sessionmaker(engine)() as db:
                await db.execute(text("SELECT 1"))
                database = "PASS"
                actual = await database_heads(db)
                health = await operations_health(db, settings)
        finally:
            await engine.dispose()
    except Exception:
        # Driver errors and arbitrary stored values must never reach operator output.
        pass
    try:
        telegram = telegram_configuration(settings)
    except Exception:
        telegram = "BLOCK"
    print("Database connectivity: " + database)
    print("Actual Alembic head: " + (head_label(actual) if actual is not None else "UNAVAILABLE"))
    print("Expected release head: " + (head_label([expected]) if expected else "UNAVAILABLE"))
    print("Telegram configuration: " + telegram)
    print("Telegram worker: " + (health.telegram_worker.state if health else "UNAVAILABLE"))
    print(
        "Google configuration: " + ("CONFIGURED" if settings.google_mode == "real" else "DISABLED")
    )
    print("Mirror worker: " + (health.mirror_worker.state if health else "UNAVAILABLE"))
    print("Schedule worker: " + (health.schedule_worker.state if health else "UNAVAILABLE"))
    for name in ("telegram", "schedule", "mirror", "report_calendar"):
        queue = health.queues.get(name) if health else None
        counts = (
            " ".join(
                f"{field}={getattr(queue, field)}"
                for field in ("pending", "processing", "failed", "ambiguous")
            )
            if queue
            else "UNAVAILABLE"
        )
        print(f"Queue {name}: {counts}")
    passed = bool(
        expected
        and actual == [expected]
        and health
        and health.status == "PASS"
        and telegram != "BLOCK"
    )
    print("Overall: " + ("PASS" if passed else "BLOCK"))
    return 0 if passed else 2


def migrate(settings):
    try:
        target = release_migration_head()
        before = asyncio.run(read_heads(settings))
        print("Current DB head: " + head_label(before), flush=True)
        print("Target release head: " + head_label([target]), flush=True)
        if before == [target]:
            print("No migration required. PASS")
            return 0
        result = subprocess.run(
            (sys.executable, "-m", "alembic", "upgrade", target),
            cwd=API_DIRECTORY,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode != 0:
            print("Migration failed. BLOCK (database head verification required)")
            return 2
        after = asyncio.run(read_heads(settings))
        if after != [target]:
            print("Migration verification failed: database head does not match release. BLOCK")
            return 2
        print(f"Migrated {head_label(before)} -> {head_label(after)}. PASS")
        return 0
    except Exception:
        print("Migration unavailable: check configuration, database and release graph. BLOCK")
        return 2
