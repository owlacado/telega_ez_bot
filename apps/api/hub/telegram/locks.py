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
    # Session-level lock on a dedicated AUTOCOMMIT connection: no transaction spans I/O.
    async with engine.connect() as raw:
        connection = await raw.execution_options(isolation_level="AUTOCOMMIT")
        key = lock_key(namespace, identifier)
        if wait:
            await connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": key})
        elif not await connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": key}):
            raise RuntimeError("POLLER_ALREADY_RUNNING")
        try:
            yield
        finally:
            await connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": key})
