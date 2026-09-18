"""Separate opt-in schedule worker. Never starts a polling loop in FastAPI."""

import asyncio
import logging
import signal
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from hub.auth.security import now
from hub.core.config import Settings
from hub.schedule_delivery.delivery import deliver_one, purge
from hub.schedule_delivery.models import ScheduleWorkerState
from hub.schedule_delivery.scheduler import evaluate
from hub.telegram.types import ProviderError


class Worker:
    def __init__(self, settings, engine, lock_engine, provider, google_provider):
        self.settings, self.engine, self.lock_engine, self.provider = (
            settings,
            engine,
            lock_engine,
            provider,
        )
        self.factory, self.id = async_sessionmaker(engine, expire_on_commit=False), uuid4()
        self.request = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(
                    settings=settings,
                    session_factory=self.factory,
                    google_lock_engine=lock_engine,
                    google_provider=google_provider,
                )
            ),
            state=SimpleNamespace(manager_id=None),
        )

    async def state(self, status, error=None):
        async with self.factory() as db, db.begin():
            await db.execute(
                insert(ScheduleWorkerState)
                .values(worker_id=self.id, status=status, heartbeat_at=now(), error_code=error)
                .on_conflict_do_update(
                    index_elements=["worker_id"],
                    set_={"status": status, "heartbeat_at": now(), "error_code": error},
                )
            )

    async def cycle(self):
        await self.state("RUNNING")
        await evaluate(self.request)
        for _ in range(20):
            if not await deliver_one(self.factory, self.lock_engine, self.provider, self.settings):
                break
        await purge(self.factory)
        await self.state("RUNNING")

    async def run(self, stop, *, max_cycles=None):
        if not self.settings.schedule_delivery_enabled:
            return
        try:
            identity = await self.provider.initialize()
            if (
                identity.id != self.settings.telegram_expected_bot_id
                or identity.username.lower()
                != (self.settings.telegram_expected_bot_username or "").lower()
            ):
                raise ProviderError("BOT_IDENTITY_MISMATCH")
            if await self.provider.webhook_configured():
                raise ProviderError("EXISTING_WEBHOOK_REFUSED")
            count = 0
            while not stop.is_set() and (max_cycles is None or count < max_cycles):
                try:
                    await self.cycle()
                except Exception:
                    await self.state("RETRYING", "PROCESSING_FAILED")
                count += 1
                if max_cycles is not None and count >= max_cycles:
                    break
                try:
                    await asyncio.wait_for(stop.wait(), timeout=60)
                except TimeoutError:
                    pass
            await self.state("STOPPED")
        except Exception:
            await self.state("FAILED", "PROCESSING_FAILED")
            raise ProviderError("PROCESSING_FAILED") from None
        finally:
            await self.provider.close()


async def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        settings = Settings()
    except Exception:
        raise SystemExit("Schedule worker: invalid configuration.") from None
    if not settings.schedule_delivery_enabled:
        print("Schedule delivery is disabled. No providers initialized.")
        return
    if settings.telegram_mode != "real" or settings.google_mode != "real":
        raise SystemExit("Fake providers require the isolated injected test harness.")
    from hub.google_calendar.provider import GoogleCalendarProvider
    from hub.telegram.adapter import TelegramBotAdapter

    engine = create_async_engine(settings.database_url, hide_parameters=True)
    locks = create_async_engine(settings.database_url, poolclass=NullPool, hide_parameters=True)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))
    try:
        await Worker(
            settings, engine, locks, TelegramBotAdapter(settings), GoogleCalendarProvider(settings)
        ).run(stop)
    finally:
        await locks.dispose()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
