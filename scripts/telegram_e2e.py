"""Private stdin-only fake transport harness. No web route and no real adapter."""

import asyncio
import json
import os
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/api"))
import hub.models  # noqa: E402,F401
from hub.auth.models import Manager, RateBucket  # noqa: E402
from hub.auth.service import create_manager  # noqa: E402
from hub.core.config import Settings  # noqa: E402
from hub.telegram.delivery import deliver_one  # noqa: E402
from hub.telegram.transport import parse_update  # noqa: E402
from hub.telegram.updates import process_update  # noqa: E402
from hub.telegram.worker import Worker  # noqa: E402
from sqlalchemy import delete  # noqa: E402
from tests.fakes import BOT_ID, BOT_USERNAME, FakeTelegram  # noqa: E402


async def main():
    url = os.environ.get(
        "TEST_DATABASE_URL",
        "postgresql+asyncpg://hub:hub_test_only@127.0.0.1:5437/technician_hub_test",
    )
    parsed = make_url(url)
    if parsed.database != "technician_hub_test" or parsed.host not in {"127.0.0.1", "localhost"}:
        raise RuntimeError("Isolated local test database required")
    payload = json.load(sys.stdin)
    engine = create_async_engine(url, hide_parameters=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    provider = FakeTelegram()
    try:
        action = payload["action"]
        if action == "bootstrap":
            async with factory() as db:
                # Each serial browser test gets isolated rate-limit state. The CLI
                # guard above permits only the disposable loopback test database;
                # application login limits and production routes are unchanged.
                await db.execute(delete(RateBucket))
                await db.commit()
                await create_manager(db, payload["username"], payload["password"])
            settings = Settings(
                database_url=url,
                app_env="test",
                telegram_mode="fake",
                telegram_expected_bot_id=BOT_ID,
                telegram_expected_bot_username=BOT_USERNAME,
            )
            await Worker(settings, engine, provider).startup()
        elif action == "google_reset":
            from hub.calendars.models import Calendar, CalendarAssignment
            from hub.google_calendar.models import CalendarConnection, GoogleOAuthAttempt
            from sqlalchemy import select

            async with factory() as db, db.begin():
                google_ids = select(Calendar.id).where(Calendar.source == "GOOGLE")
                await db.execute(
                    delete(CalendarAssignment).where(CalendarAssignment.calendar_id.in_(google_ids))
                )
                await db.execute(delete(Calendar).where(Calendar.source == "GOOGLE"))
                await db.execute(delete(GoogleOAuthAttempt))
                await db.execute(delete(CalendarConnection))
        elif action == "cleanup":
            async with factory() as db, db.begin():
                await db.execute(delete(Manager).where(Manager.username == payload["username"]))
        elif action == "claim":
            link = urlparse(payload["link"])
            query = parse_qs(link.query)
            group = "startgroup" in query
            token = query["startgroup" if group else "start"][0]
            user = payload["user_id"]
            chat = payload["chat_id"] if group else user
            provider.group(chat, user, user)
            event = parse_update(
                {
                    "update_id": payload["update_id"],
                    "message": {
                        "message_id": 1,
                        "from": {"id": user, "is_bot": False, "first_name": "E2E Telegram"},
                        "chat": {
                            "id": chat,
                            "type": "supergroup" if group else "private",
                            "title": "E2E work group",
                        },
                        "text": f"/start@{BOT_USERNAME} {token}",
                    },
                },
                BOT_USERNAME,
            )
            result = await process_update(factory, provider, event, BOT_ID)
            if result.outcome != "CONNECTED":
                raise RuntimeError("Fake claim did not connect")
        elif action == "deliver":
            provider.group(payload["chat_id"], payload["user_id"], payload["user_id"])
            for _ in range(20):
                if not await deliver_one(factory, engine, provider, BOT_ID):
                    break
        else:
            raise RuntimeError("Unknown harness action")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception:
        raise SystemExit("Isolated Telegram harness failed. No live provider was called.") from None
