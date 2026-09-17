"""Opt-in long polling. Importing this module or starting the web API does not run it."""

import asyncio
import json
import logging
import signal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

import hub.models  # noqa: F401
from hub.auth.security import now
from hub.core.config import Settings
from hub.integrations.ports import TelegramProvider
from hub.telegram.delivery import deliver_one, recover_processing
from hub.telegram.locks import advisory_guard
from hub.telegram.models import TelegramWorkerState
from hub.telegram.types import ProviderError
from hub.telegram.updates import process_update

logger = logging.getLogger("hub.telegram.worker")


class Worker:
    def __init__(self, settings: Settings, engine: AsyncEngine, provider: TelegramProvider):
        self.settings, self.engine, self.provider = settings, engine, provider
        self.factory = async_sessionmaker(engine, expire_on_commit=False)
        self.bot_id = settings.telegram_expected_bot_id

    async def state(self, status: str, error: str | None = None) -> None:
        logger.info(
            json.dumps({"event": "telegram_worker_state", "status": status, "error": error})
        )
        async with self.factory() as db, db.begin():
            await db.execute(
                insert(TelegramWorkerState)
                .values(bot_id=self.bot_id, status=status, error_code=error, heartbeat_at=now())
                .on_conflict_do_update(
                    index_elements=["bot_id"],
                    set_={"status": status, "error_code": error, "heartbeat_at": now()},
                )
            )

    async def startup(self) -> None:
        identity = await self.provider.initialize()
        if (
            identity.id != self.bot_id
            or identity.username.lower()
            != (self.settings.telegram_expected_bot_username or "").lower()
        ):
            raise ProviderError("BOT_IDENTITY_MISMATCH")
        if await self.provider.webhook_configured():
            raise ProviderError("EXISTING_WEBHOOK_REFUSED")
        await recover_processing(self.factory, self.bot_id)
        await self.state("RUNNING")

    async def cycle(self) -> None:
        await self.state("RUNNING")
        for _ in range(10):
            if not await deliver_one(self.factory, self.engine, self.provider, self.bot_id):
                break
            await self.state("RUNNING")
        async with self.factory() as db:
            offset = await db.scalar(
                select(TelegramWorkerState.next_update_id).where(
                    TelegramWorkerState.bot_id == self.bot_id
                )
            )
        updates = await self.provider.updates(offset)
        for event in sorted(updates, key=lambda value: value.update_id):
            result = await process_update(self.factory, self.provider, event, self.bot_id)
            # Processing and its deduplication record are committed before offset advancement.
            async with self.factory() as db, db.begin():
                state = await db.get(TelegramWorkerState, self.bot_id, with_for_update=True)
                state.next_update_id = max(state.next_update_id or 0, event.update_id + 1)
                state.heartbeat_at = now()
            if result.reply and event.chat_id is not None:
                try:
                    await self.provider.send(event.chat_id, result.reply)
                except ProviderError:
                    # Command receipts are best effort, do not blindly replay an uncertain send.
                    logger.warning("Telegram command response could not be confirmed")

    async def run(self, stop: asyncio.Event, *, max_cycles: int | None = None) -> None:
        if self.settings.telegram_mode == "disabled":
            return
        if not self.bot_id:
            raise ProviderError("BOT_NOT_CONFIGURED")
        async with advisory_guard(self.engine, "telegram-poller", self.bot_id, wait=False):
            try:
                await self.startup()
                attempts, cycles = 0, 0
                while not stop.is_set() and (max_cycles is None or cycles < max_cycles):
                    try:
                        await self.cycle()
                        attempts = 0
                        cycles += 1
                    except ProviderError as error:
                        if (
                            error.code
                            not in {"NETWORK_UNCERTAIN", "RATE_LIMITED", "PROVIDER_UNAVAILABLE"}
                            or attempts >= 5
                        ):
                            raise
                        attempts += 1
                        await self.state("RETRYING", error.code)
                        delay = min(60, max(2**attempts, error.retry_after))
                        try:
                            await asyncio.wait_for(stop.wait(), timeout=delay)
                        except TimeoutError:
                            pass
                await self.state("STOPPED")
            except ProviderError as error:
                await self.state("FAILED", error.code)
                raise
            except Exception:
                await self.state("FAILED", "PROCESSING_FAILED")
                raise ProviderError("PROCESSING_FAILED") from None
            finally:
                await self.provider.close()


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        settings = Settings()
    except Exception:
        raise SystemExit("Telegram worker stopped: invalid local configuration.") from None
    if settings.telegram_mode == "disabled":
        print("Telegram is disabled. No provider was initialized.")
        return
    if settings.telegram_mode != "real":
        raise SystemExit("Fake providers are injected only by the isolated test harness.")
    from hub.telegram.adapter import TelegramBotAdapter

    engine = create_async_engine(settings.database_url, pool_pre_ping=True, hide_parameters=True)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))
    try:
        await Worker(settings, engine, TelegramBotAdapter(settings)).run(stop)
    except ProviderError as error:
        raise SystemExit(f"Telegram worker stopped: {error.code}") from None
    except Exception:
        raise SystemExit(
            "Telegram worker stopped. Check local configuration and worker state."
        ) from None
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
