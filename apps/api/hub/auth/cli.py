"""Interactive local manager provisioning. Never accepts a password argument."""

import argparse
import asyncio
import getpass
import sys

from argon2.exceptions import HashingError
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import hub.models  # noqa: F401
from hub.audit.service import audit
from hub.auth.models import Manager, ManagerSession
from hub.auth.security import now
from hub.auth.service import InvalidManagerPassword, InvalidManagerUsername, create_manager
from hub.core.config import Settings


async def run(command: str, username: str, password: str | None = None) -> None:
    engine = create_async_engine(Settings().database_url, hide_parameters=True)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            if command == "create-manager":
                assert password is not None
                await create_manager(db, username, password)
                print("Manager created. Sign in through the web application.")
            else:
                manager = await db.scalar(
                    select(Manager).where(Manager.username == username.strip().lower())
                )
                if not manager:
                    raise ManagerNotFound()
                await db.execute(
                    update(ManagerSession)
                    .where(ManagerSession.manager_id == manager.id)
                    .values(revoked_at=now())
                )
                audit(db, "auth.revoke_sessions", manager.id, actor_kind="LOCAL_CLI")
                await db.commit()
                print("Manager sessions revoked.")
    finally:
        await engine.dispose()


class ManagerNotFound(ValueError):
    pass


def safe_failure(error: Exception) -> str:
    """Allowlisted local-operator diagnostics. Never stringify arbitrary exceptions."""
    if isinstance(error, InvalidManagerUsername):
        return "[USERNAME_POLICY] Username must be 1-100 characters after trimming and lowercasing."
    if isinstance(error, InvalidManagerPassword):
        return (
            "[PASSWORD_POLICY] Password must be 14-128 characters; spaces count and are preserved."
        )
    if isinstance(error, ManagerNotFound):
        return "[MANAGER_NOT_FOUND] Manager not found."
    if isinstance(error, HashingError):
        return (
            "[HASHING_UNAVAILABLE] Password hashing is unavailable. "
            "Check the API image configuration."
        )
    if isinstance(error, ValidationError):
        return (
            "[CONFIGURATION_INVALID] Server configuration is invalid. "
            "Check the deployment settings."
        )
    if isinstance(error, IntegrityError):
        original = error.orig
        constraint = getattr(original, "constraint_name", None) or getattr(
            getattr(original, "__cause__", None), "constraint_name", None
        )
        if getattr(original, "sqlstate", None) == "23505" and constraint == "uq_managers_username":
            return "[USERNAME_EXISTS] Username already exists, whether active or inactive."
        return "[DATA_CONFLICT] Database integrity check failed. Check the current schema."
    if isinstance(error, SQLAlchemyError):
        if getattr(getattr(error, "orig", None), "sqlstate", None) in {"42P01", "42703"}:
            return "[SCHEMA_MISMATCH] Database schema is out of date. Apply the current migrations."
        return (
            "[DATABASE_UNAVAILABLE] Database operation failed. "
            "Check database connectivity and access."
        )
    if isinstance(error, (OSError, TimeoutError)):
        return (
            "[DATABASE_UNAVAILABLE] Database is unavailable. "
            "Check database connectivity and access."
        )
    return "[PROVISIONING_FAILED] Unable to complete manager provisioning. Report this error code."


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["create-manager", "revoke-sessions"])
    parser.add_argument("--username", required=True)
    args = parser.parse_args()
    password = None
    if args.command == "create-manager":
        if not sys.stdin.isatty():
            raise SystemExit("Use an interactive terminal for hidden password entry.")
        password = getpass.getpass("New manager password (14-128 characters): ")
        if password != getpass.getpass("Confirm password: "):
            raise SystemExit("Passwords do not match.")
    try:
        asyncio.run(run(args.command, args.username, password))
    except Exception as error:
        # Exceptions can contain passwords, hashes, SQL parameters and credential URLs.
        # Emit only a stable allowlisted category, not repr/str/traceback or locals.
        raise SystemExit(safe_failure(error)) from None


if __name__ == "__main__":
    main()
