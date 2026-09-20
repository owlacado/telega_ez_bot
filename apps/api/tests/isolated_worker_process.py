"""Run real worker loops with process-local fakes in the guarded restart-test stack."""

import asyncio
import signal
import sys

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from hub.accounting_mirrors.worker import Worker as MirrorWorker
from hub.core.config import Settings
from hub.google_calendar.fake import FakeCalendarProvider
from hub.schedule_delivery.worker import Worker as ScheduleWorker
from hub.telegram.worker import Worker as TelegramWorker
from tests.fakes import FakeTelegram


def install_stop(stop: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for event in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(event, stop.set)
        except NotImplementedError:
            signal.signal(event, lambda *_: loop.call_soon_threadsafe(stop.set))


async def run(kind: str) -> None:
    settings = Settings()
    if not settings.allow_fake_providers or settings.app_env != "test":
        raise SystemExit("Isolated worker process requires guarded fake-provider configuration.")
    engine = create_async_engine(settings.database_url, pool_pre_ping=True, hide_parameters=True)
    stop = asyncio.Event()
    install_stop(stop)
    try:
        if kind == "telegram":
            await TelegramWorker(settings, engine, FakeTelegram()).run(stop)
        elif kind == "schedule":
            locks = create_async_engine(
                settings.database_url, poolclass=NullPool, hide_parameters=True
            )
            try:
                await ScheduleWorker(
                    settings,
                    engine,
                    locks,
                    FakeTelegram(),
                    FakeCalendarProvider(),
                ).run(stop)
            finally:
                await locks.dispose()
        elif kind == "mirror":
            worker = MirrorWorker(
                async_sessionmaker(engine, expire_on_commit=False),
                settings,
                FakeCalendarProvider(),
            )
            install_stop(worker.stop)
            await worker.run()
        else:
            raise SystemExit("Unknown isolated worker kind.")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(run(sys.argv[1] if len(sys.argv) == 2 else ""))
