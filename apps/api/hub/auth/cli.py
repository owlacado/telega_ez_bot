"""Interactive local manager provisioning. Never accepts a password argument."""

import argparse
import asyncio
import getpass
import sys

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import hub.models  # noqa: F401
from hub.audit.service import audit
from hub.auth.models import Manager, ManagerSession
from hub.auth.security import now
from hub.auth.service import create_manager
from hub.core.config import Settings


async def run(command: str, username: str, password: str | None = None) -> None:
    engine = create_async_engine(Settings().database_url)
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
                    raise ValueError("Manager not found.")
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
    except Exception:
        # A database exception may contain a password hash; do not print it.
        raise SystemExit(
            "Operation failed. Check username, password policy, and database availability."
        ) from None


if __name__ == "__main__":
    main()
