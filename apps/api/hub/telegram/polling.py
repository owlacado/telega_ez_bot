"""DB-clock polling ownership, fenced by the existing session advisory lock.

Keep the advisory session for the entire owner lifetime (including HTTP cleanup).
This also serializes the first rolling upgrade against pre-lease workers. No SQL
transaction is held over provider calls. Expiry alone cannot evict a live session.
"""

import asyncio
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import func, or_, text, update
from sqlalchemy.dialects.postgresql import insert

from hub.telegram.locks import lock_key
from hub.telegram.models import TelegramWorkerState

LEASE_SECONDS = 90
RENEW_SECONDS = 15
WAIT_SECONDS = 2
POLL_SECONDS = 40  # Hard client bound; Telegram's long-poll timeout remains 25s.


class LeaseLost(Exception):
    """Fail closed; never reuse an expired token or a reconnected DB session."""


class PollingLease:
    def __init__(self, engine, bot_id):
        self.engine, self.bot_id = engine, bot_id
        self.owner = uuid4()
        self.connection = None
        self.pid = None
        self.held = False
        self.lock = asyncio.Lock()
        self.key = lock_key("telegram-poller", bot_id)

    async def acquire(self):
        self.connection = await self.engine.connect()
        self.connection = await self.connection.execution_options(isolation_level="AUTOCOMMIT")
        try:
            self.held = bool(
                await self.connection.scalar(
                    text("SELECT pg_try_advisory_lock(:key)"), {"key": self.key}
                )
            )
            if not self.held:
                await self.close(release=False)
                return False
            self.pid = await self.connection.scalar(text("SELECT pg_backend_pid()"))
            await self.connection.execute(
                insert(TelegramWorkerState)
                .values(bot_id=self.bot_id, status="STOPPED")
                .on_conflict_do_nothing(index_elements=["bot_id"])
            )
            acquired = await self.connection.scalar(
                update(TelegramWorkerState)
                .where(
                    TelegramWorkerState.bot_id == self.bot_id,
                    or_(
                        TelegramWorkerState.poll_owner.is_(None),
                        TelegramWorkerState.poll_lease_until <= func.clock_timestamp(),
                    ),
                )
                .values(
                    poll_owner=self.owner,
                    poll_lease_until=func.clock_timestamp() + timedelta(seconds=LEASE_SECONDS),
                )
                .returning(TelegramWorkerState.bot_id)
            )
            if acquired is None:
                await self.close(release=False)
                return False
            return True
        except BaseException:
            await self.close(release=False)
            raise

    async def write(self, **values):
        async with self.lock:
            if self.connection is None or self.connection.invalidated:
                raise LeaseLost()
            try:
                result = await self.connection.scalar(
                    update(TelegramWorkerState)
                    .where(
                        TelegramWorkerState.bot_id == self.bot_id,
                        TelegramWorkerState.poll_owner == self.owner,
                        TelegramWorkerState.poll_lease_until > func.clock_timestamp(),
                        func.pg_backend_pid() == self.pid,
                    )
                    .values(**values)
                    .returning(TelegramWorkerState.bot_id)
                )
            except Exception:
                raise LeaseLost() from None
            if result is None:
                raise LeaseLost()

    async def renew(self):
        await self.write(
            poll_lease_until=func.clock_timestamp() + timedelta(seconds=LEASE_SECONDS),
            heartbeat_at=func.clock_timestamp(),
        )

    async def maintain(self):
        while True:
            await asyncio.sleep(RENEW_SECONDS)
            await self.renew()

    async def close(self, *, release):
        connection, self.connection = self.connection, None
        if connection is None:
            return
        try:
            if not connection.invalidated:
                if release:
                    # A stale owner's cleanup must never clear its successor's token.
                    await connection.execute(
                        update(TelegramWorkerState)
                        .where(
                            TelegramWorkerState.bot_id == self.bot_id,
                            TelegramWorkerState.poll_owner == self.owner,
                            func.pg_backend_pid() == self.pid,
                        )
                        .values(poll_owner=None, poll_lease_until=None)
                    )
                if self.held:
                    await connection.execute(
                        text("SELECT pg_advisory_unlock(:key)"), {"key": self.key}
                    )
        except Exception:
            # Never return a possibly still-locked physical session to the pool.
            await connection.invalidate()
        finally:
            self.held = False
            await connection.close()
