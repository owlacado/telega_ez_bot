import os
import secrets
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from hub.auth.service import create_manager
from hub.core.config import Settings
from hub.main import create_app

TEST_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://hub:hub_test_only@127.0.0.1:5437/technician_hub_test"
)


@pytest.fixture(scope="session", autouse=True)
def migrate_database() -> None:
    parsed = make_url(TEST_URL)
    if parsed.database != "technician_hub_test" or parsed.host not in {
        "localhost",
        "127.0.0.1",
        "test-db",
    }:
        raise RuntimeError("Tests may only reset the local technician_hub_test database.")
    api_root = Path(__file__).resolve().parents[1]
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=api_root,
        env={**os.environ, "DATABASE_URL": TEST_URL},
        check=True,
    )


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(TEST_URL, poolclass=NullPool)
    async with engine.begin() as connection:
        await connection.execute(
            text(
                "TRUNCATE technicians, calendars, managers, rate_buckets, "
                "audit_events, telegram_worker_states, telegram_processed_updates, "
                "google_oauth_attempts, calendar_connections, schedule_worker_states, "
                "accounting_mirror_worker_states "
                "RESTART IDENTITY CASCADE"
            )
        )
    yield engine
    await engine.dispose()


@pytest.fixture
async def app(engine: AsyncEngine):
    app = create_app(
        Settings(database_url=TEST_URL, app_env="test", allowed_origins=["http://127.0.0.1:3000"])
    )
    async with app.router.lifespan_context(app):
        yield app


@pytest.fixture
async def anonymous(app) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://127.0.0.1:3000",
        headers={"Origin": "http://127.0.0.1:3000", "X-Hub-Request": "1"},
    ) as client:
        yield client


@pytest.fixture
async def credentials(engine: AsyncEngine):
    password = secrets.token_urlsafe(24)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        manager = await create_manager(db, "test-manager", password)
    return {"username": manager.username, "password": password, "id": manager.id}


@pytest.fixture
async def client(anonymous: AsyncClient, credentials) -> AsyncIterator[AsyncClient]:
    response = await anonymous.post(
        "/api/auth/login",
        json={"username": credentials["username"], "password": credentials["password"]},
    )
    assert response.status_code == 200, response.text
    anonymous.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    yield anonymous


@pytest.fixture(autouse=True)
def forbid_live_telegram(monkeypatch):
    """Fail before any real Bot API operation, even if local credentials exist."""
    from hub.telegram.adapter import TelegramBotAdapter

    async def forbidden(*args, **kwargs):
        raise AssertionError("Automated tests must use the fake Telegram provider.")

    for method in (
        "initialize",
        "webhook_configured",
        "updates",
        "member",
        "send",
        "send_schedule",
        "answer_callback",
    ):
        monkeypatch.setattr(TelegramBotAdapter, method, forbidden)


@pytest.fixture(autouse=True)
def forbid_live_google(monkeypatch):
    import requests

    original = requests.sessions.Session.request

    def guarded(self, method, url, *args, **kwargs):
        from urllib.parse import urlparse

        host = (urlparse(url).hostname or "").lower()
        if host.endswith(("google.com", "googleapis.com")):
            raise AssertionError("Automated tests must not contact Google.")
        return original(self, method, url, *args, **kwargs)

    monkeypatch.setattr(requests.sessions.Session, "request", guarded)
