"""Source-graph and ops regressions: no database connection or migration execution."""

import shutil
import socket
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from alembic.script import ScriptDirectory
from cryptography.fernet import Fernet

from hub.core import migrations
from hub.core.config import Settings
from hub.ops import cli, router, service
from hub.telegram.adapter import TelegramBotAdapter


@pytest.fixture(scope="session", autouse=True)
def migrate_database():
    # Override the integration conftest: this module must never run Alembic upgrade.
    pass


@pytest.fixture(autouse=True)
async def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Readiness must not open network connections in these tests")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(TelegramBotAdapter, "initialize", AsyncMock(side_effect=blocked))
    try:
        yield
    finally:
        monkeypatch.undo()


def revision(directory, name, parent=None):
    (directory / "versions").mkdir(parents=True, exist_ok=True)
    (directory / "versions" / f"{name}.py").write_text(
        f"revision = {name!r}\ndown_revision = {parent!r}\n"
        "branch_labels = None\ndepends_on = None\n",
        encoding="utf-8",
    )


class ReadOnlyDatabase:
    def __init__(self, heads):
        self.heads, self.statements = heads, []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    def record(self, statement):
        sql = str(statement)
        assert sql.lstrip().upper().startswith("SELECT ")
        self.statements.append(sql)
        return sql

    async def execute(self, statement):
        self.record(statement)

    async def scalars(self, statement):
        sql = self.record(statement)
        assert "alembic_version" in sql and "LIMIT" not in sql.upper()
        return SimpleNamespace(all=lambda: self.heads)

    async def scalar(self, statement):
        sql = self.record(statement)
        if "count(" in sql.lower():
            return 1 if "managers" in sql else 0
        return None  # No worker rows; disabled providers need none.


def configure_cli(monkeypatch, heads):
    db = ReadOnlyDatabase(heads)
    engine = SimpleNamespace(dispose=AsyncMock())
    monkeypatch.setattr(cli, "create_async_engine", lambda *a, **k: engine)
    monkeypatch.setattr(cli, "async_sessionmaker", lambda *a, **k: lambda: db)
    return db


def settings(**kwargs):
    return Settings(_env_file=None, app_env="test", **kwargs)


async def assert_consumers(monkeypatch, capsys, heads, expected):
    db = configure_cli(monkeypatch, heads)
    config = settings()
    health = await service.operations_health(db, config)
    assert health.migration.state == expected
    assert health.status == expected
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(settings=config)))
    assert (await router.health(request, db)).migration == health.migration
    code = 0 if expected == "PASS" else 2
    assert await cli.preflight(config) == code
    assert f"{expected} migration:" in capsys.readouterr().out
    assert await cli.queues(config, require_pass=True) == code
    assert f'"status":"{expected}"' in capsys.readouterr().out
    return db


@pytest.mark.parametrize("case", ["current", "stale", "unknown", "empty", "multiple", "duplicate"])
async def test_release_and_database_heads_for_every_consumer(monkeypatch, capsys, case):
    current = migrations.release_migration_head()
    previous = (
        ScriptDirectory(str(migrations.MIGRATIONS_DIRECTORY)).get_revision(current).down_revision
    )
    heads = {
        "current": [current],
        "stale": [previous],
        "unknown": ["unknown-revision"],
        "empty": [],
        "multiple": [current, "unknown-revision"],
        "duplicate": [current, current],
    }[case]
    await assert_consumers(monkeypatch, capsys, heads, "PASS" if case == "current" else "BLOCK")


@pytest.mark.parametrize("problem", ["multiple", "empty", "missing", "broken"])
async def test_invalid_release_graph_fails_closed_for_every_consumer(
    tmp_path, monkeypatch, capsys, problem
):
    graph = tmp_path / "release-migrations"
    if problem != "missing":
        (graph / "versions").mkdir(parents=True)
    if problem == "multiple":
        revision(graph, "one")
        revision(graph, "two")
    elif problem == "broken":
        (graph / "versions" / "bad.py").write_text("not valid python!", encoding="utf-8")
    monkeypatch.setattr(migrations, "MIGRATIONS_DIRECTORY", graph)
    with pytest.raises(migrations.ReleaseMigrationError):
        migrations.release_migration_head()
    db = await assert_consumers(monkeypatch, capsys, ["one"], "BLOCK")
    assert not any("alembic_version" in sql for sql in db.statements)


async def test_new_migration_changes_all_consumers_without_updating_a_constant(
    tmp_path, monkeypatch, capsys
):
    graph = tmp_path / "migrations"
    shutil.copytree(
        migrations.MIGRATIONS_DIRECTORY, graph, ignore=shutil.ignore_patterns("__pycache__")
    )
    monkeypatch.setattr(migrations, "MIGRATIONS_DIRECTORY", graph)
    old_head = migrations.release_migration_head()
    await assert_consumers(monkeypatch, capsys, [old_head], "PASS")
    revision(graph, "future_synthetic_head", old_head)
    assert migrations.release_migration_head() == "future_synthetic_head"
    await assert_consumers(monkeypatch, capsys, [old_head], "BLOCK")
    await assert_consumers(monkeypatch, capsys, ["future_synthetic_head"], "PASS")


def test_head_resolution_ignores_cwd_and_does_not_execute_env(tmp_path, monkeypatch):
    graph = tmp_path / "release"
    revision(graph, "isolated_head")
    (graph / "env.py").write_text("raise AssertionError('env.py must not run')", encoding="utf-8")
    monkeypatch.setattr(migrations, "MIGRATIONS_DIRECTORY", graph)
    monkeypatch.chdir(tmp_path)
    assert migrations.release_migration_head() == "isolated_head"


async def test_preflight_real_provider_configuration_remains_provider_silent(monkeypatch, capsys):
    configure_cli(monkeypatch, [migrations.release_migration_head()])
    config = settings(
        telegram_mode="real",
        telegram_expected_bot_id=9000001,
        telegram_expected_bot_username="hub_dedicated_test_bot",
        telegram_bot_token="synthetic-token",
        google_mode="real",
        google_client_id="synthetic-client",
        google_client_secret="synthetic-secret",
        google_oauth_redirect_uri="http://127.0.0.1:3000/api/calendar-connections/google/callback",
        google_calendar_credential_encryption_key=Fernet.generate_key().decode(),
    )
    assert await cli.preflight(config) == 0
    assert "PASS migration" in capsys.readouterr().out
    TelegramBotAdapter.initialize.assert_not_called()


def test_migration_validator_uses_release_graph_for_head_assertions():
    source = (Path(__file__).resolve().parents[3] / "scripts/validate_migrations.py").read_text()
    assert "release_head = release_migration_head()" in source
    assert source.count("== [release_head]") == 4
    assert "get_heads() == [" not in source
    assert "EXPECTED_ALEMBIC_HEAD" not in source
