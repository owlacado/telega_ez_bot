"""Independent PostgreSQL audit; fake Telegram only."""

import asyncio
from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker
from telegram.error import BadRequest, Forbidden, NetworkError

from hub.auth.models import Manager, ManagerSession
from hub.auth.security import digest, now, random_token
from hub.core.config import Settings
from hub.integrations.models import TelegramBinding
from hub.telegram.adapter import TelegramBotAdapter, safe_error
from hub.telegram.delivery import deliver_one, recover_processing
from hub.telegram.models import (
    TelegramInvitation,
    TelegramOutbox,
    TelegramProcessedUpdate,
    TelegramWorkerState,
)
from hub.telegram.transport import parse_update
from hub.telegram.types import Member, ProviderError, TrustedEvent
from hub.telegram.updates import process_update
from hub.telegram.worker import Worker
from tests.conftest import TEST_URL
from tests.fakes import BOT_ID, BOT_USERNAME, FakeTelegram
from tests.telegram_helpers import claim, event, issue, state, technician

# Capture before the autouse network guard; only local async stubs are supplied.
REAL_MEMBER_MAPPING = TelegramBotAdapter.member


@pytest.fixture(autouse=True)
def configured(app):
    app.state.settings = Settings(
        database_url=TEST_URL,
        app_env="test",
        allow_fake_providers=True,
        telegram_mode="fake",
        telegram_expected_bot_id=BOT_ID,
        telegram_expected_bot_username=BOT_USERNAME,
    )


@pytest.fixture
def provider():
    return FakeTelegram()


async def connect(client, engine, provider, user=101, offset=1):
    identifier = await technician(client)
    invitation = await issue(client, identifier)
    assert (
        await claim(engine, provider, invitation, user_id=user, update_id=offset)
    ).outcome == "CONNECTED"
    return identifier


async def connect_group(client, engine, provider):
    identifier = await connect(client, engine, provider)
    invitation = await issue(client, identifier, "WORK_GROUP")
    provider.members[(-10001, BOT_ID)] = Member("member")
    assert (
        await claim(
            engine,
            provider,
            invitation,
            user_id=101,
            update_id=2,
            chat_id=-10001,
            chat_type="supergroup",
        )
    ).outcome == "CONNECTED"
    return identifier


async def test_malformed_lifecycle_cannot_select_null_group_identity(client, engine, provider):
    identifier = await connect(client, engine, provider)
    incoming = parse_update(
        {
            "update_id": 2,
            "my_chat_member": {
                "chat": {"type": "supergroup"},
                "new_chat_member": {"user": {"id": BOT_ID}, "status": "left"},
            },
        },
        BOT_USERNAME,
    )
    result = await process_update(async_sessionmaker(engine), provider, incoming, BOT_ID)
    assert result.outcome == "IGNORED"
    assert (await state(client, identifier))["group"]["availability"] == "UNKNOWN"


async def test_poll_retry_after_is_never_shortened(app, engine, provider, monkeypatch):
    import hub.telegram.worker as module

    delays = []

    async def timeout(awaitable, timeout):
        awaitable.close()
        delays.append(timeout)
        raise TimeoutError

    monkeypatch.setattr(module.asyncio, "wait_for", timeout)
    provider.poll_error = ProviderError("RATE_LIMITED", retry_after=300)
    with pytest.raises(ProviderError, match="RATE_LIMITED"):
        await Worker(app.state.settings, engine, provider).run(asyncio.Event(), max_cycles=1)
    assert delays == [300] * 5


async def test_week_idle_random_update_id_does_not_use_stale_offset(app, engine, provider):
    async with engine.begin() as db:
        await db.execute(
            TelegramWorkerState.__table__.insert().values(
                bot_id=BOT_ID, status="STOPPED", next_update_id=10001
            )
        )
        await db.execute(
            TelegramProcessedUpdate.__table__.insert().values(
                bot_id=BOT_ID,
                update_id=10000,
                outcome="IGNORED",
                processed_at=now() - timedelta(days=8),
            )
        )
    provider.events = [TrustedEvent(40, "IGNORED")]
    await Worker(app.state.settings, engine, provider).run(asyncio.Event(), max_cycles=1)
    assert provider.offsets == [None]
    async with async_sessionmaker(engine)() as db:
        assert await db.get(TelegramProcessedUpdate, (BOT_ID, 40))
        assert (await db.get(TelegramWorkerState, BOT_ID)).next_update_id == 41


async def test_provider_error_code_is_a_closed_sanitized_boundary(app, engine, provider, caplog):
    import logging

    secret = random_token()
    provider.poll_error = ProviderError("https://t.me/test_bot?start=" + secret)
    with caplog.at_level(logging.INFO, logger="hub.telegram.worker"):
        with pytest.raises(ProviderError) as caught:
            await Worker(app.state.settings, engine, provider).run(asyncio.Event(), max_cycles=1)
    assert secret not in str(caught.value) and secret not in caplog.text
    async with engine.connect() as db:
        values = (
            (await db.execute(text("SELECT row_to_json(s)::text FROM telegram_worker_states s")))
            .scalars()
            .all()
        )
        assert all(secret not in value for value in values)


async def test_chat_not_found_preserves_identity_but_marks_unavailable(client, engine, provider):
    identifier = await connect(client, engine, provider)
    provider.send_error = safe_error(BadRequest("Chat not found"))
    assert provider.send_error.code == "CHAT_UNAVAILABLE"
    await deliver_one(async_sessionmaker(engine, expire_on_commit=False), engine, provider, BOT_ID)
    value = (await state(client, identifier))["private"]
    assert (
        value["telegram_id"] == "101"
        and value["approved"]
        and value["availability"] == "UNAVAILABLE"
    )


@pytest.mark.parametrize("race", list("ABCDEFGHIJ"))
async def test_postgresql_race_matrix(client, engine, provider, race):
    factory = async_sessionmaker(engine, expire_on_commit=False)
    if race in "HIJ":
        identifier = (
            await connect_group(client, engine, provider)
            if race == "I"
            else await connect(client, engine, provider)
        )
    else:
        identifier = await technician(client)
    purpose = "WORK_GROUP" if race in "GI" else "PRIVATE_TELEGRAM"
    if race == "G":
        seed = await issue(client, identifier)
        await claim(engine, provider, seed, user_id=101, update_id=1)
    invitation = await issue(client, identifier, purpose, replace=race in "HIJ")
    kwargs = dict(user_id=101, update_id=20)
    if purpose == "WORK_GROUP":
        provider.members[(-10001, BOT_ID)] = Member("member")
        kwargs.update(chat_id=-10001, chat_type="supergroup")
    first = claim(engine, provider, invitation, **kwargs)
    endpoint = f"/api/technicians/{identifier}/telegram"
    if race in "AB":
        second = claim(
            engine,
            provider,
            invitation,
            **{**kwargs, "user_id": 102 if race == "A" else 101, "update_id": 21},
        )
    elif race == "C":
        second = client.post(endpoint + f"/invitations/{invitation['invitation']['id']}/revoke")
    elif race in "DJ":
        payload = {
            "purpose": purpose,
            "expected_generation": (await state(client, identifier))["private"]["generation"],
            "replace": race == "J",
            "confirmation": "REPLACE" if race == "J" else "CONNECT",
        }
        second = client.post(endpoint + "/invitations", json=payload)
        if race == "J":
            first.close()
            first = client.post(endpoint + "/invitations", json=payload)
    elif race == "E":
        version = (await client.get(f"/api/technicians/{identifier}")).json()["record_version"]
        second = client.request(
            "DELETE",
            f"/api/technicians/{identifier}",
            json={"confirmation": "DELETE", "expected_record_version": version},
        )
    elif race in "FG":
        other = (
            await connect(client, engine, provider, user=102, offset=3)
            if race == "G"
            else await technician(client)
        )
        other_invite = await issue(client, other, purpose)
        second = claim(
            engine,
            provider,
            other_invite,
            **{**kwargs, "update_id": 21, "user_id": 102 if race == "G" else 101},
        )
    else:
        part = (await state(client, identifier))["group" if race == "I" else "private"]
        second = client.post(
            endpoint + "/disconnect",
            json={
                "purpose": purpose,
                "expected_generation": part["generation"],
                "confirmation": "DISCONNECT",
            },
        )
    results = await asyncio.wait_for(asyncio.gather(first, second), 15)
    async with factory() as db:
        bindings = (await db.scalars(select(TelegramBinding))).all()
        invites = (await db.scalars(select(TelegramInvitation))).all()
        jobs = (await db.scalars(select(TelegramOutbox))).all()
        users = [b.telegram_user_id for b in bindings if b.telegram_user_id is not None]
        groups = [
            b.telegram_group_chat_id for b in bindings if b.telegram_group_chat_id is not None
        ]
        assert len(users) == len(set(users)) and len(groups) == len(set(groups))
        open_keys = [(i.technician_id, i.purpose) for i in invites if i.closed_at is None]
        assert len(open_keys) == len(set(open_keys))
        assert all(i.consumed_at and i.closed_at for i in invites if i.approved_at)
        assert len([i for i in invites if i.approved_at]) == len(
            [job for job in jobs if job.kind == "APPROVED"]
        )
        current = next((b for b in bindings if b.technician_id == UUID(identifier)), None)
        if race in "ABFG":
            assert [r.outcome for r in results].count("CONNECTED") == 1
            assert len(groups if race == "G" else users) == 1
        elif race == "E":
            assert results[1].status_code == 409
            assert results[0].outcome == "CONNECTED" and current is not None
        elif race == "J":
            assert [r.status_code for r in results] == [201, 201]
            assert len(open_keys) == 1 and current.telegram_user_id == 101
        elif race in "HI":
            if results[1].status_code == 204:
                assert results[0].outcome == "INVALID_INVITATION"
                assert (
                    current.telegram_group_chat_id if race == "I" else current.telegram_user_id
                ) is None
            else:
                assert results[1].status_code == 409 and results[0].outcome == "CONNECTED"
        elif results[0].outcome == "CONNECTED":
            assert results[1].status_code == 409 and current.telegram_user_id == 101
        else:
            assert results[1].status_code in {201, 204} and current.telegram_user_id is None


@pytest.mark.parametrize(
    "problem,status_code",
    [("anonymous", 401), ("inactive", 401), ("expired", 401), ("csrf", 403), ("origin", 403)],
)
async def test_every_administrative_operation_enforces_auth(client, engine, problem, status_code):
    identifier = await technician(client)
    invitation = await issue(client, identifier)
    endpoint = f"/api/technicians/{identifier}/telegram"
    invite_path = endpoint + f"/invitations/{invitation['invitation']['id']}"
    operations = [
        (
            "POST",
            endpoint + "/invitations",
            {
                "purpose": p,
                "replace": replace_,
                "confirmation": "REPLACE" if replace_ else "CONNECT",
                "expected_generation": 0,
            },
        )
        for p in ["PRIVATE_TELEGRAM", "WORK_GROUP"]
        for replace_ in [False, True]
    ]
    operations += [
        (
            "POST",
            endpoint + "/disconnect",
            {"purpose": p, "confirmation": "DISCONNECT", "expected_generation": 0},
        )
        for p in ["PRIVATE_TELEGRAM", "WORK_GROUP"]
    ]
    operations += [
        ("POST", invite_path + "/revoke", {}),
        ("POST", invite_path + "/review", {"decision": "APPROVE"}),
        ("POST", invite_path + "/retry", {}),
    ]
    if problem == "anonymous":
        client.cookies.clear()
    elif problem == "csrf":
        client.headers.pop("x-csrf-token")
    elif problem == "origin":
        client.headers["Origin"] = "https://untrusted.invalid"
    else:
        async with engine.begin() as db:
            await db.execute(
                update(Manager).values(is_active=False)
                if problem == "inactive"
                else update(ManagerSession).values(expires_at=now() - timedelta(seconds=1))
            )
    if problem != "csrf":
        operations += [("GET", endpoint, None), ("GET", "/api/telegram/runtime", None)]
    for method, path, payload in operations:
        response = await client.request(method, path, json=payload)
        assert response.status_code == status_code, (problem, method, path, response.status_code)
    async with engine.connect() as db:
        assert await db.scalar(select(func.count()).select_from(TelegramInvitation)) == 1
        assert await db.scalar(select(func.count()).select_from(TelegramOutbox)) == 0


async def test_production_telegram_route_allowlist_and_identity_injection(client):
    from hub.main import create_app

    production = create_app(
        Settings(
            _env_file=None,
            database_url="postgresql+asyncpg://hub:unique-production-secret@db/technician_hub",
            app_env="production",
            cookie_secure=True,
            allowed_origins=["https://hub.invalid"],
        )
    )
    actual = {
        (path, method.upper())
        for path, operations in production.openapi()["paths"].items()
        if "telegram" in path
        for method in operations
    }
    root = "/api/technicians/{identifier}/telegram"
    assert actual == {
        (root, "GET"),
        ("/api/telegram/runtime", "GET"),
        (root + "/invitations", "POST"),
        (root + "/disconnect", "POST"),
        (root + "/test-message", "POST"),
        *[
            (root + "/invitations/{invitation_id}/" + s, "POST")
            for s in ["revoke", "review", "retry"]
        ],
    }
    identifier = await technician(client)
    for field in ["telegram_user_id", "telegram_group_chat_id", "automatic", "token_hash"]:
        response = await client.post(
            f"/api/technicians/{identifier}/telegram/invitations",
            json={
                "purpose": "PRIVATE_TELEGRAM",
                "expected_generation": 0,
                "confirmation": "CONNECT",
                field: 123,
            },
        )
        assert response.status_code == 422
    with pytest.raises(ValueError):
        Settings(
            _env_file=None,
            database_url=TEST_URL,
            app_env="production",
            cookie_secure=True,
            allowed_origins=["https://hub.invalid"],
            telegram_mode="fake",
        )


@pytest.mark.parametrize("stage", ["before_send", "accepted_before_persistence"])
async def test_confirmation_crash_keeps_binding_and_never_blindly_resends(
    client, engine, provider, monkeypatch, stage
):
    from hub.telegram import delivery

    identifier = await connect(client, engine, provider)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def crash(*args, **kwargs):
        raise RuntimeError("simulated crash")

    if stage == "before_send":
        monkeypatch.setattr(provider, "send", crash)
    else:
        monkeypatch.setattr(delivery, "finish", crash)
    with pytest.raises(RuntimeError, match="simulated crash"):
        await deliver_one(factory, engine, provider, BOT_ID)
    await recover_processing(factory, BOT_ID)
    current = await state(client, identifier)
    assert current["private"]["approved"] and current["deliveries"][0]["state"] == "UNKNOWN"
    assert not await deliver_one(factory, engine, provider, BOT_ID)
    assert len(provider.sent) == (1 if stage == "accepted_before_persistence" else 0)


@pytest.mark.parametrize("error_type", [BadRequest, Forbidden, NetworkError])
def test_adapter_error_text_never_survives_boundary(error_type):
    token = random_token()
    detail = (
        "https://t.me/test_bot?start="
        + token
        + " "
        + "123456789:"
        + "x" * 35
        + " telegram_id=987654321"
    )
    result = safe_error(error_type(detail))
    assert token not in str(result) and "987654321" not in str(result) and len(str(result)) < 50


def test_token_encoding_entropy_and_configuration():
    import base64
    import re
    from urllib.parse import parse_qs, urlparse

    tokens = {random_token() for _ in range(1000)}
    assert len(tokens) == 1000
    for token in tokens:
        assert re.fullmatch(r"[A-Za-z0-9_-]{43}", token)
        assert len(base64.urlsafe_b64decode(token + "=")) == 32
        assert len(digest(token)) == 64 and digest(token) != digest(token + " ")
        assert parse_qs(urlparse("https://t.me/test_bot?start=" + token).query) == {
            "start": [token]
        }
    for name in ["bad?start=x", "bot/name", "@test_bot", "test bot", "test_bot#fragment"]:
        with pytest.raises(ValueError):
            Settings(_env_file=None, telegram_expected_bot_username=name)


@pytest.mark.parametrize("suffix", [" extra", "?start=x", "&start=x", "=", "\u200b"])
async def test_payload_mutations_do_not_claim(client, engine, provider, suffix):
    identifier = await technician(client)
    invitation = await issue(client, identifier)
    original = event(invitation, user_id=101)
    incoming = parse_update(
        {
            "update_id": 1,
            "message": {
                "chat": {"id": 101, "type": "private"},
                "from": {"id": 101, "is_bot": False},
                "text": "/start " + original.payload + suffix,
            },
        },
        BOT_USERNAME,
    )
    assert (
        await process_update(async_sessionmaker(engine), provider, incoming, BOT_ID)
    ).outcome == "INVALID_INVITATION"
    assert not (await state(client, identifier))["private"]["approved"]


async def test_unicode_metadata_is_bounded_not_identity(client, engine, provider):
    identifier = await technician(client, "Canonical")
    invitation = await issue(client, identifier)
    source = event(invitation, user_id=101)
    incoming = parse_update(
        {
            "update_id": 1,
            "message": {
                "chat": {"id": 101, "type": "private"},
                "from": {
                    "id": 101,
                    "is_bot": False,
                    "first_name": "<script>\u96ea</script>" * 40,
                    "username": "",
                },
                "text": "/start " + source.payload,
            },
        },
        BOT_USERNAME,
    )
    assert (
        await process_update(async_sessionmaker(engine), provider, incoming, BOT_ID)
    ).outcome == "CONNECTED"
    value = (await state(client, identifier))["private"]
    assert (
        len(value["display_name"]) == 200
        and value["username"] is None
        and value["telegram_id"] == "101"
    )
    assert (await client.get(f"/api/technicians/{identifier}")).json()["first_name"] == "Canonical"


async def test_live_schema_constraints_and_documented_gap(client, engine, provider):
    from sqlalchemy.exc import IntegrityError

    await connect(client, engine, provider)
    two = await technician(client)
    await issue(client, two)
    for sql in [
        "UPDATE telegram_bindings SET telegram_user_id=101",
        "UPDATE telegram_bindings SET private_status='invalid'",
        "UPDATE telegram_invitations SET purpose='invalid'",
    ]:
        with pytest.raises(IntegrityError):
            async with engine.begin() as db:
                await db.execute(text(sql))
    with pytest.raises(IntegrityError):
        async with engine.begin() as db:
            await db.execute(
                update(TelegramBinding)
                .where(TelegramBinding.technician_id == UUID(two))
                .values(private_status="CONNECTED", telegram_user_id=None)
            )
    assert not (await state(client, two))["private"]["approved"]
    async with engine.connect() as db:
        constraints = (
            (
                await db.execute(
                    text(
                        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                        "WHERE conrelid IN ('telegram_bindings'::regclass,"
                        "'telegram_invitations'::regclass)"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert any("UNIQUE (telegram_user_id)" in c for c in constraints)
        assert any("UNIQUE (telegram_group_chat_id)" in c for c in constraints)
        assert any("private_status" in c and "telegram_user_id" in c for c in constraints)
        assert any("ON DELETE CASCADE" in c for c in constraints)
        indexes = (
            (
                await db.execute(
                    text("SELECT indexdef FROM pg_indexes WHERE tablename='telegram_invitations'")
                )
            )
            .scalars()
            .all()
        )
        assert any("UNIQUE" in i and "closed_at IS NULL" in i for i in indexes)


async def test_contended_advisory_waiters_do_not_starve_owner_pool(engine):
    from sqlalchemy.ext.asyncio import create_async_engine

    from hub.telegram.locks import advisory_guard

    pool = create_async_engine(TEST_URL, pool_size=2, max_overflow=0, pool_timeout=0.5)
    waiters = []

    async def wait():
        async with advisory_guard(pool, "audit-pool", 123):
            pass

    try:
        async with advisory_guard(pool, "audit-pool", 123):
            waiters = [asyncio.create_task(wait()) for _ in range(5)]
            await asyncio.sleep(0.1)
            async with pool.connect() as db:
                assert await db.scalar(text("SELECT 1")) == 1
        await asyncio.wait_for(asyncio.gather(*waiters), 5)
    finally:
        for waiter in waiters:
            waiter.cancel()
        await asyncio.gather(*waiters, return_exceptions=True)
        await pool.dispose()


@pytest.mark.parametrize("permission", [True, False, None])
async def test_regular_bot_membership_observes_default_chat_send_permission(permission):
    from types import SimpleNamespace

    calls = []

    async def get_member(chat_id, user_id):
        calls.append((chat_id, user_id))
        return SimpleNamespace(status="member")

    async def get_chat(chat_id):
        return SimpleNamespace(
            permissions=SimpleNamespace(can_send_messages=permission)
            if permission is not None
            else None
        )

    stub = SimpleNamespace(
        bot=SimpleNamespace(get_chat_member=get_member, get_chat=get_chat),
        settings=SimpleNamespace(telegram_expected_bot_id=BOT_ID),
    )
    member = await REAL_MEMBER_MAPPING(stub, -10001, BOT_ID)
    assert member.present and member.can_send_messages is (permission is True)
    assert calls == [(-10001, BOT_ID)]
