"""Safe operator commands. No command contacts Google or Telegram."""

import argparse
import asyncio
import json
from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import hub.models  # noqa: F401
from hub.auth.models import Manager
from hub.core.config import Settings
from hub.ops.service import EXPECTED_ALEMBIC_HEAD, cleanup_expired, operations_health
from hub.technicians.models import Technician

FINGERPRINT_TABLES = (
    "accounting_mirror_refreshes",
    "accounting_mirror_targets",
    "audit_events",
    "calendar_assignments",
    "calendar_connections",
    "calendars",
    "expense_revisions",
    "google_oauth_attempts",
    "manager_sessions",
    "managers",
    "schedule_auto_decisions",
    "schedule_delivery_settings",
    "schedule_dispatches",
    "technician_expenses",
    "technician_form_sessions",
    "technicians",
    "telegram_bindings",
    "telegram_invitations",
    "telegram_outbox",
    "telegram_processed_updates",
    "work_report_revisions",
    "work_reports",
)


def _settings() -> Settings | None:
    try:
        return Settings()
    except Exception:
        print("BLOCK configuration: invalid or unsafe configuration; inspect environment names.")
        return None


async def preflight(settings: Settings) -> int:
    checks: list[tuple[str, str, str]] = [("PASS", "configuration", "static validation passed")]
    production = settings.app_env not in {"development", "test"}
    commit = settings.release_commit.lower()
    if production and (
        commit in {"", "unknown", "development"}
        or len(commit) != 40
        or any(char not in "0123456789abcdef" for char in commit)
    ):
        checks.append(("BLOCK", "release", "production release commit is missing or invalid"))
    else:
        checks.append(("PASS", "release", f"version {settings.app_version} identified"))
    if settings.telegram_mode == "real":
        token_file = Path(settings.telegram_token_file) if settings.telegram_token_file else None
        token_available = bool(settings.telegram_bot_token) or bool(
            token_file and token_file.is_file()
        )
        checks.append(
            (
                "PASS" if token_available else "BLOCK",
                "telegram",
                "real provider credential source configured"
                if token_available
                else "real provider requires a readable token source",
            )
        )
    else:
        checks.append(("WARN", "telegram", "provider is disabled"))
    if settings.google_mode == "real":
        checks.append(("PASS", "google", "OAuth and credential encryption configured"))
    else:
        checks.append(("WARN", "google", "provider is disabled"))
    engine = create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        hide_parameters=True,
        connect_args={"timeout": 5},
    )
    try:
        async with async_sessionmaker(engine)() as db:
            await db.execute(text("SELECT 1"))
            checks.append(("PASS", "database", "reachable"))
            head = await db.scalar(text("SELECT version_num FROM alembic_version LIMIT 1"))
            checks.append(
                (
                    "PASS" if head == EXPECTED_ALEMBIC_HEAD else "BLOCK",
                    "migration",
                    "schema head matches release"
                    if head == EXPECTED_ALEMBIC_HEAD
                    else "schema head does not match release",
                )
            )
            managers = int(
                await db.scalar(
                    select(func.count()).select_from(Manager).where(Manager.is_active.is_(True))
                )
                or 0
            )
            checks.append(
                (
                    "PASS" if managers else "BLOCK",
                    "manager",
                    f"{managers} active manager account(s)"
                    if managers
                    else "no active manager account",
                )
            )
            missing_zones = int(
                await db.scalar(
                    select(func.count())
                    .select_from(Technician)
                    .where(
                        Technician.status == "ACTIVE",
                        Technician.accounting_timezone.is_(None),
                    )
                )
                or 0
            )
            checks.append(
                (
                    "WARN" if missing_zones else "PASS",
                    "technicians",
                    f"{missing_zones} active technician(s) need accounting timezone"
                    if missing_zones
                    else "active technician timezone configuration is complete",
                )
            )
    except Exception:
        checks.append(("BLOCK", "database", "unreachable or schema unavailable"))
    finally:
        await engine.dispose()
    for level, name, message in checks:
        print(f"{level} {name}: {message}")
    return 2 if any(level == "BLOCK" for level, _, _ in checks) else 0


async def fingerprint(settings: Settings) -> int:
    engine = create_async_engine(settings.database_url, hide_parameters=True)
    result = {}
    try:
        async with engine.connect() as connection:
            for table in FINGERPRINT_TABLES:
                count, digest = (
                    await connection.execute(
                        text(
                            "SELECT count(*), md5(coalesce(string_agg(to_jsonb(t)::text, '' "
                            f"ORDER BY to_jsonb(t)::text), '')) FROM {table} t"
                        )
                    )
                ).one()
                result[table] = {"count": count, "opaque_digest": digest}
            size = await connection.scalar(
                text("SELECT pg_size_pretty(pg_database_size(current_database()))")
            )
            result["database"] = {"approximate_size": size}
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception:
        print('{"error":"FINGERPRINT_UNAVAILABLE"}')
        return 2
    finally:
        await engine.dispose()


async def queues(settings: Settings, *, require_pass: bool = False) -> int:
    engine = create_async_engine(settings.database_url, hide_parameters=True)
    try:
        async with async_sessionmaker(engine)() as db:
            health = await operations_health(db, settings)
        print(health.model_dump_json())
        return 2 if require_pass and health.status != "PASS" else 0
    except Exception:
        print('{"error":"OPERATIONS_HEALTH_UNAVAILABLE"}')
        return 2
    finally:
        await engine.dispose()


async def cleanup(settings: Settings, *, apply: bool, batch_size: int) -> int:
    engine = create_async_engine(settings.database_url, hide_parameters=True)
    try:
        async with async_sessionmaker(engine)() as db:
            async with db.begin():
                result = await cleanup_expired(
                    db, apply=apply, batch_size=batch_size, settings=settings
                )
                if not apply:
                    await db.rollback()
        print(result.model_dump_json())
        return 0
    except Exception:
        print('{"error":"CLEANUP_UNAVAILABLE"}')
        return 2
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m hub.ops.cli")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("preflight")
    subcommands.add_parser("fingerprint")
    queues_parser = subcommands.add_parser("queues")
    queues_parser.add_argument(
        "--require-pass",
        action="store_true",
        help="exit nonzero when aggregate operations health is WARN or BLOCK",
    )
    cleanup_parser = subcommands.add_parser("cleanup-expired-data")
    cleanup_parser.add_argument("--apply", action="store_true")
    cleanup_parser.add_argument("--batch-size", type=int, default=100)
    args = parser.parse_args()
    settings = _settings()
    if settings is None:
        raise SystemExit(2)
    if args.command == "preflight":
        code = asyncio.run(preflight(settings))
    elif args.command == "fingerprint":
        code = asyncio.run(fingerprint(settings))
    elif args.command == "queues":
        code = asyncio.run(queues(settings, require_pass=args.require_pass))
    else:
        code = asyncio.run(cleanup(settings, apply=args.apply, batch_size=args.batch_size))
    raise SystemExit(code)


if __name__ == "__main__":
    main()
