import hashlib
import hmac
import secrets
from datetime import UTC, datetime

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from argon2.low_level import Type
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from hub.auth.models import RateBucket


def now() -> datetime:
    return datetime.now(UTC)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def random_token() -> str:
    return secrets.token_urlsafe(32)


def csrf_for(session_token: str) -> str:
    return hmac.new(session_token.encode(), b"technician-hub:csrf:v1", hashlib.sha256).hexdigest()


def password_hasher() -> PasswordHasher:
    return PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4, type=Type.ID)


def verify_password(encoded: str, password: str) -> bool:
    try:
        return password_hasher().verify(encoded, password)
    except (VerificationError, InvalidHashError):
        return False


async def rate_limit(db: AsyncSession, key: str, *, limit: int, seconds: int) -> None:
    hashed = digest(key)
    moment = now()
    await db.execute(
        insert(RateBucket)
        .values(key_hash=hashed, count=0, window_start=moment)
        .on_conflict_do_nothing()
    )
    bucket = await db.scalar(
        select(RateBucket).where(RateBucket.key_hash == hashed).with_for_update()
    )
    assert bucket is not None
    if (moment - bucket.window_start).total_seconds() >= seconds:
        bucket.count, bucket.window_start = 0, moment
    if bucket.count >= limit:
        raise HTTPException(429, "Too many attempts. Try again later.")
    bucket.count += 1
