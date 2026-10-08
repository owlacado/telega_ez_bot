"""Isolated operator tests: synthetic DB results and no migration/provider execution."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from hub import render_operator as operator
from hub import render_runtime as runtime
from hub.core.config import Settings
from hub.core.migrations import ReleaseMigrationError, release_migration_head
from hub.ops.schemas import ComponentHealth, OperationsHealth, QueueCounts


@pytest.fixture(scope="session", autouse=True)
def migrate_database():
    pass


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(operator, "engine_for", MagicMock(side_effect=AssertionError("No real DB")))
    monkeypatch.setattr(
        operator.subprocess, "run", MagicMock(side_effect=AssertionError("No Alembic"))
    )


@pytest.fixture
def settings():
    return Settings(app_env="test", release_commit="a" * 40)


def summary():
    disabled = ComponentHealth(state="DISABLED", message="disabled")
    return OperationsHealth(
        status="PASS",
        app_version="0.3.0",
        release_commit="a" * 40,
        database=ComponentHealth(state="PASS", message="reachable"),
        migration=ComponentHealth(state="PASS", message="current"),
        telegram_worker=disabled,
        schedule_worker=disabled,
        mirror_worker=disabled,
        google_configuration=disabled,
        queues={
            name: QueueCounts() for name in ("telegram", "schedule", "mirror", "report_calendar")
        },
    )


def status_db(monkeypatch, heads, health=None):
    db = AsyncMock()
    db.scalar.return_value = "alembic_version"
    db.scalars.return_value = SimpleNamespace(all=lambda: heads)
    context = AsyncMock()
    context.__aenter__.return_value = db
    engine = SimpleNamespace(dispose=AsyncMock())
    monkeypatch.setattr(operator, "engine_for", lambda settings: engine)
    monkeypatch.setattr(operator, "async_sessionmaker", lambda engine: lambda: context)
    monkeypatch.setattr(operator, "operations_health", AsyncMock(return_value=health or summary()))
    return db, engine


async def test_status_pass(monkeypatch, settings, capsys):
    head = release_migration_head()
    db, engine = status_db(monkeypatch, [head])
    assert await operator.status(settings) == 0
    output = capsys.readouterr().out
    for expected in (
        "App version: 0.3.0",
        "Release commit: " + "a" * 40,
        "Database connectivity: PASS",
        "Actual Alembic head: " + head,
        "Expected release head: " + head,
        "Telegram configuration: DISABLED",
        "Mirror worker: DISABLED",
        "Schedule worker: DISABLED",
        "Queue telegram: pending=0 processing=0 failed=0 ambiguous=0",
        "Queue report_calendar: pending=0 processing=0 failed=0 ambiguous=0",
        "Overall: PASS",
    ):
        assert expected in output
    engine.dispose.assert_awaited_once()


@pytest.mark.parametrize("heads", [["old"], ["unknown"], [], ["one", "two"]])
async def test_status_stale_or_invalid_head_blocks(monkeypatch, settings, capsys, heads):
    status_db(monkeypatch, heads)
    assert await operator.status(settings) == 2
    assert "Overall: BLOCK" in capsys.readouterr().out


async def test_status_unhealthy_worker_or_queue_blocks(monkeypatch, settings, capsys):
    health = summary()
    health.status = "WARN"
    health.queues["telegram"].ambiguous = 1
    status_db(monkeypatch, [release_migration_head()], health)
    assert await operator.status(settings) == 2
    assert "ambiguous=1" in capsys.readouterr().out


async def test_status_db_failure_is_safe(monkeypatch, settings, capsys):
    secret = "postgresql://operator:private-password@secret.example/db"
    db, engine = status_db(monkeypatch, [])
    db.execute.side_effect = RuntimeError(secret)
    assert await operator.status(settings) == 2
    output = capsys.readouterr().out
    assert secret not in output and "private-password" not in output
    assert "Database connectivity: UNAVAILABLE" in output
    assert "Overall: BLOCK" in output
    engine.dispose.assert_awaited_once()


async def test_status_no_secret_or_payload_output(monkeypatch, settings, capsys):
    secret = "synthetictokenvalue"
    settings.app_version = secret
    settings.release_commit = secret
    settings.telegram_bot_token = secret
    health = summary()
    health.telegram_worker.message = secret
    status_db(monkeypatch, [secret], health)
    assert await operator.status(settings) == 2
    output = capsys.readouterr().out
    assert secret not in output
    assert "Actual Alembic head: UNKNOWN" in output


def migration_reads(monkeypatch, values):
    read = AsyncMock(side_effect=values)
    run = MagicMock(return_value=SimpleNamespace(returncode=0))
    monkeypatch.setattr(operator, "read_heads", read)
    monkeypatch.setattr(operator.subprocess, "run", run)
    return read, run


def test_migrate_noop(monkeypatch, settings, capsys):
    head = release_migration_head()
    read, run = migration_reads(monkeypatch, [[head]])
    assert operator.migrate(settings) == 0
    assert "No migration required. PASS" in capsys.readouterr().out
    run.assert_not_called()
    read.assert_awaited_once()


def test_migrate_success(monkeypatch, settings, capsys):
    head = release_migration_head()
    read, run = migration_reads(monkeypatch, [[], [head]])
    assert operator.migrate(settings) == 0
    output = capsys.readouterr().out
    assert "Current DB head: NONE" in output
    assert "Target release head: " + head in output
    assert "Migrated NONE -> " + head + ". PASS" in output
    assert run.call_args.args[0][-2:] == ("upgrade", head)
    assert read.await_count == 2
    assert run.call_args.kwargs["stdout"] == operator.subprocess.DEVNULL
    assert run.call_args.kwargs["stderr"] == operator.subprocess.DEVNULL


@pytest.mark.parametrize("failure", ["exit", "exception", "stale", "unreachable"])
def test_migrate_failure_nonzero_and_no_leak(monkeypatch, settings, capsys, failure):
    read, run = migration_reads(monkeypatch, [[], ["stale"]])
    if failure == "exit":
        run.return_value = SimpleNamespace(returncode=1)
    elif failure == "exception":
        run.side_effect = RuntimeError("private-password")
    elif failure == "unreachable":
        read.side_effect = RuntimeError("private-password")
    assert operator.migrate(settings) == 2
    output = capsys.readouterr().out
    assert "BLOCK" in output and "PASS" not in output
    assert "private-password" not in output


def test_divergent_release_fails_before_migration(monkeypatch, settings, capsys):
    monkeypatch.setattr(
        operator, "release_migration_head", MagicMock(side_effect=ReleaseMigrationError())
    )
    read, run = migration_reads(monkeypatch, [[]])
    assert operator.migrate(settings) == 2
    run.assert_not_called()
    read.assert_not_awaited()
    assert "BLOCK" in capsys.readouterr().out


async def test_empty_database_heads(monkeypatch):
    db = AsyncMock()
    db.scalar.return_value = None
    assert await operator.database_heads(db) == []
    db.scalars.assert_not_awaited()


@pytest.mark.parametrize(
    "command,code", [("status", 0), ("status", 2), ("migrate", 0), ("migrate", 2)]
)
def test_runtime_exit_contract(monkeypatch, settings, command, code):
    monkeypatch.setattr(runtime.sys, "argv", ["hub.render_runtime", command])
    monkeypatch.setattr(runtime, "prepare_environment", lambda: settings)
    monkeypatch.setattr(operator, "status", AsyncMock(return_value=code))
    monkeypatch.setattr(operator, "migrate", MagicMock(return_value=code))
    with pytest.raises(SystemExit) as error:
        runtime.main()
    assert error.value.code == code


@pytest.mark.parametrize(
    "command,tail",
    [
        ("preflight", ("preflight",)),
        ("queues", ("queues", "--require-pass")),
    ],
)
def test_existing_operator_commands_unchanged(monkeypatch, settings, command, tail):
    monkeypatch.setattr(runtime.sys, "argv", ["hub.render_runtime", command])
    monkeypatch.setattr(runtime, "prepare_environment", lambda: settings)
    call = MagicMock(return_value=2)
    monkeypatch.setattr(runtime.subprocess, "call", call)
    with pytest.raises(SystemExit) as error:
        runtime.main()
    assert error.value.code == 2
    assert call.call_args.args[0] == (runtime.sys.executable, "-m", "hub.ops.cli", *tail)


async def test_status_divergent_release_blocks(monkeypatch, settings, capsys):
    status_db(monkeypatch, [release_migration_head()])
    monkeypatch.setattr(
        operator, "release_migration_head", MagicMock(side_effect=ReleaseMigrationError())
    )
    assert await operator.status(settings) == 2
    assert "Expected release head: UNAVAILABLE" in capsys.readouterr().out


async def test_read_heads_disposes_readonly_connection(monkeypatch, settings):
    head = release_migration_head()
    db, engine = status_db(monkeypatch, [head])
    assert await operator.read_heads(settings) == [head]
    engine.dispose.assert_awaited_once()
    db.commit.assert_not_awaited()


async def test_enabled_telegram_without_token_blocks(monkeypatch, settings, capsys):
    status_db(monkeypatch, [release_migration_head()])
    settings.telegram_mode = "real"
    settings.telegram_bot_token = None
    settings.telegram_token_file = None
    assert await operator.status(settings) == 2
    assert "Telegram configuration: BLOCK" in capsys.readouterr().out
