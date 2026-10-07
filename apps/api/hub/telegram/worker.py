"""Opt-in long polling. Importing this module or starting the web API does not run it."""

import asyncio
import json
import logging
import signal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

import hub.models  # noqa: F401
from hub.auth.security import now
from hub.core.config import Settings
from hub.integrations.ports import TelegramProvider
from hub.telegram.delivery import deliver_one, recover_processing
from hub.telegram.models import TelegramProcessedUpdate, TelegramWorkerState
from hub.telegram.polling import POLL_SECONDS, WAIT_SECONDS, LeaseLost, PollingLease
from hub.telegram.types import ProviderError
from hub.telegram.updates import process_update

logger = logging.getLogger("hub.telegram.worker")


class Worker:
    def __init__(self, settings: Settings, engine: AsyncEngine, provider: TelegramProvider):
        self.settings, self.engine, self.provider = settings, engine, provider
        self.factory = async_sessionmaker(engine, expire_on_commit=False)
        self.bot_id = settings.telegram_expected_bot_id
        self.lease = None
        self.poll_uncertain = False
        self.stop = asyncio.Event()

    async def state(self, status: str, error: str | None = None) -> None:
        logger.info(
            json.dumps({"event": "telegram_worker_state", "status": status, "error": error})
        )
        if self.lease is None:
            raise LeaseLost()
        await self.lease.write(status=status, error_code=error, heartbeat_at=func.clock_timestamp())

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
            # Telegram may choose a lower random update ID after a week without updates.
            # Do not acknowledge a new epoch with the preceding epoch's high offset.
            previous = (
                await db.get(TelegramProcessedUpdate, (self.bot_id, offset - 1)) if offset else None
            )
            if offset and (
                not previous or (now() - previous.processed_at).total_seconds() >= 6 * 86400
            ):
                offset = None
        if self.stop.is_set():
            return
        await self.lease.renew()
        self.poll_uncertain = True
        try:
            async with asyncio.timeout(POLL_SECONDS):
                updates = await self.provider.updates(offset)
            self.poll_uncertain = False
        except TimeoutError:
            raise ProviderError("NETWORK_UNCERTAIN") from None
        await self.lease.renew()
        for event in sorted(updates, key=lambda value: value.update_id):
            result = await process_update(
                self.factory, self.provider, event, self.bot_id, settings=self.settings
            )
            # Processing and its deduplication record are committed before offset advancement.
            await self.lease.write(
                next_update_id=event.update_id + 1, heartbeat_at=func.clock_timestamp()
            )
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
        self.stop = stop
        while not stop.is_set():
            lease = PollingLease(self.engine, self.bot_id)
            if not await lease.acquire():
                # A standby is healthy. Do not overwrite the active owner's status/offset.
                logger.info('{"event":"telegram_poller","status":"WAITING_FOR_LEASE"}')
                try:
                    await asyncio.wait_for(stop.wait(), timeout=WAIT_SECONDS)
                except TimeoutError:
                    pass
                continue
            self.lease = lease
            owned = asyncio.create_task(self.owned_run(stop, max_cycles))
            renewal = asyncio.create_task(lease.maintain())
            try:
                done, _ = await asyncio.wait({owned, renewal}, return_when=asyncio.FIRST_COMPLETED)
                if renewal in done:
                    await renewal  # Lease loss cancels in-flight work before cleanup/unlock.
                await owned
                return
            except LeaseLost:
                logger.warning('{"event":"telegram_poller","status":"LEASE_LOST"}')
            finally:
                owned.cancel()
                renewal.cancel()
                await asyncio.gather(owned, renewal, return_exceptions=True)
                try:
                    await self.provider.close()
                finally:
                    # On cancellation/DB loss/crash, retain the expiry as a drain
                    # window for any remote poll whose response we cannot observe.
                    await lease.close(release=not self.poll_uncertain)
                    self.lease = None

    async def owned_run(self, stop, max_cycles):
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
                        or error.retry_after > 3600
                    ):
                        raise
                    attempts += 1
                    await self.state("RETRYING", error.code)
                    try:
                        await asyncio.wait_for(
                            stop.wait(), timeout=max(2**attempts, error.retry_after)
                        )
                    except TimeoutError:
                        pass
            await self.state("STOPPED")
        except LeaseLost:
            raise
        except ProviderError as error:
            await self.state("FAILED", error.code)
            raise
        except Exception:
            await self.state("FAILED", "PROCESSING_FAILED")
            raise ProviderError("PROCESSING_FAILED") from None


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
