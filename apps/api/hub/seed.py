"""Idempotent, opt-in development calendars. No technicians or provider IDs."""

import asyncio

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import create_async_engine

from hub.calendars.models import Calendar
from hub.core.config import Settings


async def seed() -> None:
    settings = Settings()
    if settings.app_env != "development":
        raise SystemExit("Seed is only available with APP_ENV=development.")
    engine = create_async_engine(settings.database_url)
    try:
        async with engine.begin() as connection:
            for name in ["DEMO - Atlanta", "DEMO - California", "DEMO - Field Team"]:
                await connection.execute(
                    insert(Calendar)
                    .values(name=name)
                    .on_conflict_do_nothing(index_elements=["name"])
                )
        print("Development calendars seeded. No external providers were contacted.")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
