"""Logging-only regressions; no database or provider network access."""

import asyncio
import json
import logging
import socket
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from hub.accounting_mirrors.worker import Worker as MirrorWorker
from hub.schedule_delivery.worker import Worker as ScheduleWorker
from hub.telegram import worker as telegram


@pytest.fixture(scope="session", autouse=True)
def migrate_database():
    # These tests exercise log emission and assert every durable write is still requested.
    pass


@pytest.fixture(autouse=True)
async def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Logging tests must not contact databases or providers")

    monkeypatch.setattr(socket.socket, "connect", blocked)
    try:
        yield
    finally:
        monkeypatch.undo()


def make_worker():
    return telegram.Worker(
        SimpleNamespace(telegram_mode="fake", telegram_expected_bot_id=10),
        MagicMock(),
        SimpleNamespace(close=AsyncMock()),
    )


def states(caplog):
    return [
        json.loads(record.message)["status"]
        for record in caplog.records
        if record.name == "hub.telegram.worker"
    ]


async def test_healthy_repetition_preserves_every_heartbeat_and_errors(caplog):
    caplog.set_level(logging.INFO)
    worker = make_worker()
    worker.lease = SimpleNamespace(write=AsyncMock())
    requested = ["RUNNING"] * 8 + ["RETRYING", "RETRYING", "RUNNING", "STOPPED", "ERROR"]
    for status in requested:
        await worker.state(status, "PROVIDER_UNAVAILABLE" if status == "RETRYING" else None)
    assert states(caplog) == ["RUNNING", "RETRYING", "RETRYING", "RUNNING", "STOPPED", "ERROR"]
    assert worker.lease.write.await_count == len(requested)
    for call, status in zip(worker.lease.write.await_args_list, requested, strict=True):
        assert call.kwargs["status"] == status
        assert str(call.kwargs["heartbeat_at"]) == "clock_timestamp()"
    assert all(record.levelno == logging.INFO for record in caplog.records)


async def test_failed_heartbeat_cannot_log_success_or_suppress_recovery(caplog):
    caplog.set_level(logging.INFO)
    worker = make_worker()
    worker.lease = SimpleNamespace(write=AsyncMock(side_effect=telegram.LeaseLost()))
    with pytest.raises(telegram.LeaseLost):
        await worker.state("RUNNING")
    assert states(caplog) == []
    worker.lease.write.side_effect = None
    await worker.state("RUNNING")
    assert states(caplog) == ["RUNNING"]


async def test_rolling_wait_takeover_loss_and_reacquisition_logs(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    worker = make_worker()
    outcomes = iter([False, False, False, True, False, False, True])
    leases = []

    class Lease:
        def __init__(self, *args):
            self.write = AsyncMock()
            self.close = AsyncMock()
            leases.append(self)

        async def acquire(self):
            return next(outcomes)

        async def maintain(self):
            await asyncio.Event().wait()

    runs = 0

    async def owned(stop, max_cycles):
        nonlocal runs
        runs += 1
        for _ in range(5):
            await worker.state("RUNNING")
        if runs == 1:
            raise telegram.LeaseLost()
        await worker.state("STOPPED")

    monkeypatch.setattr(telegram, "PollingLease", Lease)
    monkeypatch.setattr(telegram, "WAIT_SECONDS", 0.001)
    monkeypatch.setattr(worker, "owned_run", owned)
    await asyncio.wait_for(worker.run(asyncio.Event()), 2)
    assert states(caplog) == [
        "STARTING",
        "WAITING_FOR_LEASE",
        "LEASE_ACQUIRED",
        "RUNNING",
        "LEASE_LOST",
        "WAITING_FOR_LEASE",
        "LEASE_ACQUIRED",
        "RUNNING",
        "STOPPED",
    ]
    assert len(leases) == 7
    assert sum(lease.write.await_count for lease in leases) == 11
    assert worker.provider.close.await_count == 2
    assert next(r for r in caplog.records if "LEASE_LOST" in r.message).levelno == logging.WARNING


async def test_schedule_and_mirror_healthy_writes_already_silent(caplog):
    caplog.set_level(logging.INFO)
    db = AsyncMock()
    db.begin = MagicMock(return_value=AsyncMock())
    context = AsyncMock()
    context.__aenter__.return_value = db
    factory = MagicMock(return_value=context)
    schedule = ScheduleWorker(SimpleNamespace(), MagicMock(), MagicMock(), None, None)
    schedule.factory = factory
    mirror = MirrorWorker(factory, SimpleNamespace(), None)
    for _ in range(5):
        await schedule.state("RUNNING")
        await mirror.beat()
    assert db.execute.await_count == 10
    assert not caplog.records


async def test_standby_shutdown_logs_stopped_without_owner_write(monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    worker = make_worker()
    stop = asyncio.Event()
    lease = SimpleNamespace(acquire=AsyncMock(return_value=False))

    async def acquire():
        stop.set()
        return False

    lease.acquire.side_effect = acquire
    monkeypatch.setattr(telegram, "PollingLease", lambda *args: lease)
    await worker.run(stop)
    assert states(caplog) == ["STARTING", "WAITING_FOR_LEASE", "STOPPED"]
    assert worker.lease is None
    worker.provider.close.assert_not_awaited()
