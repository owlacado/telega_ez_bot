"""Render-only process entrypoint; never contacts a provider during preparation."""

import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

from hub.core.config import Settings

API_DIRECTORY = Path(__file__).resolve().parents[1]
WEB_SERVER = Path("/app/apps/web/server.js")
CADDYFILE = Path("/app/render.Caddyfile")
CHILD_GRACE_SECONDS = 45


def prepare_environment() -> Settings:
    """Translate Render's private Postgres URL and reject unsafe deployment modes."""
    raw = os.environ.get("RENDER_DATABASE_URL", "")
    if raw.startswith("postgresql://"):
        database_url = "postgresql+asyncpg://" + raw[len("postgresql://") :]
    elif raw.startswith("postgres://"):
        database_url = "postgresql+asyncpg://" + raw[len("postgres://") :]
    else:
        raise ValueError("Render internal PostgreSQL connection is missing or invalid.")
    database_host = urlsplit(database_url).hostname
    if os.environ.get("RENDER") == "true" and database_host in {
        None,
        "localhost",
        "127.0.0.1",
        "::1",
        "db",
        "test-db",
    }:
        raise ValueError("Render must use a private managed PostgreSQL host.")
    origin = os.environ.get("PUBLIC_APP_ORIGIN", "")
    parsed = urlsplit(origin)
    if not origin or parsed.path or parsed.query or parsed.fragment or not parsed.hostname:
        raise ValueError("PUBLIC_APP_ORIGIN must be one exact application origin.")
    if os.environ.get("APP_ENV") not in {"pilot", "production", "development", "test"}:
        raise ValueError("APP_ENV must be explicit.")
    if os.environ.get("RENDER") == "true" and os.environ["APP_ENV"] not in {"pilot", "production"}:
        raise ValueError("Render must use pilot or production mode.")
    if os.environ.get("ALLOW_FAKE_PROVIDERS", "false").lower() != "false" or any(
        os.environ.get(name, "disabled") == "fake" for name in ("GOOGLE_MODE", "TELEGRAM_MODE")
    ):
        raise ValueError("Fake providers are forbidden in the Render entrypoint.")
    commit = os.environ.get("RENDER_GIT_COMMIT") or os.environ.get("RELEASE_COMMIT", "")
    if os.environ.get("APP_ENV") not in {"development", "test"} and not re.fullmatch(
        r"[0-9a-f]{40}", commit
    ):
        raise ValueError("A 40-character release commit is required.")
    os.environ["DATABASE_URL"] = database_url
    os.environ["ALLOWED_ORIGINS"] = json.dumps([origin])
    os.environ["RELEASE_COMMIT"] = commit or "development"
    if os.environ.get("GOOGLE_MODE") == "real":
        callback = origin + "/api/calendar-connections/google/callback"
        if os.environ.get("GOOGLE_OAUTH_REDIRECT_URI", callback) != callback:
            raise ValueError("Google OAuth redirect must match the public application origin.")
        os.environ["GOOGLE_OAUTH_REDIRECT_URI"] = callback
    return Settings()


def child_specs(kind: str, settings: Settings) -> list[tuple[str, tuple[str, ...]]]:
    if kind == "web":
        return [
            (
                "api",
                (
                    "uvicorn",
                    "hub.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "8000",
                    "--no-proxy-headers",
                ),
            ),
            ("next", ("node", str(WEB_SERVER))),
            ("router", ("caddy", "run", "--config", str(CADDYFILE), "--adapter", "caddyfile")),
        ]
    if kind == "worker":
        children = []
        if settings.telegram_mode == "real":
            children.append(("telegram", (sys.executable, "-m", "hub.telegram.worker")))
        if settings.schedule_delivery_enabled:
            children.append(("schedule", (sys.executable, "-m", "hub.schedule_delivery.worker")))
        if settings.google_mode == "real":
            children.append(("mirror", (sys.executable, "-m", "hub.accounting_mirrors.worker")))
        return children
    raise ValueError("Unknown Render process group.")


def supervise(
    specs: list[tuple[str, tuple[str, ...]]], *, grace_seconds: float = CHILD_GRACE_SECONDS
) -> int:
    """One child exit fails the group; SIGTERM reaches every enabled child."""
    processes: list[tuple[str, subprocess.Popen]] = []
    stopping = False

    def request_stop(_signal, _frame):
        nonlocal stopping
        stopping = True

    previous = {sig: signal.signal(sig, request_stop) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        for name, command in specs:
            child_env = os.environ.copy()
            if name == "next":
                child_env["PORT"] = "3000"
                child_env["HOSTNAME"] = "127.0.0.1"
            print(f"Render process starting: {name}", flush=True)
            processes.append(
                (name, subprocess.Popen(command, env=child_env, start_new_session=True))
            )
        while not stopping:
            for name, process in processes:
                result = process.poll()
                if result is not None:
                    print(f"Render process stopped unexpectedly: {name} ({result})", flush=True)
                    return 1
            time.sleep(0.2)
        return 0
    finally:
        for _, process in processes:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
        deadline = time.monotonic() + grace_seconds
        for _, process in processes:
            try:
                process.wait(timeout=max(0, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command not in {
        "migrate",
        "preflight",
        "queues",
        "create-manager",
        "revoke-sessions",
        "web",
        "worker",
    }:
        raise SystemExit("Expected a Render deployment or operator command.")
    if command in {"create-manager", "revoke-sessions"}:
        if len(sys.argv) != 4 or sys.argv[2] != "--username":
            raise SystemExit("Expected --username NAME.")
    elif len(sys.argv) != 2:
        raise SystemExit("Unexpected arguments.")
    try:
        settings = prepare_environment()
    except Exception:
        raise SystemExit(
            "Render configuration is missing or unsafe; check variable names."
        ) from None
    if command == "migrate":
        raise SystemExit(subprocess.call(("alembic", "upgrade", "head"), cwd=API_DIRECTORY))
    if command == "preflight":
        raise SystemExit(subprocess.call((sys.executable, "-m", "hub.ops.cli", "preflight")))
    if command == "queues":
        raise SystemExit(
            subprocess.call((sys.executable, "-m", "hub.ops.cli", "queues", "--require-pass"))
        )
    if command in {"create-manager", "revoke-sessions"}:
        raise SystemExit(
            subprocess.call(
                (sys.executable, "-m", "hub.auth.cli", command, "--username", sys.argv[3])
            )
        )
    raise SystemExit(supervise(child_specs(command, settings)))


if __name__ == "__main__":
    main()
