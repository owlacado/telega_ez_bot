from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from hub.audit.service import audit
from hub.auth.models import Manager, ManagerSession
from hub.auth.security import (
    digest,
    now,
    password_hasher,
    random_token,
    rate_limit,
    verify_password,
)
from hub.core.config import Settings


class InvalidManagerUsername(ValueError):
    """Safe type for provisioning policy failures; never contains user input."""


class InvalidManagerPassword(ValueError):
    """Safe type for provisioning policy failures; never contains the password."""


async def create_manager(db: AsyncSession, username: str, password: str) -> Manager:
    normalized = username.strip().lower()
    if not normalized or len(normalized) > 100:
        raise InvalidManagerUsername()
    if not 14 <= len(password) <= 128:
        raise InvalidManagerPassword()
    hashed = await run_in_threadpool(password_hasher().hash, password)
    manager = Manager(username=normalized, password_hash=hashed)
    db.add(manager)
    await db.flush()
    audit(db, "manager.created", manager.id, actor_id=manager.id)
    await db.commit()
    return manager


async def login(
    db: AsyncSession,
    username: str,
    password: str,
    peer: str,
    settings: Settings,
    dummy_hash: str,
    previous_token: str | None,
) -> tuple[Manager, ManagerSession, str]:
    try:
        # Shared peer limit is intentionally conservative behind the local Next proxy.
        await rate_limit(db, f"login:peer:{peer}", limit=30, seconds=900)
        await rate_limit(db, f"login:user:{username.strip().lower()}", limit=8, seconds=900)
    except HTTPException:
        audit(db, "auth.login", outcome="THROTTLED")
        await db.commit()
        raise
    manager = await db.scalar(select(Manager).where(Manager.username == username.strip().lower()))
    await db.commit()  # No DB transaction is held while doing expensive password verification.
    valid = await run_in_threadpool(
        verify_password, manager.password_hash if manager else dummy_hash, password
    )
    if not manager or not valid or not manager.is_active:
        audit(db, "auth.login", outcome="INVALID_CREDENTIALS")
        await db.commit()
        raise HTTPException(401, "Invalid username or password.")
    if previous_token:
        await db.execute(
            update(ManagerSession)
            .where(ManagerSession.token_hash == digest(previous_token))
            .values(revoked_at=now())
        )
    token = random_token()
    record = ManagerSession(
        manager_id=manager.id,
        token_hash=digest(token),
        expires_at=now() + timedelta(seconds=settings.session_lifetime_seconds),
    )
    db.add(record)
    audit(db, "auth.login", manager.id, actor_id=manager.id)
    await db.commit()
    return manager, record, token
