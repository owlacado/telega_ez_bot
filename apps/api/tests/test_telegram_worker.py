import asyncio
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker
from telegram.error import BadRequest, Conflict, Forbidden, InvalidToken, RetryAfter, TimedOut

from hub.audit.models import AuditEvent
from hub.auth.security import now
from hub.core.config import Settings
from hub.telegram.adapter import safe_error
from hub.telegram.delivery import claim_job, deliver_one, recover_processing
from hub.telegram.locks import advisory_guard
from hub.telegram.models import (
    TelegramInvitation,
    TelegramOutbox,
    TelegramProcessedUpdate,
    TelegramWorkerState,
)
from hub.telegram.types import BotIdentity, ProviderError, TrustedEvent
from hub.telegram.updates import process_update
from hub.telegram.worker import Worker
from tests.conftest import TEST_URL
from tests.fakes import BOT_ID, BOT_USERNAME, FakeTelegram
from tests.telegram_helpers import connected_group, connected_private, issue, state


@pytest.fixture(autouse=True)
def configured_app(app):
    app.state.settings = Settings(
        database_url=TEST_URL,
        app_env="test",
        telegram_mode="fake",
        telegram_expected_bot_id=BOT_ID,
        telegram_expected_bot_username=BOT_USERNAME,
    )


@pytest.fixture
def provider():
    return FakeTelegram()


@pytest.fixture
def factory(engine):
    return async_sessionmaker(engine, expire_on_commit=False)


async def test_disabled_worker_has_no_provider_calls(app, engine, provider):
    settings = app.state.settings.model_copy(update={"telegram_mode": "disabled"})
    await Worker(settings, engine, provider).run(asyncio.Event(), max_cycles=1)
    assert not provider.initialized and not provider.offsets and not provider.sent


@pytest.mark.parametrize(
    "problem,expected",
    [
        ("webhook", "EXISTING_WEBHOOK_REFUSED"),
        ("identity", "BOT_IDENTITY_MISMATCH"),
        ("conflict", "POLLING_CONFLICT"),
    ],
)
async def test_startup_refuses_takeover(app, engine, provider, factory, problem, expected):
    if problem == "webhook":
        provider.webhook = True
    if problem == "identity":
        provider.identity = BotIdentity(BOT_ID + 1, "different_bot")
    if problem == "conflict":
        provider.poll_error = ProviderError("POLLING_CONFLICT")
    with pytest.raises(ProviderError, match=expected):
        await Worker(app.state.settings, engine, provider).run(asyncio.Event(), max_cycles=1)
    assert provider.closed and not provider.sent
    async with factory() as db:
        record = await db.get(TelegramWorkerState, BOT_ID)
        assert record.status == "FAILED" and record.error_code == expected


async def test_concurrent_poller_guard(app, engine, provider):
    async with advisory_guard(engine, "telegram-poller", BOT_ID, wait=False):
        with pytest.raises(RuntimeError, match="POLLER_ALREADY_RUNNING"):
            await Worker(app.state.settings, engine, provider).run(asyncio.Event(), max_cycles=1)
    assert not provider.initialized


async def test_offset_processing_failure_restart_and_dedup(
    app, engine, provider, factory, monkeypatch
):
    import hub.telegram.worker as worker_module

    worker = Worker(app.state.settings, engine, provider)
    provider.events = [
        TrustedEvent(10, "IGNORED"),
        TrustedEvent(11, "IGNORED"),
        TrustedEvent(12, "IGNORED"),
    ]
    original = worker_module.process_update

    async def fail_second(factory, provider, event, bot_id):
        if event.update_id == 11:
            raise RuntimeError("simulated processing interruption")
        return await original(factory, provider, event, bot_id)

    monkeypatch.setattr(worker_module, "process_update", fail_second)
    with pytest.raises(ProviderError, match="PROCESSING_FAILED"):
        await worker.run(asyncio.Event(), max_cycles=1)
    async with factory() as db:
        assert (await db.get(TelegramWorkerState, BOT_ID)).next_update_id == 11
        assert await db.get(TelegramProcessedUpdate, (BOT_ID, 10))
        assert not await db.get(TelegramProcessedUpdate, (BOT_ID, 11))
    monkeypatch.setattr(worker_module, "process_update", original)
    # Simulate crash after committing processing but before advancing the poll offset.
    await original(factory, provider, provider.events[1], BOT_ID)
    await Worker(app.state.settings, engine, provider).run(asyncio.Event(), max_cycles=1)
    assert provider.offsets == [None, 11]
    async with factory() as db:
        assert (await db.get(TelegramWorkerState, BOT_ID)).next_update_id == 13
        assert len((await db.scalars(select(TelegramProcessedUpdate))).all()) == 3


async def test_poll_timeout_retries_with_bounded_backoff(app, engine, provider, monkeypatch):
    import hub.telegram.worker as worker_module

    delays = []

    async def immediate_timeout(awaitable, timeout):
        awaitable.close()
        delays.append(timeout)
        raise TimeoutError

    monkeypatch.setattr(worker_module.asyncio, "wait_for", immediate_timeout)
    provider.poll_error = ProviderError("NETWORK_UNCERTAIN")
    with pytest.raises(ProviderError, match="NETWORK_UNCERTAIN"):
        await Worker(app.state.settings, engine, provider).run(asyncio.Event(), max_cycles=1)
    assert delays == [2, 4, 8, 16, 32] and len(provider.offsets) == 6


@pytest.mark.parametrize(
    "code,result",
    [("NETWORK_UNCERTAIN", "UNKNOWN"), ("ACCESS_DENIED", "FAILED"), ("REQUEST_REJECTED", "FAILED")],
)
async def test_notification_failure_preserves_binding(
    client, engine, provider, factory, code, result
):
    identifier = await connected_private(client, engine, provider)
    provider.send_error = ProviderError(code)
    assert await deliver_one(factory, engine, provider, BOT_ID)
    current = await state(client, identifier)
    assert current["private"]["approved"]
    assert current["deliveries"][0]["state"] == result
    assert not await deliver_one(factory, engine, provider, BOT_ID)
    assert not provider.sent


async def test_rate_limited_delivery_bounded_retry(client, engine, provider, factory):
    identifier = await connected_private(client, engine, provider)
    provider.send_error = ProviderError("RATE_LIMITED", retry_after=30)
    for attempt in range(3):
        assert await deliver_one(factory, engine, provider, BOT_ID)
        current = await state(client, identifier)
        assert current["deliveries"][0]["state"] == ("FAILED" if attempt == 2 else "QUEUED")
        async with factory() as db, db.begin():
            await db.execute(
                update(TelegramOutbox).values(available_at=now() - timedelta(seconds=10))
            )
    assert not await deliver_one(factory, engine, provider, BOT_ID)


async def test_worker_restart_does_not_replay_uncertain_send(client, engine, provider, factory):
    identifier = await connected_private(client, engine, provider)
    assert await claim_job(factory, BOT_ID)
    await recover_processing(factory, BOT_ID)
    assert (await state(client, identifier))["deliveries"][0]["state"] == "UNKNOWN"
    assert not await deliver_one(factory, engine, provider, BOT_ID)


async def test_test_message_destination_confirmation_and_rate_limit(
    client, engine, provider, factory
):
    identifier = await connected_group(client, engine, provider)
    path = f"/api/technicians/{identifier}/telegram/test-message"
    current = await state(client, identifier)
    payload = {
        "destination": "WORK_GROUP",
        "expected_generation": current["group"]["generation"],
        "confirmation": "SEND TEST",
    }
    assert (await client.post(path, json={**payload, "confirmation": "yes"})).status_code == 422
    assert (await client.post(path, json=payload)).status_code == 202
    assert (await client.post(path, json=payload)).status_code == 429
    while await deliver_one(factory, engine, provider, BOT_ID):
        pass
    assert provider.sent[-1][0] == -1009876543210
    assert (await state(client, identifier))["deliveries"][0]["state"] == "SENT"


async def test_disconnect_and_deletion_cancel_undelivered_work(client, engine, provider, factory):
    identifier = await connected_private(client, engine, provider)
    await issue(client, identifier, replace=True)
    current = await state(client, identifier)
    assert (
        await client.post(
            f"/api/technicians/{identifier}/telegram/disconnect",
            json={
                "purpose": "PRIVATE_ACCOUNT",
                "expected_generation": current["private"]["generation"],
                "confirmation": "DISCONNECT",
            },
        )
    ).status_code == 204
    assert not await deliver_one(factory, engine, provider, BOT_ID)
    assert not provider.sent
    assert (
        await client.request(
            "DELETE", f"/api/technicians/{identifier}", json={"confirmation": "DELETE"}
        )
    ).status_code == 204
    async with factory() as db:
        assert not (await db.scalars(select(TelegramInvitation))).all()
        assert not (await db.scalars(select(TelegramOutbox))).all()
        audits = (
            await db.scalars(select(AuditEvent).where(AuditEvent.target_id == UUID(identifier)))
        ).all()
        assert any(item.action == "technician.deleted" for item in audits)


async def test_delete_waits_for_inflight_send_and_no_transaction_over_network(
    client, engine, provider, factory
):
    identifier = await connected_private(client, engine, provider)
    entered, release = asyncio.Event(), asyncio.Event()

    async def slow_send(chat_id, message):
        # Session advisory lock stays open, but SQL transactions must not.
        async with engine.connect() as db:
            count = await db.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity WHERE "
                    "datname=current_database() AND state='idle in transaction'"
                )
            )
            assert count == 0
        entered.set()
        await release.wait()
        provider.sent.append((chat_id, message))
        return 1

    provider.send = slow_send
    send_task = asyncio.create_task(deliver_one(factory, engine, provider, BOT_ID))
    await asyncio.wait_for(entered.wait(), 5)
    delete_task = asyncio.create_task(
        client.request("DELETE", f"/api/technicians/{identifier}", json={"confirmation": "DELETE"})
    )
    await asyncio.sleep(0.1)
    assert not delete_task.done()
    release.set()
    await send_task
    assert (await delete_task).status_code == 204
    assert not await deliver_one(factory, engine, provider, BOT_ID)


async def test_lost_group_permissions_preserve_identity(client, engine, provider, factory):
    identifier = await connected_group(client, engine, provider)
    event = TrustedEvent(
        33,
        "BOT_MEMBERSHIP",
        chat_id=-1009876543210,
        chat_type="supergroup",
        member_user_id=BOT_ID,
        member_status="member",
        member_present=True,
    )
    await process_update(factory, provider, event, BOT_ID)
    current = await state(client, identifier)
    assert current["group"]["approved"] and current["group"]["availability"] == "UNAVAILABLE"
    await process_update(
        factory, provider, replace(event, update_id=34, member_status="administrator"), BOT_ID
    )
    assert (await state(client, identifier))["group"]["availability"] == "REVALIDATION_REQUIRED"


async def test_uninvited_commands_disclose_no_profile(client, engine, provider, factory):
    for i, command in enumerate(["/start", "/status", "/help", "/getid"]):
        result = await process_update(
            factory,
            provider,
            TrustedEvent(
                50 + i, "COMMAND", chat_type="private", chat_id=123, user_id=123, command=command
            ),
            BOT_ID,
        )
        assert result.outcome in {"INVITATION_REQUIRED", "HELP", "OWN_ID"}
        assert result.reply


@pytest.mark.parametrize(
    "error,code",
    [
        (TimedOut(), "NETWORK_UNCERTAIN"),
        (RetryAfter(30), "RATE_LIMITED"),
        (BadRequest("private detail"), "REQUEST_REJECTED"),
        (Forbidden("private detail"), "ACCESS_DENIED"),
        (Conflict("private detail"), "POLLING_CONFLICT"),
        (InvalidToken("sensitive token"), "INVALID_BOT_CREDENTIALS"),
    ],
)
def test_adapter_errors_are_sanitized(error, code):
    assert str(safe_error(error)) == code


def test_adapter_avoids_polling_bootstrap_and_webhook_mutation():
    source = (Path(__file__).parents[1] / "hub/telegram/adapter.py").read_text()
    assert "delete_webhook(" not in source and "set_webhook(" not in source
    assert "drop_pending_updates=" not in source and "run_polling(" not in source
    assert "await self.bot.initialize()" in source


async def test_stale_membership_update_cannot_affect_replaced_group(
    client, engine, provider, factory
):
    from hub.integrations.models import TelegramBinding
    from hub.technicians.models import Technician

    identifier = await connected_group(client, engine, provider)
    async with factory() as db:
        await db.scalar(
            select(Technician).where(Technician.id == UUID(identifier)).with_for_update()
        )
        task = asyncio.create_task(
            process_update(
                factory,
                provider,
                TrustedEvent(
                    90,
                    "BOT_MEMBERSHIP",
                    chat_id=-1009876543210,
                    chat_type="supergroup",
                    member_user_id=BOT_ID,
                    member_status="kicked",
                    member_present=False,
                ),
                BOT_ID,
            )
        )
        await asyncio.sleep(0.15)
        assert not task.done()
        await db.execute(
            update(TelegramBinding)
            .where(TelegramBinding.technician_id == UUID(identifier))
            .values(telegram_group_chat_id=-1009999999999, group_generation=2)
        )
        await db.commit()
    assert (await task).outcome == "IGNORED"
    current = (await state(client, identifier))["group"]
    assert current["telegram_id"] == "-1009999999999"
    assert current["availability"] == "AVAILABLE"
