"""Verify full image-stack restart persistence in a dedicated named-volume project."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "apps" / "api"
sys.path.insert(0, str(ROOT / "scripts"))

import verify_backup_restore as restore  # noqa: E402

COMPOSE = ROOT / "compose.restart-test.yaml"
DATABASE_URL = "postgresql+asyncpg://hub:hub_restart_test_only@127.0.0.1:5444/technician_hub_test"
WORKERS = ("telegram-test-worker", "schedule-test-worker", "mirror-test-worker")


async def wait_for_workers() -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(DATABASE_URL, hide_parameters=True)
    try:
        for _ in range(60):
            try:
                async with engine.connect() as connection:
                    values = (
                        await connection.execute(
                            text(
                                "SELECT "
                                "EXISTS (SELECT 1 FROM telegram_worker_states "
                                "WHERE status = 'RUNNING' "
                                "AND heartbeat_at >= clock_timestamp() - interval '120 seconds'), "
                                "EXISTS (SELECT 1 FROM schedule_worker_states "
                                "WHERE status = 'RUNNING' "
                                "AND heartbeat_at >= clock_timestamp() - interval '120 seconds'), "
                                "EXISTS (SELECT 1 FROM accounting_mirror_worker_states "
                                "WHERE status = 'RUNNING' AND heartbeat_at >= "
                                "clock_timestamp() - interval '120 seconds')"
                            )
                        )
                    ).one()
                if all(values):
                    return
            except Exception:
                pass
            await asyncio.sleep(1)
    finally:
        await engine.dispose()
    raise RuntimeError("Isolated workers did not publish current RUNNING heartbeats.")


def run(command: list[str], *, cwd=ROOT, env=None) -> None:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(f"Command failed safely: {Path(command[0]).name}")


def compose(*arguments: str) -> None:
    run(["docker", "compose", "-f", str(COMPOSE), *arguments])


def main() -> None:
    if COMPOSE.name != "compose.restart-test.yaml" or "hub_restart_test_only" not in DATABASE_URL:
        raise SystemExit("Refusing to run outside the dedicated restart stack.")
    restore.DATABASE_URL = DATABASE_URL
    env = {**os.environ, "DATABASE_URL": DATABASE_URL}
    compose("up", "-d", "--wait", "test-db")
    try:
        run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=API_ROOT, env=env)
        asyncio.run(restore.seed())
        seeded = asyncio.run(restore.fingerprint())
        compose("up", "-d", "--wait", "api", "web", *WORKERS)
        asyncio.run(wait_for_workers())
        time.sleep(6)
        before = asyncio.run(restore.fingerprint())
        for table in ("telegram_outbox", "schedule_dispatches", "accounting_mirror_refreshes"):
            if before[table]["count"] != seeded[table]["count"]:
                raise RuntimeError("A durable queue row disappeared while workers started.")
        compose("restart", "test-db", "api", "web", *WORKERS)
        compose("up", "-d", "--wait", "test-db", "api", "web", *WORKERS)
        asyncio.run(wait_for_workers())
        time.sleep(6)
        after = asyncio.run(restore.fingerprint())
        if after != before:
            raise RuntimeError("Named-volume state changed across container restart.")
        asyncio.run(restore.verify_application())
        stable = asyncio.run(restore.fingerprint())
        # Stop PostgreSQL while API/Web/workers remain alive. Health must fail
        # closed, then pool_pre_ping and worker loops must recover in place.
        compose("stop", "test-db")
        try:
            urllib.request.urlopen("http://127.0.0.1:8003/api/health", timeout=10)
        except urllib.error.HTTPError as error:
            if error.code != 503:
                raise RuntimeError("API returned an unexpected database-outage status.") from None
        except urllib.error.URLError:
            pass
        else:
            raise RuntimeError("API health stayed healthy while PostgreSQL was stopped.")
        compose("start", "test-db")
        compose("up", "-d", "--wait", "test-db")
        asyncio.run(wait_for_workers())
        recovered = asyncio.run(restore.fingerprint())
        if recovered != stable:
            raise RuntimeError("Named-volume state changed across PostgreSQL restart.")
        with urllib.request.urlopen("http://127.0.0.1:8003/api/health", timeout=10) as response:
            health = json.load(response)
        with urllib.request.urlopen("http://127.0.0.1:3003/login", timeout=10) as response:
            if response.status != 200:
                raise RuntimeError("Web login page did not recover after restart.")
        if health.get("database") != "connected":
            raise RuntimeError("API did not recover its database connection after restart.")
        print(
            json.dumps(
                {
                    "containers": "RESTARTED",
                    "database_fingerprint": "MATCH",
                    "manager_login": "PASS",
                    "accounting": "PASS",
                    "durable_queues": "PASS",
                    "api_recovery": "PASS",
                    "postgres_client_recovery": "PASS",
                    "web_recovery": "PASS",
                    "worker_heartbeats": "PASS",
                    "db_outage_health": "PASS",
                    "tables_verified": len(before),
                },
                sort_keys=True,
            )
        )
    finally:
        compose("down", "-v", "--remove-orphans")


if __name__ == "__main__":
    main()
