"""Existing-binding recovery, using isolated PostgreSQL and fake Telegram only."""

import asyncio
from dataclasses import replace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from hub.core.config import Settings
from hub.integrations.models import TelegramBinding
from hub.technicians.models import Technician
from hub.telegram.delivery import deliver_one, recover_processing
from hub.telegram.models import TelegramOutbox, TelegramWorkerState
from hub.telegram.types import BotIdentity, Member, ProviderError, TrustedEvent
from hub.telegram.updates import process_update
from hub.telegram.worker import Worker
from tests.conftest import TEST_URL
from tests.fakes import BOT_ID, BOT_USERNAME, FakeTelegram

USER = 771001
GROUP = -771002


@pytest.fixture
async def ready(engine):
    sessions = []

    class TrackedSession(AsyncSession):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            sessions.append(self)

    factory = async_sessionmaker(engine, class_=TrackedSession, expire_on_commit=False)
    async with factory() as db, db.begin():
        tech = Technician(first_name="Recovery", last_name="Test")
        db.add(tech)
        await db.flush()
        db.add(
            TelegramBinding(
                technician_id=tech.id,
                bot_id=BOT_ID,
                private_status="CONNECTED",
                private_availability="AVAILABLE",
                telegram_user_id=USER,
                private_generation=1,
                group_status="CONNECTED",
                group_availability="AVAILABLE",
                telegram_group_chat_id=GROUP,
                group_generation=1,
                group_private_generation=1,
            )
        )
    fake = FakeTelegram()
    fake.group(GROUP, USER, USER)
    original_member, original_initialize = fake.member, fake.initialize

    async def member(*args):
        assert all(not session.in_transaction() for session in sessions)
        return await original_member(*args)

    async def initialize():
        assert all(not session.in_transaction() for session in sessions)
        return await original_initialize()

    fake.member, fake.initialize = member, initialize
    return factory, fake, tech.id


def membership(update_id=100, present=True, **values):
    return replace(
        TrustedEvent(
            update_id=update_id,
            kind="MEMBER",
            chat_id=GROUP,
            chat_type="supergroup",
            member_user_id=USER,
            member_status="member" if present else "left",
            member_present=present,
        ),
        **values,
    )


async def incoming(ready, event):
    factory, fake, _ = ready
    return await process_update(factory, fake, event, BOT_ID)


async def binding(ready):
    factory, _, identifier = ready
    async with factory() as db:
        return await db.get(TelegramBinding, identifier)


async def jobs(ready):
    async with ready[0]() as db:
        return list(await db.scalars(select(TelegramOutbox).order_by(TelegramOutbox.created_at)))


async def drain(ready, engine):
    factory, fake, _ = ready
    while await deliver_one(factory, engine, fake, BOT_ID):
        pass


async def test_remove_rejoin_recovers_same_binding_without_reviving_cancelled_work(ready, engine):
    factory, fake, identifier = ready
    async with factory() as db, db.begin():
        old = TelegramOutbox(
            technician_id=identifier,
            bot_id=BOT_ID,
            kind="TEST",
            destination="WORK_GROUP",
            generation=1,
            private_generation=1,
        )
        db.add(old)
    assert (await incoming(ready, membership(present=False))).outcome == "AVAILABILITY_UPDATED"
    assert (await binding(ready)).group_availability == "UNAVAILABLE"
    assert (await jobs(ready))[0].state == "CANCELLED"
    assert (await incoming(ready, membership(101))).outcome == "AVAILABILITY_UPDATED"
    assert (await binding(ready)).group_availability == "REVALIDATION_REQUIRED"
    await drain(ready, engine)
    current = await binding(ready)
    assert current.group_availability == "AVAILABLE" and current.group_status == "CONNECTED"
    assert (current.telegram_user_id, current.telegram_group_chat_id) == (USER, GROUP)
    assert (
        current.private_generation
        == current.group_generation
        == current.group_private_generation
        == 1
    )
    assert [(job.kind, job.state) for job in await jobs(ready)] == [
        ("TEST", "CANCELLED"),
        ("VERIFY_GROUP", "SENT"),
    ]
    assert not fake.sent  # Verification never sends a message.
    assert (await incoming(ready, membership(101))).outcome == "DUPLICATE"
    await incoming(ready, membership(102))
    await drain(ready, engine)
    assert (await binding(ready)).group_availability == "AVAILABLE"
    assert (await binding(ready)).group_generation == 1


@pytest.mark.parametrize(
    "change",
    [
        {"member_user_id": USER + 1},
        {"chat_id": GROUP - 1},
        {"kind": "BOT_MEMBERSHIP", "member_user_id": BOT_ID + 1},
    ],
)
async def test_unrelated_membership_cannot_recover(ready, engine, change):
    await incoming(ready, membership(present=False))
    assert (await incoming(ready, membership(101, **change))).outcome == "IGNORED"
    await drain(ready, engine)
    assert (await binding(ready)).group_availability == "UNAVAILABLE"
    assert not await jobs(ready)


@pytest.mark.parametrize(
    "field,value",
    [
        ("private_generation", 2),
        ("group_generation", 2),
        ("group_private_generation", None),
        ("telegram_user_id", USER + 1),
        ("telegram_group_chat_id", GROUP - 1),
        ("bot_id", BOT_ID + 1),
        ("private_availability", "BLOCKED"),
        ("group_status", "NOT_CONNECTED"),
    ],
)
@pytest.mark.parametrize("during_io", [False, True])
async def test_changed_binding_cannot_recover_before_or_during_verification(
    ready, engine, field, value, during_io
):
    factory, fake, identifier = ready
    await incoming(ready, membership())

    async def mutate():
        async with factory() as db, db.begin():
            current = await db.get(TelegramBinding, identifier)
            setattr(current, field, value)

    if during_io:
        original = fake.initialize

        async def initialize():
            result = await original()
            await mutate()
            return result

        fake.initialize = initialize
    else:
        await mutate()
    await drain(ready, engine)
    assert (await binding(ready)).group_availability != "AVAILABLE"
    assert (await jobs(ready))[0].state == "CANCELLED"
    assert not fake.sent


@pytest.mark.parametrize(
    "failure", ["bot_missing", "bot_cannot_send", "technician_missing", "identity", "provider"]
)
async def test_live_checks_fail_closed(ready, engine, failure):
    _, fake, _ = ready
    await incoming(ready, membership())
    if failure == "bot_missing":
        fake.members[(GROUP, BOT_ID)] = Member("left")
    elif failure == "bot_cannot_send":
        fake.members[(GROUP, BOT_ID)] = Member(
            "restricted", is_member=True, can_send_messages=False
        )
    elif failure == "technician_missing":
        fake.members[(GROUP, USER)] = Member("left")
    elif failure == "identity":
        fake.identity = BotIdentity(BOT_ID + 1, "unexpected_bot")
    else:
        fake.member_error = ProviderError("NETWORK_UNCERTAIN")
    await drain(ready, engine)
    assert (await binding(ready)).group_availability != "AVAILABLE"
    assert (await jobs(ready))[0].state == ("QUEUED" if failure == "provider" else "FAILED")
    assert not fake.sent


async def test_new_removal_invalidates_inflight_membership_proof(ready, engine):
    _, fake, _ = ready
    await incoming(ready, membership())
    original = fake.member
    removed = False

    async def member(chat, user):
        nonlocal removed
        result = await original(chat, user)
        if not removed:
            removed = True
            await incoming(ready, membership(101, present=False))
        return result  # Deliberately return the stale positive result.

    fake.member = member
    await drain(ready, engine)
    assert (await binding(ready)).group_availability == "UNAVAILABLE"
    assert (await jobs(ready))[0].state == "CANCELLED"


async def test_repeated_rejoin_cancels_old_proof_and_worker_restart_can_resume(ready, engine):
    factory, _, _ = ready
    await incoming(ready, membership())
    await incoming(ready, membership(101))
    async with factory() as db, db.begin():
        current_jobs = list(
            await db.scalars(select(TelegramOutbox).order_by(TelegramOutbox.created_at))
        )
        assert [job.state for job in current_jobs] == ["CANCELLED", "QUEUED"]
        current_jobs[-1].state = "PROCESSING"
    await recover_processing(factory, BOT_ID)
    await drain(ready, engine)
    assert (await binding(ready)).group_availability == "AVAILABLE"
    assert [job.state for job in await jobs(ready)] == ["CANCELLED", "SENT"]


async def test_stale_private_relationship_never_queues_recovery(ready, engine):
    factory, _, identifier = ready
    await incoming(ready, membership(present=False))
    async with factory() as db, db.begin():
        current = await db.get(TelegramBinding, identifier)
        current.private_generation = 2
    await incoming(ready, membership(101))
    await drain(ready, engine)
    assert (await binding(ready)).group_availability != "AVAILABLE"
    assert not await jobs(ready)


async def test_worker_automatically_recovers_and_preserves_durable_offset(ready, engine):
    factory, fake, _ = ready
    fake.events = [membership(present=False), membership(101)]
    settings = Settings(
        database_url=TEST_URL,
        app_env="test",
        allow_fake_providers=True,
        telegram_mode="fake",
        telegram_expected_bot_id=BOT_ID,
        telegram_expected_bot_username=BOT_USERNAME,
    )
    worker = Worker(settings, engine, fake)
    worker.factory = factory
    await worker.run(asyncio.Event(), max_cycles=2)
    assert (await binding(ready)).group_availability == "AVAILABLE"
    assert [job.state for job in await jobs(ready)] == ["SENT"]
    async with factory() as db:
        assert (await db.get(TelegramWorkerState, BOT_ID)).next_update_id == 102


async def test_bot_rejoin_uses_same_verification_and_technician_must_still_be_present(
    ready, engine
):
    _, fake, _ = ready
    await incoming(ready, membership(present=False, kind="BOT_MEMBERSHIP", member_user_id=BOT_ID))
    assert (await binding(ready)).group_availability == "UNAVAILABLE"
    fake.members[(GROUP, USER)] = Member("left")
    await incoming(ready, membership(101, kind="BOT_MEMBERSHIP", member_user_id=BOT_ID))
    await drain(ready, engine)
    assert (await binding(ready)).group_availability != "AVAILABLE"
    fake.members[(GROUP, USER)] = Member("member")
    await incoming(ready, membership(102))
    await drain(ready, engine)
    assert (await binding(ready)).group_availability == "AVAILABLE"


async def test_transient_verification_failure_retries_read_only_and_recovers(ready, engine):
    from hub.auth.security import now

    factory, fake, _ = ready
    await incoming(ready, membership())
    fake.member_error = ProviderError("NETWORK_UNCERTAIN")
    await drain(ready, engine)
    assert (await jobs(ready))[0].state == "QUEUED"
    assert (await binding(ready)).group_availability != "AVAILABLE"
    fake.member_error = None
    async with factory() as db, db.begin():
        job = await db.get(TelegramOutbox, (await jobs(ready))[0].id)
        job.available_at = now()
    await drain(ready, engine)
    assert (await binding(ready)).group_availability == "AVAILABLE"
    assert (await jobs(ready))[0].attempts == 2
    assert not fake.sent


async def test_simultaneous_rejoins_leave_one_current_recovery(ready, engine):
    await asyncio.gather(incoming(ready, membership()), incoming(ready, membership(101)))
    assert sorted(job.state for job in await jobs(ready)) == ["CANCELLED", "QUEUED"]
    await asyncio.gather(drain(ready, engine), drain(ready, engine))
    assert (await binding(ready)).group_availability == "AVAILABLE"
    assert sorted(job.state for job in await jobs(ready)) == ["CANCELLED", "SENT"]


async def test_unavailable_binding_can_recover_and_manager_projection_is_connected(ready, engine):
    from hub.telegram.state import read_state

    factory, _, identifier = ready
    await incoming(ready, membership())
    async with factory() as db, db.begin():
        current = await db.get(TelegramBinding, identifier)
        current.group_availability = "UNAVAILABLE"
    await drain(ready, engine)
    async with factory() as db:
        state = await read_state(db, identifier, Settings(telegram_expected_bot_id=BOT_ID))
        assert state.group.approved and state.group.state == "CONNECTED"
        assert state.group.availability == "AVAILABLE"
        assert state.group.generation == state.private.generation == 1


@pytest.mark.parametrize("delay", [-1, 0, 3, 600, 601])
async def test_verification_respects_existing_rate_limit_retry_bounds(ready, engine, delay):
    _, fake, _ = ready
    await incoming(ready, membership())
    fake.member_error = ProviderError("RATE_LIMITED", retry_after=delay)
    await drain(ready, engine)
    assert (await jobs(ready))[0].state == ("QUEUED" if 0 <= delay <= 600 else "FAILED")
    assert (await binding(ready)).group_availability != "AVAILABLE"
