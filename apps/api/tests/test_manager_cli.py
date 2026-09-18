"""Actual CLI entrypoint, isolated PostgreSQL, synthetic stdin-only credentials."""

import asyncio
import json
import os
import secrets
import subprocess
import sys

import pytest
from sqlalchemy import func, select, update

from hub.audit.models import AuditEvent
from hub.auth.models import Manager, ManagerSession
from tests.conftest import TEST_URL

# Test-side prompt simulation, not a product flag or endpoint. A separate Linux
# PTY test below exercises getpass itself inside the actual Docker image.
BOOTSTRAP = """
import getpass, json, sys
from hub.auth import cli
value = json.load(sys.stdin)
class Terminal:
    def isatty(self): return True
sys.stdin = Terminal()
answers = iter(value['answers'])
getpass.getpass = lambda prompt: next(answers)
sys.argv = ['hub.auth.cli', value.get('command','create-manager'), '--username', value['username']]
if value.get('failure'):
    async def fail(*args):
        if value['failure'] == 'hash':
            from argon2.exceptions import HashingError
            raise HashingError(value['answers'][0])
        raise RuntimeError(value['answers'][0])
    cli.create_manager = fail
if value.get('audit_failure'):
    import hub.auth.service
    def fail_audit(*args, **kwargs): raise RuntimeError(value['answers'][0])
    hub.auth.service.audit = fail_audit
cli.main()
"""


def cli_environment(database=TEST_URL):
    return {
        **os.environ,
        "DATABASE_URL": database,
        "APP_ENV": "test",
        "GOOGLE_MODE": "disabled",
        "TELEGRAM_MODE": "disabled",
        "SCHEDULE_DELIVERY_ENABLED": "false",
    }


async def invoke(username="manager", password=None, confirmation=None, **options):
    password = password if password is not None else secrets.token_urlsafe(24)
    confirmation = confirmation if confirmation is not None else password
    database = options.pop("database", TEST_URL)
    result = await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-c", BOOTSTRAP],
        input=json.dumps(dict(username=username, answers=[password, confirmation], **options)),
        text=True,
        capture_output=True,
        env=cli_environment(database),
        timeout=30,
    )
    output = result.stdout + result.stderr
    if password and password in output:
        pytest.fail("CLI exposed a synthetic credential; output withheld.", pytrace=False)
    if "Traceback" in output or "$argon2" in output:
        pytest.fail("CLI exposed internal diagnostics; output withheld.", pytrace=False)
    return result.returncode, output


async def state(engine):
    async with engine.connect() as db:
        return tuple(
            [
                await db.scalar(select(func.count()).select_from(model))
                for model in (Manager, ManagerSession, AuditEvent)
            ]
        )


async def test_cli_creates_audited_manager_and_api_login(anonymous, engine):
    password = secrets.token_urlsafe(24)
    code, message = await invoke("  Manager  ", password)
    assert code == 0 and "Manager created." in message
    assert await state(engine) == (1, 0, 1)
    async with engine.connect() as db:
        manager = (await db.execute(select(Manager.id, Manager.username, Manager.is_active))).one()
        event = (await db.execute(select(AuditEvent.actor_id, AuditEvent.target_id))).one()
        assert manager.username == "manager" and manager.is_active
        assert event.actor_id == event.target_id == manager.id
    response = await anonymous.post(
        "/api/auth/login", json={"username": "manager", "password": password}
    )
    assert response.status_code == 200
    assert (await anonymous.get("/api/auth/me")).status_code == 200


@pytest.mark.parametrize("password", ["x" * 14, "x" * 128, "é" * 14, " " * 14])
async def test_documented_password_boundaries_no_hidden_composition_rule(engine, password):
    code, _ = await invoke(password=password)
    assert code == 0 and await state(engine) == (1, 0, 1)


@pytest.mark.parametrize("password", ["x" * 13, "x" * 129, ""])
async def test_cli_password_policy_actionable_and_atomic(engine, password):
    code, message = await invoke(password=password)
    assert code == 1 and "[PASSWORD_POLICY]" in message and "14-128" in message
    assert await state(engine) == (0, 0, 0)


async def test_cli_password_mismatch_does_not_write(engine):
    code, message = await invoke(confirmation=secrets.token_urlsafe(24))
    assert code == 1 and "Passwords do not match." in message
    assert await state(engine) == (0, 0, 0)


@pytest.mark.parametrize("username", [" ", "x" * 101])
async def test_cli_username_policy(engine, username):
    code, message = await invoke(username)
    assert code == 1 and "[USERNAME_POLICY]" in message
    assert await state(engine) == (0, 0, 0)


@pytest.mark.parametrize("inactive", [False, True])
async def test_duplicate_username_including_inactive(engine, inactive):
    assert (await invoke())[0] == 0
    if inactive:
        async with engine.begin() as db:
            await db.execute(update(Manager).values(is_active=False))
    code, message = await invoke(" MANAGER ")
    assert code == 1 and "[USERNAME_EXISTS]" in message
    assert await state(engine) == (1, 0, 1)


async def test_two_concurrent_cli_creations_one_commit(engine):
    results = await asyncio.gather(invoke(), invoke())
    assert sorted(code for code, _ in results) == [0, 1]
    assert any("[USERNAME_EXISTS]" in message for _, message in results)
    assert await state(engine) == (1, 0, 1)


async def test_database_unavailable_safe_message(engine):
    code, message = await invoke(
        database="postgresql+asyncpg://hub:synthetic_unused@127.0.0.1:1/technician_hub_test"
    )
    assert code == 1 and "[DATABASE_UNAVAILABLE]" in message
    assert "synthetic_unused" not in message
    assert await state(engine) == (0, 0, 0)


@pytest.mark.parametrize(
    "failure,expected", [("hash", "HASHING_UNAVAILABLE"), ("other", "PROVISIONING_FAILED")]
)
async def test_service_failures_do_not_echo_exception(engine, failure, expected):
    code, message = await invoke(failure=failure)
    assert code == 1 and f"[{expected}]" in message
    assert await state(engine) == (0, 0, 0)


async def test_audit_failure_rolls_back_manager(engine):
    code, message = await invoke(audit_failure=True)
    assert code == 1 and "[PROVISIONING_FAILED]" in message
    assert await state(engine) == (0, 0, 0)


async def test_noninteractive_cli_refuses_password_input(engine):
    result = await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-m", "hub.auth.cli", "create-manager", "--username", "manager"],
        input="",
        text=True,
        capture_output=True,
        env=cli_environment(),
        timeout=30,
    )
    assert result.returncode == 1 and "interactive terminal" in result.stderr
    assert await state(engine) == (0, 0, 0)


@pytest.mark.skipif(sys.platform == "win32", reason="Real POSIX TTY is verified in Docker")
@pytest.mark.parametrize("valid", [True, False])
async def test_real_tty_hidden_prompt_cli(engine, valid):
    password = secrets.token_urlsafe(24) if valid else secrets.token_hex(6)
    result = await asyncio.to_thread(
        subprocess.run,
        [sys.executable, "-m", "tests.cli_terminal"],
        input=json.dumps({"username": "manager", "password": password}),
        text=True,
        capture_output=True,
        env=cli_environment(),
        timeout=40,
    )
    assert result.returncode == 0
    outcome = json.loads(result.stdout)
    assert outcome["prompts"] == 2 and not outcome["secret_echoed"]
    assert outcome["created"] is valid
    assert outcome["exit_code"] == (0 if valid else 1)
    assert outcome["safe_code"] == (None if valid else "PASSWORD_POLICY")
    assert await state(engine) == ((1, 0, 1) if valid else (0, 0, 0))
