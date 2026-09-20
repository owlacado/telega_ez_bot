import asyncio
from dataclasses import replace
from datetime import timedelta
from urllib.parse import parse_qs, urlparse
from uuid import UUID

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from hub.auth.security import digest, now
from hub.core.config import Settings
from hub.integrations.models import TelegramBinding
from hub.telegram.delivery import deliver_one
from hub.telegram.models import TelegramInvitation, TelegramProcessedUpdate
from hub.telegram.types import Member, TrustedEvent
from hub.telegram.updates import operational_access, process_update
from tests.conftest import TEST_URL
from tests.fakes import BOT_ID, BOT_USERNAME, FakeTelegram
from tests.telegram_helpers import (
    claim,
    connected_group,
    connected_private,
    event,
    patch_technician,
    review,
    state,
    technician,
)
from tests.telegram_helpers import (
    legacy_issue as issue,
)


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


async def test_invite_entropy_hash_only_and_private_approval(client, engine, provider):
    identifier = await technician(client)
    invitation = await issue(client, identifier)
    token = parse_qs(urlparse(invitation["link"]).query)["start"][0]
    assert len(token) == 43
    async with engine.connect() as db:
        assert await db.scalar(select(TelegramInvitation.token_hash)) == digest(token)
    assert token not in str(await state(client, identifier))
    result = await claim(engine, provider, invitation)
    assert result.outcome == "AWAITING_APPROVAL"
    async with async_sessionmaker(engine)() as db:
        assert not await operational_access(db, 12345678, BOT_ID)
    pending = (await state(client, identifier))["private"]
    assert pending["invitation"]["candidate_username"] is None
    assert pending["invitation"]["candidate_user_id"] == "12345678"
    assert not pending["approved"]
    assert (await review(client, identifier, invitation)).status_code == 204
    assert (await state(client, identifier))["private"]["approved"]
    async with async_sessionmaker(engine)() as db:
        assert await operational_access(db, 12345678, BOT_ID)


@pytest.mark.parametrize("chat_type", ["group", "supergroup", "channel"])
async def test_private_token_rejects_wrong_context(client, engine, provider, chat_type):
    invitation = await issue(client, await technician(client))
    assert (
        await claim(engine, provider, invitation, chat_type=chat_type, chat_id=-1001)
    ).outcome == "INVALID_INVITATION"


@pytest.mark.parametrize("change", [{"anonymous": True}, {"user_is_bot": True}, {"chat_id": 555}])
async def test_private_rejects_ambiguous_or_bot_identity(client, engine, provider, change):
    invitation = await issue(client, await technician(client))
    result = await process_update(
        async_sessionmaker(engine, expire_on_commit=False),
        provider,
        replace(event(invitation), **change),
        BOT_ID,
    )
    assert result.outcome in {"IGNORED", "INVALID_INVITATION"}


async def test_expiration_revocation_regeneration(client, engine, provider):
    identifier = await technician(client)
    old = await issue(client, identifier)
    fresh = await issue(client, identifier)
    assert (await claim(engine, provider, old)).outcome == "INVALID_INVITATION"
    assert (
        await client.post(
            f"/api/technicians/{identifier}/telegram/invitations/{fresh['invitation']['id']}/revoke"
        )
    ).status_code == 204
    assert (await claim(engine, provider, fresh, update_id=2)).outcome == "INVALID_INVITATION"
    expired = await issue(client, identifier)
    async with engine.begin() as db:
        await db.execute(
            update(TelegramInvitation)
            .where(TelegramInvitation.id == UUID(expired["invitation"]["id"]))
            .values(expires_at=now() - timedelta(seconds=1))
        )
    assert (await claim(engine, provider, expired, update_id=3)).outcome == "INVALID_INVITATION"


async def test_pending_approval_expiry(client, engine, provider):
    identifier = await technician(client)
    invitation = await issue(client, identifier)
    await claim(engine, provider, invitation)
    async with engine.begin() as db:
        await db.execute(update(TelegramInvitation).values(expires_at=now() - timedelta(seconds=1)))
    assert (await review(client, identifier, invitation)).status_code == 409
    assert not (await state(client, identifier))["private"]["approved"]


async def test_atomic_single_use_and_duplicate_update(client, engine, provider):
    identifier = await technician(client)
    invitation = await issue(client, identifier)
    results = await asyncio.gather(
        claim(engine, provider, invitation, user_id=111, update_id=100),
        claim(engine, provider, invitation, user_id=222, update_id=101),
    )
    assert sorted(result.outcome for result in results) == [
        "AWAITING_APPROVAL",
        "INVALID_INVITATION",
    ]
    assert (
        await claim(engine, provider, invitation, user_id=111, update_id=100)
    ).outcome == "DUPLICATE"
    async with engine.connect() as db:
        assert await db.scalar(select(func.count()).select_from(TelegramProcessedUpdate)) == 2


async def test_same_account_competing_approvals(client, engine, provider):
    first, second = await technician(client, "First"), await technician(client, "Second")
    one, two = await issue(client, first), await issue(client, second)
    await claim(engine, provider, one, update_id=1)
    await claim(engine, provider, two, update_id=2)
    responses = await asyncio.gather(review(client, first, one), review(client, second, two))
    assert sorted(response.status_code for response in responses) == [204, 409]
    async with engine.connect() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(TelegramBinding)
                .where(TelegramBinding.telegram_user_id == 12345678)
            )
            == 1
        )


async def test_replacement_preserves_old_identity_and_revalidates_group(client, engine, provider):
    identifier = await connected_group(client, engine, provider)
    invitation = await issue(client, identifier, replace=True)
    pending = await state(client, identifier)
    assert pending["private"]["replacement_pending"]
    assert pending["private"]["telegram_id"] == "12345678"
    await claim(engine, provider, invitation, user_id=987654321, update_id=3)
    assert (await review(client, identifier, invitation, "REJECT")).status_code == 204
    assert (await state(client, identifier))["private"]["telegram_id"] == "12345678"
    second = await issue(client, identifier, replace=True)
    await claim(engine, provider, second, user_id=987654321, update_id=4)
    assert (await review(client, identifier, second)).status_code == 204
    current = await state(client, identifier)
    assert current["private"]["telegram_id"] == "987654321"
    assert current["group"]["telegram_id"] == "-1009876543210"
    assert current["group"]["availability"] == "REVALIDATION_REQUIRED"
    assert (await review(client, identifier, second)).status_code == 409


async def test_group_requires_private_account(client):
    identifier = await technician(client)
    response = await client.post(
        f"/api/technicians/{identifier}/telegram/invitations",
        json={
            "purpose": "WORK_GROUP",
            "replace": False,
            "expected_generation": 0,
            "confirmation": "CONNECT",
        },
    )
    assert response.status_code == 409


async def test_group_large_negative_id_and_existing_bot_membership(client, engine, provider):
    identifier = await connected_group(client, engine, provider, chat_id=-1009876543210123)
    result = (await state(client, identifier))["group"]
    assert result["approved"] and result["telegram_id"] == "-1009876543210123"
    assert result["availability"] == "AVAILABLE"


@pytest.mark.parametrize(
    "problem", ["non_admin", "anonymous_admin", "bot_not_admin", "technician_absent"]
)
async def test_group_recoverable_checks_and_retry(client, engine, provider, problem):
    identifier = await connected_private(client, engine, provider)
    invitation = await issue(client, identifier, "WORK_GROUP")
    chat, actor = -100222222, 123444
    provider.group(chat, actor, 12345678)
    if problem == "non_admin":
        provider.members[(chat, actor)] = Member("member")
    if problem == "anonymous_admin":
        provider.members[(chat, actor)] = Member("administrator", is_anonymous=True)
    if problem == "bot_not_admin":
        provider.members[(chat, BOT_ID)] = Member("member")
    if problem == "technician_absent":
        provider.members[(chat, 12345678)] = Member("left")
    assert (
        await claim(
            engine,
            provider,
            invitation,
            user_id=actor,
            chat_type="supergroup",
            chat_id=chat,
            update_id=2,
        )
    ).outcome == "NEEDS_SETUP"
    assert (await review(client, identifier, invitation)).status_code == 409
    provider.group(chat, actor, 12345678)
    assert (
        await client.post(
            f"/api/technicians/{identifier}/telegram/invitations/{invitation['invitation']['id']}/retry"
        )
    ).status_code == 202
    factory = async_sessionmaker(engine, expire_on_commit=False)
    for _ in range(3):
        await deliver_one(factory, engine, provider, BOT_ID)
    response = await review(client, identifier, invitation)
    assert response.status_code == 204, (response.text, await state(client, identifier))


@pytest.mark.parametrize("chat_type", ["private", "channel"])
async def test_group_token_wrong_context(client, engine, provider, chat_type):
    identifier = await connected_private(client, engine, provider)
    invitation = await issue(client, identifier, "WORK_GROUP")
    assert (
        await claim(engine, provider, invitation, chat_type=chat_type, update_id=2)
    ).outcome == "INVALID_INVITATION"


async def test_group_anonymous_sender_rejected(client, engine, provider):
    identifier = await connected_private(client, engine, provider)
    invitation = await issue(client, identifier, "WORK_GROUP")
    result = await claim(
        engine,
        provider,
        invitation,
        chat_type="supergroup",
        chat_id=-1003,
        update_id=2,
        sender_chat={"id": -1003, "type": "supergroup"},
    )
    assert result.outcome == "IGNORED"


async def test_group_conflict_not_stolen(client, engine, provider):
    first = await connected_group(client, engine, provider)
    second = await connected_private(client, engine, provider, user_id=333333, update_id=5)
    invitation = await issue(client, second, "WORK_GROUP")
    provider.group(-1009876543210, 333333, 333333)
    await claim(
        engine,
        provider,
        invitation,
        user_id=333333,
        chat_type="supergroup",
        chat_id=-1009876543210,
        update_id=6,
    )
    assert (await review(client, second, invitation)).status_code == 409
    assert (await state(client, first))["group"]["approved"]


async def test_group_checks_must_be_fresh_at_approval(client, engine, provider):
    identifier = await connected_private(client, engine, provider)
    invitation = await issue(client, identifier, "WORK_GROUP")
    provider.group(-1004, 12345678, 12345678)
    await claim(engine, provider, invitation, chat_type="group", chat_id=-1004, update_id=2)
    async with engine.begin() as db:
        await db.execute(
            update(TelegramInvitation).values(verified_at=now() - timedelta(minutes=3))
        )
    assert (await review(client, identifier, invitation)).status_code == 409


async def test_inactive_and_deleted_identity_cannot_claim_or_reappear(client, engine, provider):
    identifier = await technician(client)
    invitation = await issue(client, identifier)
    assert (
        await patch_technician(client, identifier, status="INACTIVE")
    ).status_code == 200
    assert (await claim(engine, provider, invitation)).outcome == "INVALID_INVITATION"
    assert (
        await client.request(
            "DELETE",
            f"/api/technicians/{identifier}",
            json={
                "confirmation": "DELETE",
                "expected_updated_at": (await client.get(f"/api/technicians/{identifier}")).json()[
                    "updated_at"
                ],
            },
        )
    ).status_code == 204
    assert (await claim(engine, provider, invitation, update_id=2)).outcome == "INVALID_INVITATION"
    assert (await review(client, identifier, invitation)).status_code == 404
    async with engine.connect() as db:
        assert await db.scalar(select(func.count()).select_from(TelegramInvitation)) == 0


async def test_disconnect_independent_stale_tab_and_private_suspension(client, engine, provider):
    identifier = await connected_group(client, engine, provider)
    current = await state(client, identifier)
    path = f"/api/technicians/{identifier}/telegram/disconnect"
    assert (
        await client.post(
            path,
            json={
                "purpose": "WORK_GROUP",
                "expected_generation": current["group"]["generation"],
                "confirmation": "DISCONNECT",
            },
        )
    ).status_code == 204
    after = await state(client, identifier)
    assert after["private"]["approved"] and not after["group"]["approved"]
    assert (
        await client.post(
            path,
            json={
                "purpose": "WORK_GROUP",
                "expected_generation": current["group"]["generation"],
                "confirmation": "DISCONNECT",
            },
        )
    ).status_code == 409
    assert (
        await client.post(
            path,
            json={
                "purpose": "PRIVATE_TELEGRAM",
                "expected_generation": current["private"]["generation"],
                "confirmation": "DISCONNECT",
            },
        )
    ).status_code == 204
    async with async_sessionmaker(engine)() as db:
        assert not await operational_access(db, 12345678, BOT_ID)


async def test_blocking_preserves_identity_and_stops_delivery(client, engine, provider):
    identifier = await connected_group(client, engine, provider)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    blocked = TrustedEvent(
        20,
        "BOT_MEMBERSHIP",
        chat_id=12345678,
        chat_type="private",
        member_user_id=BOT_ID,
        member_status="kicked",
        member_present=False,
    )
    await process_update(factory, provider, blocked, BOT_ID)
    current = await state(client, identifier)
    assert current["private"]["telegram_id"] == "12345678"
    assert current["private"]["availability"] == "BLOCKED"
    assert current["group"]["availability"] == "PRIVATE_UNAVAILABLE"
    async with factory() as db:
        assert not await operational_access(db, 12345678, BOT_ID)
    await process_update(
        factory,
        provider,
        replace(blocked, update_id=21, member_status="member", member_present=True),
        BOT_ID,
    )
    assert (await state(client, identifier))["private"]["availability"] == "AVAILABLE"


async def test_trusted_migration_and_conflict(client, engine, provider):
    first = await connected_group(client, engine, provider, chat_id=-10051)
    second = await connected_group(
        client, engine, provider, user_id=43211234, chat_id=-10052, update_id=5
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    result = await process_update(
        factory,
        provider,
        TrustedEvent(20, "MIGRATION", chat_id=-10051, migrated_chat_id=-10052),
        BOT_ID,
    )
    assert result.outcome == "MIGRATION_CONFLICT"
    assert (await state(client, first))["group"]["telegram_id"] == "-10051"
    assert (await state(client, second))["group"]["telegram_id"] == "-10052"
    await process_update(
        factory,
        provider,
        TrustedEvent(21, "MIGRATION", chat_id=-10051, migrated_chat_id=-10053),
        BOT_ID,
    )
    current = (await state(client, first))["group"]
    assert current["telegram_id"] == "-10053" and current["availability"] == "REVALIDATION_REQUIRED"


async def test_browser_cannot_supply_provider_identity_or_raw_updates(client):
    identifier = await technician(client)
    assert (await client.post("/api/telegram/updates", json={"update_id": 1})).status_code == 404
    assert (
        await client.patch(f"/api/technicians/{identifier}", json={"telegram_user_id": 111})
    ).status_code == 422
    assert (
        await client.post(
            f"/api/technicians/{identifier}/telegram/test-message",
            json={
                "destination": "PRIVATE_TELEGRAM",
                "expected_generation": 0,
                "confirmation": "SEND TEST",
                "chat_id": 111,
            },
        )
    ).status_code == 422
