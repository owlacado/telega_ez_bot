from collections.abc import AsyncIterator
from datetime import datetime

from fastapi import HTTPException, Request
from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


class Timestamps:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


async def session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.session_factory() as db:
        try:
            yield db
        except (OSError, TimeoutError) as exc:
            # Drivers can raise raw socket failures before SQLAlchemy wraps them.
            raise HTTPException(503, "The database is unavailable. Try again shortly.") from exc
