"""Adversarial PostgreSQL ownership tests; all providers are synthetic."""

import asyncio
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text, update

from hub.core.config import Settings
from hub.telegram.models import TelegramProcessedUpdate, TelegramWorkerState
from hub.telegram.polling import LeaseLost, PollingLease
from hub.telegram.types import TrustedEvent
from hub.telegram.worker import Worker
from tests.conftest import TEST_URL
from tests.fakes import BOT_ID, BOT_USERNAME, FakeTelegram


@pytest.fixture
def settings():
    return Settings(
        database_url=TEST_URL,
        app_env="test",
        allow_fake_providers=True,
        telegram_mode="fake",
        telegram_expected_bot_id=BOT_ID,
        telegram_expected_bot_username=BOT_USERNAME,
    )


@pytest.fixture(autouse=True)
def fast_wait(monkeypatch):
    monkeypatch.setattr("hub.telegram.worker.WAIT_SECONDS", 0.03)


async def expired(engine):
    async with engine.begin() as db:
        await db.execute(
            update(TelegramWorkerState).values(
                poll_lease_until=func.clock_timestamp() - timedelta(seconds=1)
            )
        )


async def test_two_simultaneous_acquisitions_and_database_clock(engine):
    first, second = PollingLease(engine, BOT_ID), PollingLease(engine, BOT_ID)
    results = await asyncio.gather(first.acquire(), second.acquire())
    assert sorted(results) == [False, True]
    owner = first if results[0] else second
    try:
        async with engine.connect() as db:
            delta = await db.scalar(
                select(TelegramWorkerState.poll_lease_until - func.clock_timestamp())
            )
            assert 85 < delta.total_seconds() <= 90
        await owner.renew()
    finally:
        await owner.close(release=True)


async def test_standby_waits_without_provider_or_heartbeat_overwrite(engine, settings):
    lease = PollingLease(engine, BOT_ID)
    assert await lease.acquire()
    await lease.write(status="RUNNING", next_update_id=41)
    provider, stop = FakeTelegram(), asyncio.Event()
    task = asyncio.create_task(Worker(settings, engine, provider).run(stop, max_cycles=1))
    try:
        await asyncio.sleep(0.2)
        assert not task.done() and not provider.initialized and not provider.offsets
        async with engine.connect() as db:
            assert (
                await db.execute(
                    select(TelegramWorkerState.status, TelegramWorkerState.next_update_id)
                )
            ).one() == ("RUNNING", 41)
        await lease.close(release=True)
        await asyncio.wait_for(task, 4)
        assert provider.initialized and len(provider.offsets) == 1
    finally:
        stop.set()
        await lease.close(release=True)
        await asyncio.gather(task, return_exceptions=True)


async def test_crash_retains_expiry_then_successor_acquires(engine):
    old = PollingLease(engine, BOT_ID)
    assert await old.acquire()
    await old.close(release=False)  # Lost process/session; durable lease still exists.
    successor = PollingLease(engine, BOT_ID)
    assert not await successor.acquire()
    await expired(engine)
    assert await successor.acquire()
    try:
        with pytest.raises(LeaseLost):
            await old.renew()
    finally:
        await successor.close(release=True)


async def test_expired_owner_cannot_renew_or_advance_offset(engine):
    old = PollingLease(engine, BOT_ID)
    assert await old.acquire()
    await old.write(next_update_id=7)
    await expired(engine)
    try:
        with pytest.raises(LeaseLost):
            await old.renew()
        with pytest.raises(LeaseLost):
            await old.write(next_update_id=999)
        # Expiry cannot steal a still-live advisory session (paused old process).
        successor = PollingLease(engine, BOT_ID)
        assert not await successor.acquire()
        async with engine.connect() as db:
            assert await db.scalar(select(TelegramWorkerState.next_update_id)) == 7
    finally:
        await old.close(release=False)


async def test_old_token_cleanup_cannot_release_successor(engine):
    old = PollingLease(engine, BOT_ID)
    assert await old.acquire()
    new_owner = uuid4()
    async with engine.begin() as db:
        await db.execute(update(TelegramWorkerState).values(poll_owner=new_owner))
    with pytest.raises(LeaseLost):
        await old.renew()
    await old.close(release=True)
    async with engine.connect() as db:
        assert await db.scalar(select(TelegramWorkerState.poll_owner)) == new_owner


async def test_two_workers_handoff_durable_offset_and_dedupe(engine, settings):
    old, new = FakeTelegram(), FakeTelegram()
    stop, arrived, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    original = old.updates

    async def poll(offset):
        arrived.set()
        await release.wait()
        stop.set()
        return await original(offset)

    old.events = new.events = [TrustedEvent(40, "IGNORED"), TrustedEvent(41, "IGNORED")]
    old.updates = poll
    first = asyncio.create_task(Worker(settings, engine, old).run(stop))
    await asyncio.wait_for(arrived.wait(), 4)
    second = asyncio.create_task(Worker(settings, engine, new).run(asyncio.Event(), max_cycles=1))
    try:
        await asyncio.sleep(0.1)
        assert not new.initialized
        release.set()
        await asyncio.wait_for(asyncio.gather(first, second), 6)
        assert old.offsets == [None] and new.offsets == [42]
        async with engine.connect() as db:
            assert await db.scalar(select(TelegramWorkerState.next_update_id)) == 42
            assert await db.scalar(select(func.count()).select_from(TelegramProcessedUpdate)) == 2
    finally:
        release.set()
        first.cancel()
        second.cancel()
        await asyncio.gather(first, second, return_exceptions=True)


async def test_renewal_loss_cancels_poll_and_blocks_another_poll(engine, settings, monkeypatch):
    monkeypatch.setattr("hub.telegram.polling.RENEW_SECONDS", 0.03)
    provider, stop, entered, cancelled = (
        FakeTelegram(),
        asyncio.Event(),
        asyncio.Event(),
        asyncio.Event(),
    )

    async def poll(offset):
        provider.offsets.append(offset)
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
            stop.set()

    provider.updates = poll
    task = asyncio.create_task(Worker(settings, engine, provider).run(stop))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        await expired(engine)
        await asyncio.wait_for(cancelled.wait(), 3)
        await asyncio.wait_for(task, 3)
        assert provider.closed and provider.offsets == [None]
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_lost_db_session_cannot_reconnect_and_resume(engine):
    lease = PollingLease(engine, BOT_ID)
    assert await lease.acquire()
    async with engine.connect() as db:
        await db.execute(text("SELECT pg_terminate_backend(:pid)"), {"pid": lease.pid})
    try:
        for _ in range(2):
            with pytest.raises(LeaseLost):
                await lease.renew()
    finally:
        await lease.close(release=False)


async def test_healthy_long_poll_renews_lease_and_heartbeat(engine, settings, monkeypatch):
    monkeypatch.setattr("hub.telegram.polling.LEASE_SECONDS", 0.3)
    monkeypatch.setattr("hub.telegram.polling.RENEW_SECONDS", 0.03)
    provider, entered, release = FakeTelegram(), asyncio.Event(), asyncio.Event()

    async def poll(offset):
        entered.set()
        await release.wait()
        return []

    provider.updates = poll
    task = asyncio.create_task(
        Worker(settings, engine, provider).run(asyncio.Event(), max_cycles=1)
    )
    try:
        await asyncio.wait_for(entered.wait(), 3)
        async with engine.connect() as db:
            original = await db.scalar(select(TelegramWorkerState.poll_lease_until))
            assert (
                await db.scalar(
                    text(
                        "SELECT count(*) FROM pg_stat_activity WHERE "
                        "datname=current_database() AND state='idle in transaction'"
                    )
                )
                == 0
            )
        await asyncio.sleep(0.65)
        async with engine.connect() as db:
            current = await db.scalar(select(TelegramWorkerState.poll_lease_until))
            assert current > original
        contender = PollingLease(engine, BOT_ID)
        assert not await contender.acquire()
        release.set()
        await asyncio.wait_for(task, 3)
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_lease_loss_after_durable_processing_keeps_offset_replayable(
    engine, settings, monkeypatch
):
    import hub.telegram.worker as module

    provider, stop = FakeTelegram(), asyncio.Event()
    provider.events = [TrustedEvent(81, "IGNORED")]
    original = module.process_update

    async def lose_after_commit(*args, **kwargs):
        result = await original(*args, **kwargs)
        await expired(engine)
        stop.set()
        return result

    monkeypatch.setattr(module, "process_update", lose_after_commit)
    await Worker(settings, engine, provider).run(stop)
    async with engine.connect() as db:
        assert await db.scalar(select(TelegramWorkerState.next_update_id)) is None
        assert await db.scalar(select(TelegramProcessedUpdate.outcome)) == "IGNORED"
    monkeypatch.setattr(module, "process_update", original)
    await Worker(settings, engine, provider).run(asyncio.Event(), max_cycles=1)
    async with engine.connect() as db:
        assert await db.scalar(select(TelegramWorkerState.next_update_id)) == 82
        assert await db.scalar(select(func.count()).select_from(TelegramProcessedUpdate)) == 1
