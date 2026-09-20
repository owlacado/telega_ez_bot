"""Hard-death probe, callable only against a disposable loopback TEST database."""

import asyncio
import json
import os
import sys
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

import hub.models  # noqa: F401
from hub.core.config import Settings
from hub.schedule_delivery import delivery
from hub.schedule_delivery.models import ScheduleDispatch
from tests.fakes import BOT_ID, BOT_USERNAME, FakeTelegram


async def main():
    config = json.loads(sys.stdin.read())
    url = make_url(config["url"])
    if url.host not in {"localhost", "127.0.0.1"} or url.database != "technician_hub_test":
        raise RuntimeError("Disposable TEST database required")
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=config["url"],
        telegram_mode="fake",
        telegram_expected_bot_id=BOT_ID,
        telegram_expected_bot_username=BOT_USERNAME,
        google_mode="fake",
        google_calendar_credential_encryption_key=config["key"],
        schedule_delivery_enabled=True,
        schedule_payload_encryption_key=config["key"],
    )
    engine = create_async_engine(config["url"], poolclass=NullPool, hide_parameters=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    window = config["window"]

    def die():
        os._exit(81)

    if window == "A":
        die()
    original_claim, original_prepare = delivery.claim, delivery.prepare
    original_finish, original_terminal = delivery.finish, delivery.terminal

    async def claim(*args):
        result = await original_claim(*args)
        if window == "B":
            die()
        return result

    async def prepare(*args, **kwargs):
        result = await original_prepare(*args, **kwargs)
        if window == "C":
            die()
        return result

    async def finish(*args, **kwargs):
        result = await original_finish(*args, **kwargs)
        if window in {"G", "I"}:
            die()
        return result

    def terminal(row, status, code, stamp):
        if window == "H" and status == "SENT":
            die()
        return original_terminal(row, status, code, stamp)

    @event.listens_for(Session, "before_commit")
    def before_commit(session):
        if window == "F" and any(
            isinstance(r, ScheduleDispatch) and r.status == "SENT" for r in session.dirty
        ):
            die()

    delivery.claim, delivery.prepare, delivery.finish, delivery.terminal = (
        claim,
        prepare,
        finish,
        terminal,
    )
    fake = FakeTelegram()
    fake.group(-771002, 771001, 771001)

    async def send(*args):
        # Independent invocation ledger survives os._exit; never stores message/token.
        with Path(config["ledger"]).open("a", encoding="ascii") as ledger:
            ledger.write("invoked\n")
            ledger.flush()
            os.fsync(ledger.fileno())
        if window in {"D", "E"}:
            die()
        return 123

    fake.send_schedule = send
    await delivery.deliver_one(factory, engine, fake, settings)
    raise AssertionError("Death injection was not reached")


if __name__ == "__main__":
    asyncio.run(main())
