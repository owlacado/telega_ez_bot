"""Render deployment guards; all tests use synthetic configuration and processes."""

import os
import signal
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from hub import render_runtime as runtime


@pytest.fixture
def render_env(monkeypatch):
    values = {
        "RENDER_DATABASE_URL": "postgresql://hub:synthetic@private.example:5432/isolated_test",
        "PUBLIC_APP_ORIGIN": "https://pilot.example.test",
        "APP_ENV": "pilot",
        "COOKIE_SECURE": "true",
        "DEBUG": "false",
        "ALLOW_FAKE_PROVIDERS": "false",
        "TELEGRAM_MODE": "disabled",
        "GOOGLE_MODE": "disabled",
        "SCHEDULE_DELIVERY_ENABLED": "false",
        "RENDER_GIT_COMMIT": "a" * 40,
        "RENDER": "true",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    for key in ("GOOGLE_OAUTH_REDIRECT_URI", "DATABASE_URL", "ALLOWED_ORIGINS"):
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


def test_render_internal_database_and_exact_origin_are_derived(render_env):
    settings = runtime.prepare_environment()
    assert settings.database_url == (
        "postgresql+asyncpg://hub:synthetic@private.example:5432/isolated_test"
    )
    assert settings.allowed_origins == ["https://pilot.example.test"]
    assert settings.allowed_hosts == ["127.0.0.1", "api", "localhost", "pilot.example.test"]
    assert settings.release_commit == "a" * 40
    assert os.environ["DATABASE_URL"] == settings.database_url


@pytest.mark.parametrize(
    "key,value",
    [
        ("RENDER_DATABASE_URL", "postgresql+asyncpg://hub:pass@127.0.0.1/db"),
        ("RENDER_DATABASE_URL", "postgresql://hub:pass@localhost:5436/db"),
        ("PUBLIC_APP_ORIGIN", "https://pilot.example.test/path"),
        ("PUBLIC_APP_ORIGIN", "http://pilot.example.test"),
        ("APP_ENV", "test"),
        ("ALLOW_FAKE_PROVIDERS", "true"),
        ("GOOGLE_MODE", "fake"),
        ("TELEGRAM_MODE", "fake"),
        ("RENDER_GIT_COMMIT", "development"),
    ],
)
def test_render_rejects_unsafe_configuration(render_env, key, value):
    render_env.setenv(key, value)
    with pytest.raises(ValueError):
        runtime.prepare_environment()


def test_google_callback_matches_public_origin(render_env):
    render_env.setenv("GOOGLE_MODE", "real")
    render_env.setenv("GOOGLE_CLIENT_ID", "synthetic-client")
    render_env.setenv("GOOGLE_CLIENT_SECRET", "synthetic-secret")
    render_env.setenv(
        "GOOGLE_CALENDAR_CREDENTIAL_ENCRYPTION_KEY",
        Fernet.generate_key().decode(),
    )
    settings = runtime.prepare_environment()
    assert settings.google_oauth_redirect_uri == (
        "https://pilot.example.test/api/calendar-connections/google/callback"
    )
    render_env.setenv("GOOGLE_OAUTH_REDIRECT_URI", "https://attacker.example/callback")
    with pytest.raises(ValueError, match="redirect"):
        runtime.prepare_environment()


def test_only_enabled_worker_children_are_started(render_env):
    settings = runtime.prepare_environment()
    assert (runtime.API_DIRECTORY / "alembic.ini").is_file()
    assert runtime.child_specs("worker", settings) == []
    assert [name for name, _ in runtime.child_specs("web", settings)] == [
        "api",
        "next",
        "router",
    ]
    assert "--no-proxy-headers" in runtime.child_specs("web", settings)[0][1]


def test_enabled_worker_features_have_three_independent_children(render_env):
    render_env.setenv("TELEGRAM_MODE", "real")
    render_env.setenv("TELEGRAM_EXPECTED_BOT_ID", "123")
    render_env.setenv("TELEGRAM_EXPECTED_BOT_USERNAME", "TestPilotBot")
    render_env.setenv("TELEGRAM_BOT_TOKEN", "synthetic-token")
    render_env.setenv("GOOGLE_MODE", "real")
    render_env.setenv("GOOGLE_CLIENT_ID", "synthetic-client")
    render_env.setenv("GOOGLE_CLIENT_SECRET", "synthetic-secret")
    render_env.setenv("GOOGLE_CALENDAR_CREDENTIAL_ENCRYPTION_KEY", Fernet.generate_key().decode())
    render_env.setenv("SCHEDULE_DELIVERY_ENABLED", "true")
    render_env.setenv("SCHEDULE_PAYLOAD_ENCRYPTION_KEY", Fernet.generate_key().decode())
    settings = runtime.prepare_environment()
    assert [name for name, _ in runtime.child_specs("worker", settings)] == [
        "telegram",
        "schedule",
        "mirror",
    ]


class FakeProcess:
    next_pid = 100

    def __init__(self, command, *, env, start_new_session):
        self.command = command
        self.env = env
        self.pid = FakeProcess.next_pid
        FakeProcess.next_pid += 1
        self.result = None
        assert start_new_session

    def poll(self):
        return self.result

    def wait(self, timeout):
        self.result = 0
        return 0


def test_child_exit_fails_group_and_terminates_siblings(monkeypatch):
    processes = []
    signals = []

    def spawn(*args, **kwargs):
        child = FakeProcess(*args, **kwargs)
        processes.append(child)
        if len(processes) == 2:
            child.result = 17
        return child

    monkeypatch.setattr(runtime.subprocess, "Popen", spawn)
    monkeypatch.setattr(
        runtime.os, "killpg", lambda pid, sig: signals.append((pid, sig)), raising=False
    )
    assert runtime.supervise([("telegram", ("one",)), ("mirror", ("two",))]) == 1
    assert (processes[0].pid, signal.SIGTERM) in signals


def test_sigterm_fans_out_to_all_enabled_children(monkeypatch):
    processes = []
    signals = []
    handlers = {}

    def spawn(*args, **kwargs):
        child = FakeProcess(*args, **kwargs)
        processes.append(child)
        return child

    def set_handler(sig, callback):
        previous = handlers.get(sig, signal.SIG_DFL)
        handlers[sig] = callback
        return previous

    def stop_on_first_sleep(_seconds):
        handlers[signal.SIGTERM](signal.SIGTERM, None)

    monkeypatch.setattr(runtime.subprocess, "Popen", spawn)
    monkeypatch.setattr(runtime.signal, "signal", set_handler)
    monkeypatch.setattr(runtime.time, "sleep", stop_on_first_sleep)
    monkeypatch.setattr(
        runtime.os, "killpg", lambda pid, sig: signals.append((pid, sig)), raising=False
    )
    assert runtime.supervise([("telegram", ("one",)), ("schedule", ("two",))]) == 0
    assert signals == [(child.pid, signal.SIGTERM) for child in processes]


def test_router_does_not_forward_untrusted_proxy_headers():
    caddyfile = (
        Path(__file__).resolve().parents[3] / "infrastructure/render.Caddyfile"
    ).read_text()
    for name in ("Forwarded", "X-Forwarded-For", "X-Forwarded-Host", "X-Forwarded-Proto"):
        assert caddyfile.count(f"header_up -{name}") == 2
    assert "127.0.0.1:8000" in caddyfile
    assert "127.0.0.1:3000" in caddyfile
