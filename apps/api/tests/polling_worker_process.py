"""Test-only process: real worker, shared loopback fake getUpdates endpoint."""

import asyncio
import sys
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from sqlalchemy.ext.asyncio import create_async_engine

from hub.core.config import Settings
from hub.telegram import polling, worker
from hub.telegram.types import TrustedEvent
from tests.fakes import FakeTelegram


async def main():
    url, stop_path = sys.argv[1:]
    settings = Settings()
    if (
        settings.app_env != "test"
        or not settings.allow_fake_providers
        or settings.telegram_mode != "fake"
        or urlsplit(url).hostname != "127.0.0.1"
    ):
        raise SystemExit("Synthetic local rolling-test configuration required")
    polling.LEASE_SECONDS, polling.RENEW_SECONDS = 2, 0.2
    worker.WAIT_SECONDS, worker.POLL_SECONDS = 0.05, 0.5
    stop = asyncio.Event()

    class SharedFake(FakeTelegram):
        async def updates(self, offset):
            async with httpx.AsyncClient(trust_env=False) as client:
                response = await client.post(url, json={"offset": offset}, timeout=1)
            return [TrustedEvent(value, "IGNORED") for value in response.json()]

    async def watch():
        while not stop.is_set():
            if Path(stop_path).exists():
                stop.set()
            await asyncio.sleep(0.02)

    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    watcher = asyncio.create_task(watch())
    try:
        await worker.Worker(settings, engine, SharedFake()).run(stop)
    finally:
        stop.set()
        await watcher
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
