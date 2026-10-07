"""Two OS processes share one PostgreSQL database and one loopback fake provider."""

import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from sqlalchemy import select

from hub import render_runtime
from hub.telegram.models import TelegramWorkerState
from hub.telegram.polling import PollingLease
from tests.conftest import TEST_URL
from tests.fakes import BOT_ID, BOT_USERNAME

ROOT = Path(__file__).resolve().parents[1]


def environment():
    return {
        **os.environ,
        "DATABASE_URL": TEST_URL,
        "APP_ENV": "test",
        "ALLOW_FAKE_PROVIDERS": "true",
        "TELEGRAM_MODE": "fake",
        "GOOGLE_MODE": "disabled",
        "TELEGRAM_EXPECTED_BOT_ID": str(BOT_ID),
        "TELEGRAM_EXPECTED_BOT_USERNAME": BOT_USERNAME,
    }


async def until(predicate, timeout=8):
    async with asyncio.timeout(timeout):
        while not await predicate():
            await asyncio.sleep(0.025)


@pytest.mark.parametrize("crash", [False, True])
async def test_two_process_render_style_rollout(engine, tmp_path, crash):
    active, maximum, offsets = 0, 0, []

    async def fake(reader, writer):
        nonlocal active, maximum
        try:
            headers = await reader.readuntil(b"\r\n\r\n")
            length = next(
                int(line.split(b":", 1)[1])
                for line in headers.split(b"\r\n")
                if line.lower().startswith(b"content-length:")
            )
            payload = json.loads(await reader.readexactly(length))
            offsets.append(payload["offset"])
            active += 1
            maximum = max(maximum, active)
            try:
                await asyncio.sleep(0.12)
                values = [41] if payload["offset"] is None or payload["offset"] <= 41 else []
                data = json.dumps(values).encode()
                writer.write(
                    b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                    b"Connection: close\r\nContent-Length: "
                    + str(len(data)).encode()
                    + b"\r\n\r\n"
                    + data
                )
                await writer.drain()
            finally:
                active -= 1
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()

    server = await asyncio.start_server(fake, "127.0.0.1", 0)
    url = f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}/updates"
    processes = []

    async def spawn(name):
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "tests.polling_worker_process",
            url,
            str(tmp_path / name),
            cwd=ROOT,
            env=environment(),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        processes.append(process)
        return process

    async def owner():
        async with engine.connect() as db:
            return await db.scalar(
                select(TelegramWorkerState.poll_owner).where(TelegramWorkerState.bot_id == BOT_ID)
            )

    try:
        first = await spawn("stop-old")

        async def ready():
            return len(offsets) >= 2

        await until(ready)
        old_owner = await owner()
        second = await spawn("stop-new")
        await asyncio.sleep(0.6)
        assert first.returncode is None and second.returncode is None
        assert await owner() == old_owner
        if crash:
            first.kill()
            await first.wait()
            assert await owner() == old_owner  # No cleanup: the durable expiry remains.
        else:
            (tmp_path / "stop-old").touch()
            assert await asyncio.wait_for(first.wait(), 6) == 0

        async def took_over():
            current = await owner()
            return current is not None and current != old_owner

        await until(took_over)
        before = len(offsets)

        async def polled():
            return len(offsets) > before

        await until(polled)
        assert second.returncode is None and maximum == 1
        assert all(value == 42 for value in offsets[1:])
        (tmp_path / "stop-new").touch()
        assert await asyncio.wait_for(second.wait(), 6) == 0
        assert await owner() is None
        async with engine.connect() as db:
            assert await db.scalar(select(TelegramWorkerState.next_update_id)) == 42
    finally:
        for process in processes:
            if process.returncode is None:
                process.kill()
            await process.wait()
        server.close()
        await server.wait_closed()


async def test_render_supervisor_keeps_waiting_child_alive(engine, tmp_path, monkeypatch, capsys):
    # Real new worker process waits behind a live old-version advisory/lease owner.
    # Only signal dispatch is adapted for the Windows test host; supervisor is unchanged.
    lease = PollingLease(engine, BOT_ID)
    assert await lease.acquire()
    handlers, children = {}, []
    real_spawn, real_sleep = subprocess.Popen, time.sleep

    def spawn(command, **kwargs):
        child = real_spawn(
            command,
            cwd=ROOT,
            env=environment(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        children.append(child)
        return child

    def signals(sig, handler):
        previous = handlers.get(sig, signal.SIG_DFL)
        handlers[sig] = handler
        return previous

    observations = 0

    def tick(seconds):
        nonlocal observations
        real_sleep(seconds)
        observations += 1
        assert all(child.poll() is None for child in children)
        if observations >= 8:
            handlers[signal.SIGTERM](signal.SIGTERM, None)

    monkeypatch.setattr(render_runtime.subprocess, "Popen", spawn)
    monkeypatch.setattr(render_runtime.signal, "signal", signals)
    monkeypatch.setattr(render_runtime.time, "sleep", tick)
    monkeypatch.setattr(
        render_runtime.os,
        "killpg",
        lambda pid, sig: next(child for child in children if child.pid == pid).terminate(),
        raising=False,
    )
    try:
        command = (
            sys.executable,
            "-m",
            "tests.polling_worker_process",
            "http://127.0.0.1:1/never-called",
            str(tmp_path / "stop"),
        )
        assert render_runtime.supervise([("telegram", command)]) == 0
        assert "stopped unexpectedly" not in capsys.readouterr().out
        assert observations == 8
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
            child.wait()
        await lease.close(release=True)
