"""Approved pilot activity flows against isolated PostgreSQL and fake Telegram."""

import asyncio
from dataclasses import replace
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from hub.audit.models import AuditEvent
from hub.auth.security import now
from hub.expenses import service as expenses
from hub.expenses.models import TechnicianExpense
from hub.expenses.schemas import ExpenseInput
from hub.integrations.models import TelegramBinding
from hub.schedule_delivery.acknowledgements import acknowledge
from hub.technicians.models import Technician
from hub.telegram import delivery
from hub.telegram.models import TelegramOutbox
from hub.telegram.types import Member, ProviderError, TrustedEvent
from hub.work_reports.models import WorkReport
from tests import test_schedule_delivery as schedule_tests
from tests import test_work_reports as report_tests
from tests.fakes import BOT_ID, FakeTelegram
from tests.test_calendar_events import assigned as assigned
from tests.test_expenses import issue as issue_expense
from tests.test_google_calendar import google as google
from tests.test_schedule_delivery import deliver_private_prompt, enqueue, row, run_delivery
from tests.test_work_reports import BASE, PAYLOAD, selected

schedule_ready = schedule_tests.ready
report_ready = report_tests.ready


@pytest.fixture
async def activity_ready(app, report_ready):
    async with app.state.session_factory() as db, db.begin():
        tech = await db.get(Technician, report_ready)
        tech.accounting_timezone = "America/Los_Angeles"
        binding = await db.get(TelegramBinding, report_ready)
        binding.group_status = "CONNECTED"
        binding.group_availability = "AVAILABLE"
        binding.group_generation = binding.group_private_generation = 1
        binding.telegram_group_chat_id = -771002
    return report_ready


async def submit(app, client, kind):
    if kind == "WORK_REPORT":
        token, headers, _ = await selected(app, client)
        result = await client.post(BASE + "/submit", headers=headers, json=PAYLOAD)
        assert result.status_code == 200, result.text
        again = await client.post(BASE + "/submit", headers=headers, json=PAYLOAD)
        assert again.json() == result.json()
    else:
        token = await issue_expense(app)
        payload = ExpenseInput(expense_type="Supplies", amount="12.34", note="<b>literal</b>")
        result = await expenses.submit(app.state.session_factory, token, payload)
        assert await expenses.submit(app.state.session_factory, token, payload) == result
    async with app.state.session_factory() as db:
        jobs = list(await db.scalars(select(TelegramOutbox).where(TelegramOutbox.kind == kind)))
        assert len(jobs) == 1
        return jobs[0].id


async def saved_job(app, identifier):
    async with app.state.session_factory() as db:
        return await db.get(TelegramOutbox, identifier)


def provider():
    fake = FakeTelegram()
    fake.group(-771002, 771001, 771001)
    return fake


async def deliver(app, fake):
    return await delivery.deliver_one(
        app.state.session_factory, app.state.google_lock_engine, fake, BOT_ID, app.state.settings
    )


@pytest.mark.parametrize("kind", ["WORK_REPORT", "EXPENSE"])
@pytest.mark.parametrize(
    "error,state",
    [
        (None, "SENT"),
        ("ACCESS_DENIED", "FAILED"),
        ("NETWORK_UNCERTAIN", "UNKNOWN"),
        ("PROVIDER_UNAVAILABLE", "UNKNOWN"),
    ],
)
async def test_commit_delivery_independence_and_no_replay(
    app, client, activity_ready, kind, error, state
):
    identifier = await submit(app, client, kind)
    fake = provider()
    if error:
        fake.send_error = ProviderError(error)
    await deliver(app, fake)
    assert (await saved_job(app, identifier)).state == state
    fake.send_error = None
    assert not await deliver(app, fake)
    async with app.state.session_factory() as db:
        model = WorkReport if kind == "WORK_REPORT" else TechnicianExpense
        assert await db.scalar(select(func.count()).select_from(model)) == 1
    if not error:
        chat, message = fake.sent[0]
        assert chat == -771002
        assert (
            "saved" in message
            and str(activity_ready) not in message
            and str(identifier) not in message
        )
        assert len(message.encode("utf-16-le")) <= 4096 * 2
        assert ("850.10" if kind == "WORK_REPORT" else "12.34") in message
        assert ("PRIVATE_NOTES <script>" if kind == "WORK_REPORT" else "<b>literal</b>") in message
    else:
        assert not fake.sent


@pytest.mark.parametrize("kind", ["WORK_REPORT", "EXPENSE"])
@pytest.mark.parametrize(
    "change", ["rebound", "unavailable", "missing_member", "inspection_race", "inspection_error"]
)
async def test_group_fencing(app, client, activity_ready, kind, change):
    identifier = await submit(app, client, kind)
    fake = provider()
    if change in {"rebound", "unavailable"}:
        async with app.state.session_factory() as db, db.begin():
            binding = await db.get(TelegramBinding, activity_ready)
            if change == "rebound":
                binding.group_generation += 1
                binding.telegram_group_chat_id = -888888
            else:
                binding.group_availability = "REVALIDATION_REQUIRED"
    elif change == "missing_member":
        # Even a regular bot must check the technician, not merely its own membership.
        fake.members[(-771002, BOT_ID)] = Member("member", can_send_messages=True)
        fake.members[(-771002, 771001)] = Member("left")
    elif change == "inspection_error":
        fake.member_error = ProviderError("NETWORK_UNCERTAIN")
    else:
        original = fake.member

        async def member(chat, actor):
            async with app.state.session_factory() as db, db.begin():
                binding = await db.get(TelegramBinding, activity_ready)
                binding.group_availability = "UNAVAILABLE"
            return await original(chat, actor)

        fake.member = member
    await deliver(app, fake)
    assert not fake.sent
    assert (await saved_job(app, identifier)).state in {"FAILED", "CANCELLED"}


@pytest.mark.parametrize("kind", ["WORK_REPORT", "EXPENSE"])
async def test_missing_group_is_durable_terminal_intent(app, client, activity_ready, kind):
    async with app.state.session_factory() as db, db.begin():
        binding = await db.get(TelegramBinding, activity_ready)
        binding.group_availability = "UNAVAILABLE"
    identifier = await submit(app, client, kind)
    assert (await saved_job(app, identifier)).state == "CANCELLED"
    assert not await deliver(app, provider())


async def test_rate_rejection_and_restart_safety(app, client, activity_ready):
    identifier = await submit(app, client, "EXPENSE")
    fake = provider()
    fake.send_error = ProviderError("RATE_LIMITED", retry_after=1)
    await deliver(app, fake)
    assert (await saved_job(app, identifier)).state == "QUEUED"
    async with app.state.session_factory() as db, db.begin():
        job = await db.get(TelegramOutbox, identifier)
        job.available_at = now() - timedelta(seconds=1)
    fake.send_error = None
    await deliver(app, fake)
    assert len(fake.sent) == 1
    assert (await saved_job(app, identifier)).state == "SENT"
    # A crash after a claim is conservatively UNKNOWN, never blindly resent.
    identifier = await submit(app, client, "WORK_REPORT")
    assert await delivery.claim_job(app.state.session_factory, BOT_ID)
    await delivery.recover_processing(app.state.session_factory, BOT_ID)
    assert (await saved_job(app, identifier)).state == "UNKNOWN"
    assert not await deliver(app, fake)


@pytest.mark.parametrize("availability", ["UNAVAILABLE", "REVALIDATION_REQUIRED"])
async def test_ack_availability_and_exactly_once(app, client, schedule_ready, availability):
    first = await enqueue(client, schedule_ready)
    fake = FakeTelegram()
    await run_delivery(app, fake)
    await deliver_private_prompt(app, fake)
    saved = await row(app, first["id"])
    event = TrustedEvent(
        10,
        "CALLBACK",
        chat_id=saved.telegram_user_id,
        chat_type="private",
        user_id=771001,
        message_id=saved.ack_message_id,
        payload=fake.schedule_sent[-1][2],
    )
    async with app.state.session_factory() as db, db.begin():
        binding = await db.get(TelegramBinding, schedule_ready)
        binding.group_availability = availability
    assert await acknowledge(app.state.session_factory, event, BOT_ID) == "ACK_UNAVAILABLE"
    async with app.state.session_factory() as db, db.begin():
        binding = await db.get(TelegramBinding, schedule_ready)
        binding.group_availability = "AVAILABLE"
    assert (
        await asyncio.gather(
            *[acknowledge(app.state.session_factory, event, BOT_ID) for _ in range(4)]
        )
        == ["ACKNOWLEDGED"] * 4
    )
    async with app.state.session_factory() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "schedule.acknowledged")
            )
            == 1
        )
    # A newly accepted resend supersedes the older exact dispatch immediately.
    second = await enqueue(
        client,
        schedule_ready,
        {
            "target_date": first["target_date"],
            "fingerprint": first["fingerprint"],
            "resend_of_id": first["id"],
            "confirm_duplicate_risk": True,
        },
    )
    assert (await row(app, first["id"])).superseded_at is not None
    assert await acknowledge(app.state.session_factory, event, BOT_ID) == "ACK_UNAVAILABLE"
    await run_delivery(app, fake)
    await deliver_private_prompt(app, fake)
    current = await row(app, second["id"])
    event = replace(event, message_id=current.ack_message_id, payload=fake.schedule_sent[-1][2])
    assert await acknowledge(app.state.session_factory, event, BOT_ID) == "ACKNOWLEDGED"


async def test_concurrent_claim_and_unexpected_accepted_send(app, client, activity_ready):
    identifier = await submit(app, client, "EXPENSE")
    fake = provider()
    original = fake.send

    async def uncertain(chat, message):
        await original(chat, message)
        raise RuntimeError("Synthetic response loss after accept")

    fake.send = uncertain
    results = await asyncio.gather(deliver(app, fake), deliver(app, fake), return_exceptions=True)
    assert sum(isinstance(result, RuntimeError) for result in results) == 1
    assert results.count(False) == 1
    assert len(fake.sent) == 1
    assert (await saved_job(app, identifier)).state == "PROCESSING"
    # Preserve the shared worker's crash/restart path for unexpected exceptions.
    await delivery.recover_processing(app.state.session_factory, BOT_ID)
    assert (await saved_job(app, identifier)).state == "UNKNOWN"
    assert not await deliver(app, fake)


async def test_business_rollback_also_rolls_back_intent(app, client, activity_ready, monkeypatch):
    async def fail(*args):
        raise RuntimeError("Synthetic precommit failure")

    token = await issue_expense(app)
    monkeypatch.setattr(expenses, "enqueue_for_business_change", fail)
    with pytest.raises(RuntimeError, match="precommit"):
        await expenses.submit(
            app.state.session_factory,
            token,
            ExpenseInput(expense_type="Supplies", amount="0.00", note=""),
        )
    async with app.state.session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(TechnicianExpense)) == 0
        assert await db.scalar(select(func.count()).select_from(TelegramOutbox)) == 0


def test_message_unicode_budget():
    from hub.telegram.activity import clip

    value = chr(0x1F600) * 4000
    clipped = clip(value, 3900)
    assert len(clipped.encode("utf-16-le")) <= 7800
    assert clipped.endswith("\u2026")


async def test_upgrade_preserves_receipts_and_backfills_supersession(
    app, client, schedule_ready, monkeypatch
):
    import os
    import subprocess
    import sys
    from pathlib import Path

    from sqlalchemy import update

    from hub.schedule_delivery.models import ScheduleDispatch
    from tests.conftest import TEST_URL

    # Simulate pre-private-ACK history at construction, before immutable receipt guards.
    original_init = ScheduleDispatch.__init__

    def historical_init(self, **values):
        values["private_ack_required"] = False
        original_init(self, **values)

    monkeypatch.setattr(ScheduleDispatch, "__init__", historical_init)
    first = await enqueue(client, schedule_ready)
    fake = FakeTelegram()
    await run_delivery(app, fake)
    await enqueue(
        client,
        schedule_ready,
        {
            "target_date": first["target_date"],
            "fingerprint": first["fingerprint"],
            "resend_of_id": first["id"],
            "confirm_duplicate_risk": True,
        },
    )
    await run_delivery(app, fake)
    before = await row(app, first["id"])
    async with app.state.session_factory() as db, db.begin():
        await db.execute(update(ScheduleDispatch).values(superseded_at=None))
    # Recreate the previous schema with real historical dispatches, then upgrade.
    for command, revision in [("downgrade", "fda609200001"), ("upgrade", "head")]:
        result = subprocess.run(
            [sys.executable, "-m", "alembic", command, revision],
            cwd=Path(__file__).parents[1],
            env={**os.environ, "DATABASE_URL": TEST_URL},
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
    after = await row(app, first["id"])
    assert after.superseded_at is not None
    assert (after.status, after.message_id, after.sent_at, after.ack_status) == (
        before.status,
        before.message_id,
        before.sent_at,
        before.ack_status,
    )
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "fda609200001"],
        cwd=Path(__file__).parents[1],
        env={**os.environ, "DATABASE_URL": TEST_URL},
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0 and "PILOT_ACTIVITY_HISTORY_ROLLBACK_REFUSED" in result.stderr
