import asyncio
import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


def lock_key(namespace: str, identifier: int | UUID) -> int:
    return int.from_bytes(
        hashlib.sha256(f"{namespace}:{identifier}".encode()).digest()[:8], signed=True
    )


@asynccontextmanager
async def advisory_guard(
    engine: AsyncEngine, namespace: str, identifier: int | UUID, *, wait: bool = True
) -> AsyncIterator[None]:
    # Waiters must return their connections: the lock owner needs another pooled
    # connection to commit/finish. Blocking pg_advisory_lock can exhaust that pool.
    key = lock_key(namespace, identifier)
    while True:
        async with engine.connect() as raw:
            connection = await raw.execution_options(isolation_level="AUTOCOMMIT")
            acquired = await connection.scalar(
                text("SELECT pg_try_advisory_lock(:key)"), {"key": key}
            )
            if acquired:
                try:
                    yield
                finally:
                    await connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
                return
        if not wait:
            raise RuntimeError("POLLER_ALREADY_RUNNING")
        # No SQL transaction, connection or advisory lock is held while waiting.
        await asyncio.sleep(0.05)
