"""Verify full image-stack restart persistence in a dedicated named-volume project."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "apps" / "api"
sys.path.insert(0, str(ROOT / "scripts"))

import verify_backup_restore as restore  # noqa: E402

COMPOSE = ROOT / "compose.restart-test.yaml"
DATABASE_URL = (
    "postgresql+asyncpg://hub:hub_restart_test_only@127.0.0.1:5444/technician_hub_test"
)


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
    compose("up", "-d", "--wait", "db")
    try:
        run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=API_ROOT, env=env)
        asyncio.run(restore.seed())
        before = asyncio.run(restore.fingerprint())
        compose("up", "-d", "--wait", "api", "web")
        compose("restart", "db", "api", "web")
        compose("up", "-d", "--wait", "db", "api", "web")
        after = asyncio.run(restore.fingerprint())
        if after != before:
            raise RuntimeError("Named-volume state changed across container restart.")
        asyncio.run(restore.verify_application())
        stable = asyncio.run(restore.fingerprint())
        # Restart only PostgreSQL while API/Web remain alive. pool_pre_ping must
        # discard the dead connection and recover without rebuilding either app.
        compose("restart", "db")
        compose("up", "-d", "--wait", "db")
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
                    "tables_verified": len(before),
                },
                sort_keys=True,
            )
        )
    finally:
        compose("down", "-v", "--remove-orphans")


if __name__ == "__main__":
    main()
