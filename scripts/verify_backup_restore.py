"""Destructive restore drill against only the dedicated temporary PostgreSQL stack."""

# ruff: noqa: E402

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "apps" / "api"
sys.path.insert(0, str(API_ROOT))

import hub.models  # noqa: F401
from httpx import ASGITransport, AsyncClient
from hub.accounting_mirrors.models import (
    AccountingMirrorRefresh,
    AccountingMirrorTarget,
)
from hub.auth.service import create_manager
from hub.calendars.models import Calendar, CalendarAssignment
from hub.core.config import Settings
from hub.core.secrets import SecretCipher
from hub.expenses.models import ExpenseRevision, TechnicianExpense
from hub.google_calendar.models import CalendarConnection
from hub.google_calendar.types import EVENT_SCOPE, SHEETS_SCOPE
from hub.integrations.models import TelegramBinding
from hub.main import create_app
from hub.ops.cli import FINGERPRINT_TABLES
from hub.technicians.models import Technician
from hub.telegram.models import TelegramOutbox
from hub.work_reports.models import WorkReport, WorkReportRevision
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

DATABASE_NAME = "technician_hub_restore_test"
DATABASE_URL = (
    "postgresql+asyncpg://hub:hub_restore_test_only@127.0.0.1:5439/"
    f"{DATABASE_NAME}"
)
COMPOSE = ROOT / "compose.backup-test.yaml"
PASSWORD = "synthetic-restore-password"
KEY = "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="
TECHNICIAN_ID = UUID("10101010-1010-4010-8010-101010101010")
WEEK = date(2026, 9, 14)


def run(command: list[str], *, stdout=None, env=None, cwd=ROOT) -> None:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        stdout=stdout if stdout is not None else subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(f"Command failed safely: {Path(command[0]).name}")


def compose(*arguments: str, stdout=None) -> None:
    run(["docker", "compose", "-f", str(COMPOSE), *arguments], stdout=stdout)


async def seed() -> None:
    engine = create_async_engine(DATABASE_URL, hide_parameters=True)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as db:
            manager = await create_manager(db, "restore-manager", PASSWORD)
        async with factory() as db, db.begin():
            connection = CalendarConnection(
                account_key="synthetic-account-key",
                account_label="Synthetic restore account",
                status="CONNECTED",
                generation=1,
                is_current=True,
                encrypted_refresh_token=SecretCipher(KEY).encrypt("synthetic-refresh-token"),
                granted_scopes=[EVENT_SCOPE, SHEETS_SCOPE],
                connected_at=datetime.now(UTC),
                created_by_user_id=manager.id,
            )
            technician = Technician(
                id=TECHNICIAN_ID,
                first_name="Restore",
                last_name="Synthetic",
                accounting_timezone="America/Los_Angeles",
            )
            db.add_all([connection, technician])
            await db.flush()
            calendar = Calendar(
                name="Synthetic restore calendar",
                source="GOOGLE",
                provider_connection_id=connection.id,
                provider_calendar_id="synthetic-calendar-id",
                availability="AVAILABLE",
                timezone="America/Los_Angeles",
                access_role="reader",
            )
            db.add(calendar)
            await db.flush()
            db.add_all(
                [
                    CalendarAssignment(
                        technician_id=technician.id,
                        calendar_id=calendar.id,
                        calendar_name=calendar.name,
                    ),
                    TelegramBinding(
                        technician_id=technician.id,
                        telegram_user_id=700000001,
                        telegram_group_chat_id=-700000002,
                        bot_id=700000003,
                        private_status="CONNECTED",
                        group_status="CONNECTED",
                        private_generation=1,
                        group_generation=1,
                        group_private_generation=1,
                        private_availability="AVAILABLE",
                        group_availability="AVAILABLE",
                    ),
                ]
            )
            report = WorkReport(
                technician_id=technician.id,
                calendar_id=calendar.id,
                occurrence_key="1" * 64,
                current_revision_number=1,
            )
            expense = TechnicianExpense(
                technician_id=technician.id, current_revision_number=1
            )
            db.add_all([report, expense])
            await db.flush()
            db.add_all(
                [
                    WorkReportRevision(
                        report_id=report.id,
                        revision_number=1,
                        technician_name="Restore Synthetic",
                        operational_date=WEEK,
                        start_time="09:00",
                        end_time="10:00",
                        sequence=1,
                        title="Synthetic restore job",
                        location="Synthetic location",
                        provider_event_id="synthetic-event",
                        amount_closed=Decimal("125.50"),
                        payment_method="CASH",
                        closed_by="MYSELF",
                        comments="Synthetic restore evidence",
                        yearly_maintenance_plan_provided=True,
                        google_reviews=1,
                        groupon_reviews=0,
                        facebook_reviews=0,
                        submitted_at=datetime(2026, 9, 14, 19, tzinfo=UTC),
                    ),
                    ExpenseRevision(
                        expense_id=expense.id,
                        revision_number=1,
                        technician_name="Restore Synthetic",
                        expense_date=WEEK,
                        accounting_timezone="America/Los_Angeles",
                        expense_type="Synthetic supplies",
                        amount=Decimal("25.25"),
                        note="Synthetic restore evidence",
                        submitted_at=datetime(2026, 9, 14, 20, tzinfo=UTC),
                    ),
                ]
            )
            target = AccountingMirrorTarget(
                kind="INDIVIDUAL",
                technician_id=technician.id,
                google_connection_id=connection.id,
                spreadsheet_id="synthetic-spreadsheet-id",
            )
            db.add(target)
            await db.flush()
            db.add_all(
                [
                    AccountingMirrorRefresh(target_id=target.id, week_start=WEEK),
                    TelegramOutbox(
                        technician_id=technician.id,
                        bot_id=700000003,
                        destination="PRIVATE_TELEGRAM",
                        kind="TEST",
                        generation=1,
                        private_generation=1,
                        requested_by=manager.id,
                        state="QUEUED",
                    ),
                ]
            )
    finally:
        await engine.dispose()


async def fingerprint() -> dict[str, dict[str, int | str]]:
    engine = create_async_engine(DATABASE_URL, hide_parameters=True)
    result: dict[str, dict[str, int | str]] = {}
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
        return result
    finally:
        await engine.dispose()


async def verify_application() -> None:
    settings = Settings(
        _env_file=None,
        database_url=DATABASE_URL,
        app_env="test",
        allowed_origins=["http://127.0.0.1:3000"],
        google_calendar_credential_encryption_key=KEY,
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://127.0.0.1:3000",
            headers={"Origin": "http://127.0.0.1:3000", "X-Hub-Request": "1"},
        ) as client:
            login = await client.post(
                "/api/auth/login",
                json={"username": "restore-manager", "password": PASSWORD},
            )
            if login.status_code != 200:
                raise RuntimeError("Restored manager login failed.")
            accounting = await client.get(
                f"/api/technicians/{TECHNICIAN_ID}/accounting/weekly",
                params={"week_start": WEEK.isoformat()},
            )
            if accounting.status_code != 200:
                raise RuntimeError("Restored accounting read failed.")
            body = accounting.json()
            if body["totals"]["gross_total"] != "125.50":
                raise RuntimeError("Restored Work Report accounting differs.")
            if body["totals"]["expense_total"] != "25.25":
                raise RuntimeError("Restored Expense accounting differs.")
    engine = create_async_engine(DATABASE_URL, hide_parameters=True)
    try:
        async with async_sessionmaker(engine)() as db:
            connection = await db.scalar(select(CalendarConnection).limit(1))
            queue_count = await db.scalar(
                select(func.count()).select_from(AccountingMirrorRefresh)
            )
            telegram_count = await db.scalar(select(func.count()).select_from(TelegramOutbox))
            ciphertext = connection.encrypted_refresh_token
            if queue_count != 1 or telegram_count != 1 or not ciphertext:
                raise RuntimeError("Restored durable queue state differs.")
            if SecretCipher(KEY).decrypt(ciphertext) != "synthetic-refresh-token":
                raise RuntimeError(
                    "Restored credential cannot be decrypted with the backed-up key."
                )
            try:
                SecretCipher("MTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTExMTE=").decrypt(
                    ciphertext
                )
            except Exception:
                pass
            else:
                raise RuntimeError("A wrong credential key unexpectedly decrypted restored data.")
    finally:
        await engine.dispose()


def main() -> None:
    if DATABASE_NAME not in DATABASE_URL or COMPOSE.name != "compose.backup-test.yaml":
        raise SystemExit("Refusing to run outside the isolated restore database.")
    env = {**os.environ, "DATABASE_URL": DATABASE_URL}
    with tempfile.TemporaryDirectory(prefix="technician-hub-restore-") as directory:
        compose("up", "-d", "--wait", "db")
        try:
            run(
                [sys.executable, "-m", "alembic", "upgrade", "head"],
                env=env,
                cwd=API_ROOT,
            )
            asyncio.run(seed())
            before = asyncio.run(fingerprint())
            run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-File",
                    str(ROOT / "scripts" / "backup-postgres.ps1"),
                    "-OutputDirectory",
                    directory,
                    "-ComposeFile",
                    str(COMPOSE),
                ]
            )
            dumps = list(Path(directory).glob("*.dump"))
            if len(dumps) != 1:
                raise RuntimeError("Backup tool did not produce exactly one dump.")
            dump = dumps[0]
            if dump.stat().st_size < 1024:
                raise RuntimeError("Synthetic backup is unexpectedly small.")
            manifest = json.loads(Path(f"{dump}.json").read_text(encoding="utf-8-sig"))
            digest = hashlib.sha256(dump.read_bytes()).hexdigest()
            if manifest.get("sha256") != digest:
                raise RuntimeError("Backup manifest digest does not match the dump.")
            compose(
                "exec",
                "-T",
                "db",
                "psql",
                "-v",
                "ON_ERROR_STOP=1",
                "-U",
                "hub",
                "-d",
                "postgres",
                "-c",
                f"DROP DATABASE {DATABASE_NAME} WITH (FORCE)",
            )
            compose(
                "exec",
                "-T",
                "db",
                "psql",
                "-v",
                "ON_ERROR_STOP=1",
                "-U",
                "hub",
                "-d",
                "postgres",
                "-c",
                f"CREATE DATABASE {DATABASE_NAME}",
            )
            with dump.open("rb") as stream:
                restored = subprocess.run(
                    [
                        "docker",
                        "compose",
                        "-f",
                        str(COMPOSE),
                        "exec",
                        "-T",
                        "db",
                        "pg_restore",
                        "--exit-on-error",
                        "--no-owner",
                        "--no-privileges",
                        "-U",
                        "hub",
                        "-d",
                        DATABASE_NAME,
                    ],
                    cwd=ROOT,
                    stdin=stream,
                    capture_output=True,
                    check=False,
                )
                if restored.returncode:
                    raise RuntimeError("Synthetic pg_restore failed safely.")
            run(
                [sys.executable, "-m", "alembic", "upgrade", "head"],
                env=env,
                cwd=API_ROOT,
            )
            after = asyncio.run(fingerprint())
            if after != before:
                raise RuntimeError("Restored structural fingerprint differs from backup source.")
            asyncio.run(verify_application())
            print(
                json.dumps(
                    {
                        "backup": "PASS",
                        "restore": "PASS",
                        "fingerprint": "MATCH",
                        "manager_login": "PASS",
                        "accounting": "PASS",
                        "durable_queues": "PASS",
                        "credential_key_behavior": "PASS",
                        "tables_verified": len(before),
                        "dump_sha256": digest,
                    },
                    sort_keys=True,
                )
            )
        finally:
            compose("down", "-v", "--remove-orphans")


if __name__ == "__main__":
    main()
