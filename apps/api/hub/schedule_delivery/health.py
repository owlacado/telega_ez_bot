"""Read-only operator health; API liveness does not imply worker liveness."""

import asyncio
import json
from datetime import timedelta

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import hub.models  # noqa: F401
from hub.core.config import Settings
from hub.schedule_delivery.delivery import clock
from hub.schedule_delivery.models import ScheduleWorkerState
from hub.telegram.models import TelegramWorkerState


def classify(status, heartbeat_at, stamp):
    if not heartbeat_at or stamp - heartbeat_at > timedelta(seconds=120):
        return "STALE"
    return status


async def inspect(factory, bot_id):
    async with factory() as db:
        await db.execute(text("SELECT 1"))
        stamp = await clock(db)
        schedule = (await db.scalars(select(ScheduleWorkerState))).all()
        telegram = await db.get(TelegramWorkerState, bot_id)
        states = [classify(s.status, s.heartbeat_at, stamp) for s in schedule]
        return {
            "database": "CONNECTED",
            "schedule_worker": "RUNNING" if "RUNNING" in states else "UNAVAILABLE",
            "schedule_running_instances": states.count("RUNNING"),
            "telegram_worker": classify(telegram.status, telegram.heartbeat_at, stamp)
            if telegram
            else "MISSING",
        }


async def main():
    engine = None
    try:
        settings = Settings()
        engine = create_async_engine(settings.database_url, hide_parameters=True)
        result = await inspect(async_sessionmaker(engine), settings.telegram_expected_bot_id)
        print(json.dumps(result, sort_keys=True))
        return 0 if result["schedule_worker"] == "RUNNING" else 1
    except Exception:
        print('{"error":"WORKER_HEALTH_UNAVAILABLE"}')
        return 1
    finally:
        if engine is not None:
            await engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
