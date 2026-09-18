"""Current automatic onboarding; legacy review regression tests remain separate."""

import asyncio
from dataclasses import replace
from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from hub.audit.models import AuditEvent
from hub.auth.security import digest, now
from hub.core.config import Settings
from hub.integrations.models import TelegramBinding
from hub.technicians.models import Technician
from hub.telegram.claims import consume_claim, prepare_claim
from hub.telegram.delivery import deliver_one
from hub.telegram.models import TelegramInvitation, TelegramOutbox, TelegramProcessedUpdate
from hub.telegram.transport import parse_update
from hub.telegram.types import Member, ProviderError
from hub.telegram.updates import process_update
from tests.conftest import TEST_URL
from tests.fakes import BOT_ID, BOT_USERNAME, FakeTelegram
from tests.telegram_helpers import claim, event, issue, state, technician


@pytest.fixture(autouse=True)
def configured(app):
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


async def connected(client, engine, provider, user=12345678, offset=1):
    identifier = await technician(client)
    invitation = await issue(client, identifier)
    assert (
        await claim(engine, provider, invitation, user_id=user, update_id=offset)
    ).outcome == "CONNECTED"
    return identifier


async def disconnect(client, identifier, purpose):
    current = await state(client, identifier)
    part = current["private" if purpose == "PRIVATE_TELEGRAM" else "group"]
    return await client.post(
        f"/api/technicians/{identifier}/telegram/disconnect",
        json={
            "purpose": purpose,
            "expected_generation": part["generation"],
            "confirmation": "DISCONNECT",
        },
    )


async def test_private_atomic_connection_metadata_hash_audit_and_home(
    client, engine, provider, credentials
):
    identifier = await technician(client, "Canonical")
    invitation = await issue(client, identifier)
    incoming = replace(event(invitation), username="technician_test")
    token = incoming.payload
    assert len(token) == 43 and invitation["invitation"]["automatic"]
    factory = async_sessionmaker(engine, expire_on_commit=False)
    result = await process_update(factory, provider, incoming, BOT_ID)
    assert result.outcome == "CONNECTED"
    current = (await state(client, identifier))["private"]
    assert current["state"] == "CONNECTED" and current["username"] == "technician_test"
    assert token not in str(await state(client, identifier))
    assert token not in (await client.get("/api/technicians")).text
    async with factory() as db:
        value = await db.get(TelegramInvitation, UUID(invitation["invitation"]["id"]))
        assert value.token_hash == digest(token) and value.consumed_at and value.closed_at
        assert value.approved_at and not value.reviewed_by_manager_id
        assert (await db.get(Technician, UUID(identifier))).first_name == "Canonical"
        event_row = await db.scalar(
            select(AuditEvent).where(AuditEvent.action == "telegram.connected")
        )
        assert event_row.actor_id == credentials["id"] and event_row.target_id == UUID(identifier)
        assert event_row.actor_kind == "TELEGRAM_WORKER" and event_row.outcome == "PRIVATE_TELEGRAM"
        assert await db.scalar(select(func.count()).select_from(TelegramOutbox)) == 1
        # No raw token exists in any stored invitation column, including serialized metadata.
        columns = (
            (await db.execute(text("SELECT row_to_json(t)::text FROM telegram_invitations t")))
            .scalars()
            .all()
        )
        assert all(token not in row for row in columns)
    assert await deliver_one(factory, engine, provider, BOT_ID)
    assert provider.sent == [(12345678, "You're connected to Technician Hub.")]
    home = await process_update(
        factory, provider, replace(incoming, update_id=2, payload=None), BOT_ID
    )
    assert home.outcome == "CONNECTED"
    assert home.reply == "You're connected to Technician Hub. /report — Submit Report"
    assert (await claim(engine, provider, invitation, update_id=3)).outcome == "INVALID_INVITATION"
    assert (await claim(engine, provider, invitation)).outcome == "DUPLICATE"


@pytest.mark.parametrize("reason", ["expired", "revoked", "replaced", "deleted", "inactive"])
async def test_unusable_invitation_never_creates_binding(client, engine, provider, reason):
    identifier = await technician(client)
    invitation = await issue(client, identifier)
    if reason == "expired":
        async with engine.begin() as db:
            await db.execute(
                update(TelegramInvitation).values(expires_at=now() - timedelta(seconds=1))
            )
    elif reason == "revoked":
        assert (
            await client.post(
                f"/api/technicians/{identifier}/telegram/invitations/{invitation['invitation']['id']}/revoke"
            )
        ).status_code == 204
    elif reason == "replaced":
        await issue(client, identifier)
    elif reason == "inactive":
        await client.patch(f"/api/technicians/{identifier}", json={"status": "INACTIVE"})
    else:
        profile = (await client.get(f"/api/technicians/{identifier}")).json()
        assert (
            await client.request(
                "DELETE",
                f"/api/technicians/{identifier}",
                json={"confirmation": "DELETE", "expected_updated_at": profile["updated_at"]},
            )
        ).status_code == 204
    assert (await claim(engine, provider, invitation)).outcome == "INVALID_INVITATION"
    async with engine.connect() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(TelegramBinding)
                .where(TelegramBinding.telegram_user_id.is_not(None))
            )
            == 0
        )


@pytest.mark.parametrize("context", ["group", "supergroup", "channel"])
async def test_private_purpose_cannot_bind_other_context(client, engine, provider, context):
    invitation = await issue(client, await technician(client))
    assert (
        await claim(engine, provider, invitation, chat_type=context, chat_id=-10010)
    ).outcome == "INVALID_INVITATION"


async def test_competing_claims_one_winner_and_account_unique(client, engine, provider):
    identifier = await technician(client)
    invitation = await issue(client, identifier)
    results = await asyncio.wait_for(
        asyncio.gather(
            claim(engine, provider, invitation, user_id=111, update_id=1),
            claim(engine, provider, invitation, user_id=222, update_id=2),
        ),
        10,
    )
    assert sorted(x.outcome for x in results) == ["CONNECTED", "INVALID_INVITATION"]
    first, second = await technician(client), await technician(client)
    one, two = await issue(client, first), await issue(client, second)
    results = await asyncio.wait_for(
        asyncio.gather(
            claim(engine, provider, one, user_id=333, update_id=3),
            claim(engine, provider, two, user_id=333, update_id=4),
        ),
        10,
    )
    assert sorted(x.outcome for x in results) == ["CONNECTED", "NEEDS_SETUP"]
    async with engine.connect() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(TelegramBinding)
                .where(TelegramBinding.telegram_user_id == 333)
            )
            == 1
        )


async def test_parallel_invitation_creation_revokes_previous_and_audits(client, engine):
    identifier = await technician(client)
    first, second = await asyncio.gather(issue(client, identifier), issue(client, identifier))
    assert first["link"] != second["link"]
    async with engine.connect() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(TelegramInvitation)
                .where(TelegramInvitation.closed_at.is_(None))
            )
            == 1
        )
        assert (
            await db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "telegram.invitation_replaced")
            )
            == 1
        )


async def test_revoke_racing_claim_has_consistent_winner(client, engine, provider):
    identifier = await technician(client)
    invitation = await issue(client, identifier)
    result, revoked = await asyncio.wait_for(
        asyncio.gather(
            claim(engine, provider, invitation),
            client.post(
                f"/api/technicians/{identifier}/telegram/invitations/{invitation['invitation']['id']}/revoke"
            ),
        ),
        10,
    )
    assert (result.outcome, revoked.status_code) in {
        ("CONNECTED", 409),
        ("INVALID_INVITATION", 204),
    }
    assert (await state(client, identifier))["private"]["approved"] == (
        result.outcome == "CONNECTED"
    )


@pytest.mark.parametrize("chat_type", ["group", "supergroup"])
async def test_group_exact_linked_actor_regular_bot_and_disconnect(
    client, engine, provider, chat_type
):
    identifier = await connected(client, engine, provider)
    invitation = await issue(client, identifier, "WORK_GROUP")
    chat = -10070001
    provider.members[(chat, BOT_ID)] = Member("member")
    assert (
        await claim(
            engine,
            provider,
            invitation,
            user_id=999,
            chat_type=chat_type,
            chat_id=chat,
            update_id=2,
        )
    ).outcome == "INVALID_INVITATION"
    assert (
        await claim(engine, provider, invitation, chat_type=chat_type, chat_id=chat, update_id=3)
    ).outcome == "CONNECTED"
    factory = async_sessionmaker(engine, expire_on_commit=False)
    while await deliver_one(factory, engine, provider, BOT_ID):
        pass
    assert (chat, "Technician Hub connected this group to Demo Test.") in provider.sent
    assert (await state(client, identifier))["group"]["state"] == "CONNECTED"
    assert (await disconnect(client, identifier, "PRIVATE_TELEGRAM")).status_code == 204
    partial = await state(client, identifier)
    assert not partial["private"]["approved"] and partial["group"]["approved"]
    assert partial["group"]["availability"] == "REVALIDATION_REQUIRED"
    assert (await disconnect(client, identifier, "WORK_GROUP")).status_code == 204
    new = await issue(client, identifier)
    assert new["link"] != invitation["link"]
    assert (await claim(engine, provider, new, update_id=4)).outcome == "CONNECTED"


@pytest.mark.parametrize("context", ["private", "channel"])
async def test_group_purpose_rejects_other_chat_types(client, engine, provider, context):
    identifier = await connected(client, engine, provider)
    invitation = await issue(client, identifier, "WORK_GROUP")
    assert (
        await claim(
            engine,
            provider,
            invitation,
            chat_type=context,
            chat_id=12345678 if context == "private" else -1001,
            update_id=2,
        )
    ).outcome == "INVALID_INVITATION"


async def test_group_unique_across_technicians(client, engine, provider):
    one = await connected(client, engine, provider, user=111, offset=1)
    two = await connected(client, engine, provider, user=222, offset=2)
    a, b = await issue(client, one, "WORK_GROUP"), await issue(client, two, "WORK_GROUP")
    provider.members[(-10070, BOT_ID)] = Member("member")
    results = await asyncio.wait_for(
        asyncio.gather(
            claim(engine, provider, a, user_id=111, update_id=3, chat_type="group", chat_id=-10070),
            claim(engine, provider, b, user_id=222, update_id=4, chat_type="group", chat_id=-10070),
        ),
        10,
    )
    assert sorted(x.outcome for x in results) == ["CONNECTED", "NEEDS_SETUP"]


@pytest.mark.parametrize("problem", ["left", "restricted", "network"])
async def test_group_provider_failure_never_binds_and_new_invite_recovers(
    client, engine, provider, problem
):
    identifier = await connected(client, engine, provider)
    invitation = await issue(client, identifier, "WORK_GROUP")
    provider.members[(-10070, BOT_ID)] = Member(problem, is_member=True, can_send_messages=False)
    if problem == "network":
        provider.member_error = ProviderError("NETWORK_UNCERTAIN")
    assert (
        await claim(engine, provider, invitation, update_id=2, chat_type="group", chat_id=-10070)
    ).outcome == "NEEDS_SETUP"
    assert not (await state(client, identifier))["group"]["approved"]
    # Error tokens stay consumed: provider recovery requires a new credential.
    assert (
        await claim(engine, provider, invitation, update_id=3, chat_type="group", chat_id=-10070)
    ).outcome == "INVALID_INVITATION"
    provider.member_error = None
    provider.members[(-10070, BOT_ID)] = Member("member")
    fresh = await issue(client, identifier, "WORK_GROUP")
    assert (
        await claim(engine, provider, fresh, update_id=4, chat_type="group", chat_id=-10070)
    ).outcome == "CONNECTED"


async def test_claim_transaction_rollback_keeps_token_and_binding_unchanged(
    client, engine, provider, monkeypatch
):
    identifier = await technician(client)
    invitation = await issue(client, identifier)
    from hub.telegram import claims

    original = claims.activate

    async def broken(*args):
        await original(*args)
        raise RuntimeError("injected local failure")

    monkeypatch.setattr(claims, "activate", broken)
    with pytest.raises(RuntimeError):
        await claim(engine, provider, invitation)
    async with async_sessionmaker(engine)() as db:
        value = await db.get(TelegramInvitation, UUID(invitation["invitation"]["id"]))
        assert value.consumed_at is None and value.closed_at is None
        assert (await db.get(TelegramBinding, UUID(identifier))).telegram_user_id is None
        assert await db.scalar(select(func.count()).select_from(TelegramOutbox)) == 0
        assert await db.scalar(select(func.count()).select_from(TelegramProcessedUpdate)) == 0
    monkeypatch.setattr(claims, "activate", original)
    assert (await claim(engine, provider, invitation)).outcome == "CONNECTED"


async def test_private_change_during_group_proof_rejected(client, engine, provider):
    identifier = await connected(client, engine, provider)
    invitation = await issue(client, identifier, "WORK_GROUP")
    provider.members[(-10070, BOT_ID)] = Member("member")
    incoming = event(invitation, update_id=2, chat_type="group", chat_id=-10070)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    proof = await prepare_claim(factory, incoming, provider, BOT_ID)
    assert proof
    await disconnect(client, identifier, "PRIVATE_TELEGRAM")
    async with factory() as db, db.begin():
        assert await consume_claim(db, incoming, proof, BOT_ID) == "INVALID_INVITATION"


@pytest.mark.parametrize(
    "text_value", ["hello", "/start", "/start invalid", "/start " + "z" * 10000]
)
async def test_unknown_users_never_create_technicians(engine, provider, text_value):
    incoming = parse_update(
        {
            "update_id": 1,
            "message": {
                "chat": {"id": 123, "type": "private"},
                "from": {"id": 123, "is_bot": False},
                "text": text_value,
            },
        },
        BOT_USERNAME,
    )
    result = await process_update(async_sessionmaker(engine), provider, incoming, BOT_ID)
    assert result.outcome in {"INVITATION_REQUIRED", "INVALID_INVITATION", "IGNORED"}
    if result.reply:
        assert "manager" in result.reply and "123" not in result.reply
    async with engine.connect() as db:
        assert await db.scalar(select(func.count()).select_from(Technician)) == 0


@pytest.mark.parametrize(
    "message",
    [
        [],
        "bad",
        {"chat": []},
        {"from": []},
        {"text": 123},
        {"chat": {"id": 1, "type": "private"}, "from": {"id": 1}, "text": "/start"},
        {"my_chat_member": {"new_chat_member": []}},
    ],
)
async def test_malformed_nested_payloads_do_not_crash_or_bind(engine, provider, message):
    incoming = parse_update({"update_id": 1, "message": message}, BOT_USERNAME)
    result = await process_update(async_sessionmaker(engine), provider, incoming, BOT_ID)
    assert result.outcome == "IGNORED"


async def test_managers_only_and_cross_technician_invite_denied(client, anonymous, engine):
    one, two = await technician(client), await technician(client)
    invitation = await issue(client, one)
    path = f"/api/technicians/{two}/telegram/invitations/{invitation['invitation']['id']}/revoke"
    assert (await client.post(path)).status_code == 404
    client.cookies.clear()
    for method, endpoint in [
        ("GET", f"/api/technicians/{one}/telegram"),
        ("POST", f"/api/technicians/{one}/telegram/invitations"),
        ("POST", f"/api/technicians/{one}/telegram/disconnect"),
        ("POST", path),
    ]:
        assert (await client.request(method, endpoint)).status_code == 401


async def test_real_adapter_missing_secret_fails_before_bot_construction(monkeypatch):
    from hub.telegram import adapter

    def forbidden(*args, **kwargs):
        raise AssertionError("Missing credentials must not construct a network client")

    monkeypatch.setattr(adapter, "Bot", forbidden)
    settings = Settings(
        _env_file=None,
        telegram_mode="real",
        telegram_bot_token=None,
        telegram_token_file=None,
        telegram_expected_bot_id=BOT_ID,
        telegram_expected_bot_username=BOT_USERNAME,
    )
    with pytest.raises(ProviderError, match="BOT_NOT_CONFIGURED"):
        adapter.TelegramBotAdapter(settings)


@pytest.mark.parametrize("payload", [None, [], {}, {"update_id": True}, {"update_id": -1}])
async def test_malformed_update_envelope_has_safe_failure(payload):
    with pytest.raises(ValueError, match="MALFORMED_UPDATE_ID"):
        parse_update(payload, BOT_USERNAME)


async def test_worker_logs_codes_without_invitation_or_profile_data(
    client, engine, provider, app, caplog
):
    import logging

    from hub.telegram.worker import Worker

    identifier = await technician(client, "PrivateProfileMarker")
    invitation = await issue(client, identifier)
    incoming = event(invitation)
    provider.events = [incoming]
    with caplog.at_level(logging.INFO, logger="hub.telegram.worker"):
        await Worker(app.state.settings, engine, provider).run(asyncio.Event(), max_cycles=1)
    assert "telegram_worker_state" in caplog.text
    assert incoming.payload not in caplog.text and invitation["link"] not in caplog.text
    assert "PrivateProfileMarker" not in caplog.text and "Demo Candidate" not in caplog.text


async def test_identifier_alone_does_not_report_connected(client, engine):
    identifier = await technician(client)
    await issue(client, identifier)
    async with engine.begin() as db:
        await db.execute(
            update(TelegramBinding).values(
                telegram_user_id=123, private_status="ERROR", private_availability="AVAILABLE"
            )
        )
        await db.execute(update(TelegramInvitation).values(closed_at=now(), revoked_at=now()))
    value = (await state(client, identifier))["private"]
    assert value["state"] == "ERROR" and not value["approved"]
