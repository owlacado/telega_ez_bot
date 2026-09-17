import os
import subprocess
import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

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
        await connection.execute(text("TRUNCATE technicians, calendars RESTART IDENTITY CASCADE"))
    yield engine
    await engine.dispose()


@pytest.fixture
async def client(engine: AsyncEngine) -> AsyncIterator[AsyncClient]:
    app = create_app(Settings(database_url=TEST_URL, app_env="test"))
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test.local"
        ) as client:
            yield client
