"""Independent Stage 2 audit: fake transports only, real PostgreSQL invariants."""

import asyncio
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from hub.audit.models import AuditEvent
from hub.auth.security import now
from hub.calendars.models import Calendar, CalendarAssignment
from hub.core.secrets import SecretCipher
from hub.google_calendar import service
from hub.google_calendar.models import CalendarConnection
from hub.google_calendar.types import ProviderError
from tests.test_google_calendar import (
    BASE,
    Reply,
    begin,
    catalog,
    connect,
    disconnect,
    entry,
    paged_adapter,
    technician,
)
from tests.test_google_calendar import google as google


async def test_reconnect_missing_token_rejects_corrupt_old_credential(client, app, google):
    await connect(client)
    async with app.state.session_factory() as db:
        await db.execute(update(CalendarConnection).values(encrypted_refresh_token="v1:corrupt"))
        await db.commit()
    google.grant = replace(google.grant, refresh_token=None)
    response = await client.get(await begin(client, "RECONNECT"))
    assert response.headers["location"].endswith("error")
    assert (await client.get(BASE)).json()["generation"] == 1


async def test_reconnect_missing_token_revalidates_revoked_old_credential(
    client, google, monkeypatch
):
    await connect(client)
    google.grant = replace(google.grant, refresh_token=None)

    async def revoked(token):
        raise ProviderError("REAUTH_REQUIRED")

    monkeypatch.setattr(google, "refresh_credentials", revoked)
    response = await client.get(await begin(client, "RECONNECT"))
    assert response.headers["location"].endswith("error")


async def test_identical_assignment_and_repeated_restore_are_noops(client, app, google):
    await connect(client)
    cal = (await catalog(client))[0]
    tech = await technician(client)
    await client.put(f"/api/technicians/{tech['id']}/calendar", json={"calendar_id": cal["id"]})
    async with app.state.session_factory() as db:
        count = await db.scalar(select(func.count()).select_from(CalendarAssignment))
        audits = await db.scalar(select(func.count()).select_from(AuditEvent))
    assert (
        await client.put(
            f"/api/calendars/{cal['id']}/assignment",
            json={
                "technician_id": tech["id"],
                "expected_assigned_technician_id": tech["id"],
            },
        )
    ).status_code == 204
    assert (await client.post(f"/api/calendars/{cal['id']}/restore")).status_code == 204
    async with app.state.session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(CalendarAssignment)) == count
        assert await db.scalar(select(func.count()).select_from(AuditEvent)) == audits


async def test_rotated_refresh_token_survives_page_three_failure(client, app, google, monkeypatch):
    await connect(client)
    before = await catalog(client)
    rotated = "audit-rotated-synthetic-refresh"
    google.grant = replace(google.grant, refresh_token=rotated)
    adapter, calls = paged_adapter(
        monkeypatch,
        [
            Reply({"items": [entry(0)], "nextPageToken": "two"}),
            Reply({"items": [entry(1)], "nextPageToken": "three"}),
            Reply(status=503),
        ],
    )
    monkeypatch.setattr(google, "list_calendars", adapter.list_calendars)
    assert (await client.post(BASE + "/scan")).status_code == 503
    assert len(calls) == 3 and await catalog(client) == before
    async with app.state.session_factory() as db:
        c = await db.scalar(select(CalendarConnection))
        key = app.state.settings.google_calendar_credential_encryption_key.get_secret_value()
        assert SecretCipher(key).decrypt(c.encrypted_refresh_token) == rotated


async def test_reconciliation_halfway_flush_rollback(client, app, google, monkeypatch):
    await connect(client)
    before = await catalog(client)
    real = service.reconcile

    async def broken(db, connection, calendars):
        await real(db, connection, calendars[:1])
        raise SQLAlchemyError("synthetic database failure")

    monkeypatch.setattr(service, "reconcile", broken)
    assert (await client.post(BASE + "/scan")).status_code == 503
    assert await catalog(client) == before


@pytest.mark.parametrize(
    "pages, count",
    [
        ([Reply({"items": [], "nextPageToken": "two"}), Reply({"items": [entry(0)]})], 1),
        ([Reply({"items": [entry(0)], "nextPageToken": "two"}), Reply({"items": [entry(0)]})], 1),
    ],
)
async def test_empty_continuation_and_identical_duplicate(monkeypatch, pages, count):
    adapter, calls = paged_adapter(monkeypatch, pages)
    assert len(await adapter.list_calendars("synthetic")) == count
    assert len(calls) == 2


@pytest.mark.parametrize("token", ["", 3, [], {}, "x" * 4097])
async def test_malformed_continuation_fails_closed(monkeypatch, token):
    adapter, _ = paged_adapter(monkeypatch, [Reply({"items": [], "nextPageToken": token})])
    with pytest.raises(ProviderError, match="MALFORMED_RESPONSE"):
        await adapter.list_calendars("synthetic")


async def test_pagination_bound_and_conflicting_duplicate(monkeypatch):
    adapter, calls = paged_adapter(
        monkeypatch, [Reply({"items": [], "nextPageToken": str(i)}) for i in range(1001)]
    )
    with pytest.raises(ProviderError, match="MALFORMED_RESPONSE"):
        await adapter.list_calendars("synthetic")
    assert len(calls) == 1000
    adapter, _ = paged_adapter(
        monkeypatch,
        [
            Reply({"items": [entry(0)], "nextPageToken": "two"}),
            Reply({"items": [{**entry(0), "summary": "changed mid-scan"}]}),
        ],
    )
    with pytest.raises(ProviderError, match="MALFORMED_RESPONSE"):
        await adapter.list_calendars("synthetic")


async def test_stale_switch_confirmation_after_assignment_change(client, google):
    state = await connect(client)
    tech = await technician(client)
    cal = (await catalog(client))[0]
    await client.put(f"/api/technicians/{tech['id']}/calendar", json={"calendar_id": cal["id"]})
    payload = {
        "mode": "SWITCH",
        "confirm_replace": True,
        "expected_connection_id": state["id"],
        "expected_generation": state["generation"],
    }
    if "impact_version" in state:
        payload["expected_impact_version"] = state["impact_version"]
    response = await client.post(BASE + "/start", json=payload)
    assert response.status_code == 409


async def test_pending_switch_rejects_changed_impact(client, google):
    state = await connect(client)
    url = await begin(client, "SWITCH", True)
    tech = await technician(client)
    cal = (await catalog(client))[0]
    await client.put(f"/api/technicians/{tech['id']}/calendar", json={"calendar_id": cal["id"]})
    google.calendars[0] = replace(google.calendars[0], provider_id="second-account")
    assert (await client.get(url)).headers["location"].endswith("error")
    assert (await client.get(BASE)).json()["id"] == state["id"]


async def test_quota_403_is_retryable_not_scope_revocation(monkeypatch):
    adapter, _ = paged_adapter(
        monkeypatch,
        [
            Reply(
                {"error": {"errors": [{"reason": "rateLimitExceeded"}]}},
                403,
                {"Retry-After": "300"},
            )
        ],
    )
    with pytest.raises(ProviderError, match="RATE_LIMITED") as exc:
        await adapter.list_calendars("synthetic")
    assert exc.value.retry_after == 300


async def test_revoke_400_only_invalid_token_is_idempotent(monkeypatch):
    import requests

    from hub.google_calendar.provider import GoogleCalendarProvider
    from tests.test_google_calendar import real_settings

    adapter = GoogleCalendarProvider(real_settings())
    monkeypatch.setattr(
        requests.Session, "post", lambda *a, **kw: Reply({"error": "invalid_client"}, 400)
    )
    with pytest.raises(ProviderError):
        await adapter.revoke_credentials("synthetic")


@pytest.mark.parametrize(
    "namespace", ["google.auth", "google.oauth2", "requests_oauthlib", "oauthlib", "urllib3"]
)
async def test_late_sdk_logger_does_not_emit_secrets(caplog, namespace):
    import logging

    from hub.google_calendar.provider import GoogleCalendarProvider
    from tests.test_google_calendar import real_settings

    GoogleCalendarProvider(real_settings())
    with caplog.at_level(logging.DEBUG):
        logging.getLogger(namespace + ".audit_late_child").warning("audit-secret-marker")
    assert "audit-secret-marker" not in caplog.text


async def test_google_lock_owners_do_not_exhaust_transaction_pool(client, app, google):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from hub.telegram.locks import advisory_guard

    await connect(client)
    original_engine, original_factory = app.state.engine, app.state.session_factory
    limited = create_async_engine(
        original_engine.url, pool_size=2, max_overflow=0, pool_timeout=0.3
    )
    app.state.engine = limited
    app.state.session_factory = async_sessionmaker(limited, expire_on_commit=False)
    # Baseline uses the same pool for both long-lived Google lock owners and SQL work.
    lock_engine = getattr(app.state, "google_lock_engine", limited)
    try:
        async with advisory_guard(lock_engine, "google-lifecycle", 0):
            async with advisory_guard(lock_engine, "google-scan", 0):
                response = await client.get(BASE)
                assert response.status_code == 200
    finally:
        app.state.engine, app.state.session_factory = original_engine, original_factory
        await limited.dispose()


@pytest.mark.parametrize(
    "operation", ["disconnect", "reconnect", "switch", "exclude", "restore", "assign"]
)
async def test_scan_concurrent_catalog_mutations(client, app, google, monkeypatch, operation):
    await connect(client)
    cal = next(c for c in await catalog(client) if c["name"] == "GA - Atlanta")
    tech = await technician(client)
    if operation == "restore":
        await client.post(
            f"/api/calendars/{cal['id']}/exclude",
            json={"confirmation": "EXCLUDE", "expected_assigned_technician_id": None},
        )
    started, release = asyncio.Event(), asyncio.Event()
    original = google.list_calendars
    scan_task = None

    async def blocked(token):
        # Only the first listing (scan) waits; OAuth listings can proceed.
        if not started.is_set():
            snapshot = list(google.calendars)
            started.set()
            await release.wait()
            return snapshot
        return await original(token)

    monkeypatch.setattr(google, "list_calendars", blocked)
    scan_task = asyncio.create_task(client.post(BASE + "/scan"))
    try:
        await asyncio.wait_for(started.wait(), 3)
        if operation == "disconnect":
            assert (await disconnect(client)).status_code == 204
        elif operation in {"reconnect", "switch"}:
            if operation == "switch":
                google.calendars[0] = replace(google.calendars[0], provider_id="alternate-primary")
            await connect(client, operation.upper(), operation == "switch")
        elif operation == "assign":
            assert (
                await client.put(
                    f"/api/technicians/{tech['id']}/calendar", json={"calendar_id": cal["id"]}
                )
            ).status_code == 200
        else:
            options = (
                {"json": {"confirmation": "EXCLUDE", "expected_assigned_technician_id": None}}
                if operation == "exclude"
                else {}
            )
            assert (
                await client.post(f"/api/calendars/{cal['id']}/{operation}", **options)
            ).status_code == 204
    finally:
        release.set()
    response = await asyncio.wait_for(scan_task, 5)
    assert response.status_code == (
        409 if operation in {"disconnect", "reconnect", "switch"} else 200
    )
    async with app.state.session_factory() as db:
        row = await db.get(Calendar, UUID(cal["id"]))
        assert row.availability == (
            "UNAVAILABLE" if operation in {"disconnect", "switch"} else "AVAILABLE"
        )
        assert bool(row.excluded_at) == (operation == "exclude")
        active = await db.scalar(
            select(CalendarAssignment).where(
                CalendarAssignment.calendar_id == row.id, CalendarAssignment.is_active.is_(True)
            )
        )
        assert bool(active) == (operation == "assign")


@pytest.mark.parametrize("different_snapshot", [False, True])
async def test_simultaneous_scan_rejects_second_snapshot(
    client, google, monkeypatch, different_snapshot
):
    await connect(client)
    before = await catalog(client)
    started, release = asyncio.Event(), asyncio.Event()

    async def listing(token):
        snapshot = list(google.calendars)
        started.set()
        await release.wait()
        return snapshot

    monkeypatch.setattr(google, "list_calendars", listing)
    task = asyncio.create_task(client.post(BASE + "/scan"))
    await asyncio.wait_for(started.wait(), 3)
    try:
        if different_snapshot:
            google.calendars = []
        assert (await client.post(BASE + "/scan")).status_code == 409
    finally:
        release.set()
    assert (await task).status_code == 200
    assert {c["id"] for c in await catalog(client)} == {c["id"] for c in before}
    assert all(c["availability"] == "AVAILABLE" for c in await catalog(client))


@pytest.mark.parametrize("operation", ["unassign", "exclude", "unavailable", "delete", "remove"])
async def test_assignment_concurrent_removal_final_db_invariants(client, app, google, operation):
    await connect(client)
    tech = await technician(client)
    rows = await catalog(client)
    a, b = rows[:2]
    await client.put(f"/api/technicians/{tech['id']}/calendar", json={"calendar_id": a["id"]})
    assign = client.put(f"/api/technicians/{tech['id']}/calendar", json={"calendar_id": b["id"]})
    if operation == "unassign":
        other = client.delete(f"/api/technicians/{tech['id']}/calendar")
    elif operation == "exclude":
        other = client.post(
            f"/api/calendars/{b['id']}/exclude",
            json={"confirmation": "EXCLUDE", "expected_assigned_technician_id": None},
        )
    elif operation == "remove":
        other = client.post(
            f"/api/calendars/{a['id']}/exclude",
            json={"confirmation": "EXCLUDE", "expected_assigned_technician_id": tech["id"]},
        )
    elif operation == "delete":
        other = client.request(
            "DELETE",
            f"/api/technicians/{tech['id']}",
            json={"confirmation": "DELETE", "expected_record_version": tech["record_version"]},
        )
    else:
        google.calendars = []
        other = client.post(BASE + "/scan")
    responses = await asyncio.wait_for(asyncio.gather(assign, other), 8)
    assert all(r.status_code in {200, 204, 404, 409} for r in responses), [
        r.text for r in responses
    ]
    async with app.state.session_factory() as db:
        active = (
            await db.scalars(
                select(CalendarAssignment).where(CalendarAssignment.is_active.is_(True))
            )
        ).all()
        assert len({a.technician_id for a in active}) == len(active)
        assert len({a.calendar_id for a in active}) == len(active)
        for assignment in active:
            calendar = await db.get(Calendar, assignment.calendar_id)
            assert calendar.excluded_at is None
        if operation == "delete":
            assert responses[1].status_code == 409
            assert len(active) == 1


async def test_reappearing_renamed_exclusion_survives_reconnect(client, app, google):
    await connect(client)
    before = await catalog(client)
    cal = next(c for c in before if c["name"] == "GA - Atlanta")
    tech = await technician(client)
    await client.put(f"/api/technicians/{tech['id']}/calendar", json={"calendar_id": cal["id"]})
    original = list(google.calendars)
    google.calendars = [original[0]]
    await client.post(BASE + "/scan")
    google.calendars = list(reversed(original))
    await client.post(BASE + "/scan")
    returned = next(c for c in await catalog(client) if c["id"] == cal["id"])
    assert (
        returned["availability"] == "AVAILABLE"
        and returned["assigned_technician"]["id"] == tech["id"]
    )
    await client.post(
        f"/api/calendars/{cal['id']}/exclude",
        json={"confirmation": "EXCLUDE", "expected_assigned_technician_id": tech["id"]},
    )
    google.calendars = [
        replace(c, name="Renamed") if c.provider_id == "test-atlanta" else c for c in original
    ]
    await connect(client, "RECONNECT")
    returned = next(c for c in await catalog(client) if c["id"] == cal["id"])
    assert (
        returned["name"] == "Renamed"
        and returned["excluded_at"]
        and not returned["assigned_technician"]
    )
    assert (
        await client.put(f"/api/technicians/{tech['id']}/calendar", json={"calendar_id": cal["id"]})
    ).status_code == 409
    history = (await client.get(f"/api/technicians/{tech['id']}/calendar-assignments")).json()
    assert len(history) == 1 and not history[0]["is_active"]


async def test_switch_missing_token_cannot_reuse_old_account(client, app, google):
    old = await connect(client)
    google.grant = replace(google.grant, refresh_token=None)
    google.calendars[0] = replace(google.calendars[0], provider_id="other-account")
    assert (
        (await client.get(await begin(client, "SWITCH", True)))
        .headers["location"]
        .endswith("error")
    )
    assert (await client.get(BASE)).json()["id"] == old["id"]
    async with app.state.session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(CalendarConnection)) == 1


async def test_callback_commit_failure_preserves_old_account_and_burns_state(
    client, app, google, monkeypatch
):
    old = await connect(client)
    before = await catalog(client)
    url = await begin(client, "SWITCH", True)
    google.calendars[0] = replace(google.calendars[0], provider_id="second")
    original = AsyncSession.commit

    async def failing_commit(db):
        if any(
            isinstance(row, AuditEvent) and row.action == "google.connection.completed"
            for row in db.new
        ):
            raise SQLAlchemyError("audit-token-shaped-database-error")
        await original(db)

    monkeypatch.setattr(AsyncSession, "commit", failing_commit)
    assert (await client.get(url)).headers["location"].endswith("error")
    assert (await client.get(BASE)).json()["id"] == old["id"]
    assert await catalog(client) == before
    assert (await client.get(url)).headers["location"].endswith("error")
    assert google.calls.count("exchange") == 2  # initial connect plus failed switch, no replay


async def test_switch_revoke_failure_does_not_undo_committed_identity(
    client, app, google, monkeypatch
):
    old = await connect(client)
    google.calendars[0] = replace(google.calendars[0], provider_id="second")

    async def unreachable(token):
        raise TimeoutError("synthetic-secret")

    monkeypatch.setattr(google, "revoke_credentials", unreachable)
    new = await connect(client, "SWITCH", True)
    assert new["id"] != old["id"]
    async with app.state.session_factory() as db:
        previous = await db.get(CalendarConnection, UUID(old["id"]))
        assert previous.encrypted_refresh_token is None and not previous.is_current
        assert await db.scalar(
            select(AuditEvent).where(AuditEvent.action == "google.revocation.failed")
        )


@pytest.mark.parametrize("invalid", ["expired", "revoked", "inactive", "logout"])
async def test_callback_invalid_session_never_exchanges(client, app, google, invalid):
    from hub.auth.models import Manager, ManagerSession

    url = await begin(client)
    if invalid == "logout":
        assert (await client.post("/api/auth/logout")).status_code == 204
    else:
        async with app.state.session_factory() as db:
            statement = (
                update(Manager).values(is_active=False)
                if invalid == "inactive"
                else update(ManagerSession).values(
                    **(
                        {"expires_at": now() - timedelta(seconds=1)}
                        if invalid == "expired"
                        else {"revoked_at": now()}
                    )
                )
            )
            await db.execute(statement)
            await db.commit()
    assert (await client.get(url)).headers["location"].endswith("error")
    assert "exchange" not in google.calls
    async with app.state.session_factory() as db:
        assert not await db.scalar(
            select(AuditEvent).where(AuditEvent.action == "google.connection.completed")
        )


async def test_oauth_two_attempts_reverse_order_old_attempt_burned(client, app, google):
    first = await begin(client)
    second = await begin(client)
    assert first != second
    assert (await client.get(second)).headers["location"].endswith("connected")
    assert (await client.get(first)).headers["location"].endswith("error")
    assert google.calls.count("exchange") == 1


async def test_provider_secrets_redacted_in_callback_scan_logs_audit(client, app, google, caplog):
    secret = "audit-refresh-code-client-state-calendar-email@example.invalid-raw-json"
    await connect(client)
    google.error = RuntimeError(secret)
    response = await client.post(BASE + "/scan")
    assert response.status_code == 503 and secret not in response.text
    assert (
        (await client.get(await begin(client, "RECONNECT"))).headers["location"].endswith("error")
    )
    async with app.state.session_factory() as db:
        events = (await db.scalars(select(AuditEvent))).all()
        assert secret not in str([vars(e) for e in events])
        assert all(e.actor_id and e.created_at for e in events)
    assert secret not in caplog.text


@pytest.mark.parametrize("value", ["120", "invalid", str(10**30)])
async def test_retry_after_persisted_across_provider_recreation(
    client, app, google, monkeypatch, value
):
    from hub.google_calendar.fake import FakeCalendarProvider

    await connect(client)
    adapter, _ = paged_adapter(monkeypatch, [Reply(status=429, headers={"Retry-After": value})])
    monkeypatch.setattr(google, "list_calendars", adapter.list_calendars)
    assert (await client.post(BASE + "/scan")).status_code == 429
    replacement = FakeCalendarProvider()
    app.state.google_provider = replacement
    assert (await client.post(BASE + "/scan")).status_code == 429
    assert not replacement.calls
    async with app.state.session_factory() as db:
        await db.execute(update(CalendarConnection).values(retry_at=now() - timedelta(seconds=1)))
        await db.commit()
    assert (await client.post(BASE + "/scan")).status_code == 200


def test_pkce_actual_challenge_derivation_and_state_entropy():
    import base64
    import hashlib
    from urllib.parse import parse_qs, urlsplit

    from hub.google_calendar.provider import GoogleCalendarProvider
    from tests.test_google_calendar import real_settings

    adapter = GoogleCalendarProvider(real_settings())
    one, two = (
        adapter.build_authorization_url("synthetic-state"),
        adapter.build_authorization_url("synthetic-state"),
    )
    assert one.verifier != two.verifier and len(one.verifier) == 128
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(one.verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    assert parse_qs(urlsplit(one.url).query)["code_challenge"] == [expected]
    assert one.verifier not in one.url


@pytest.mark.parametrize(
    "title",
    [
        "x" * 10000,
        "emoji \U0001f527 unicode \u00e9 \u05d0",
        "<script>alert(1)</script>",
        "[link](javascript:evil)",
        "a\x00\r\nb",
    ],
)
def test_metadata_normalization_is_bounded_plain_text(title):
    from hub.google_calendar.provider import GoogleCalendarProvider

    value = GoogleCalendarProvider._normalize({**entry(0), "summary": title})
    assert len(value.name) <= 150
    assert all(ord(c) >= 32 for c in value.name)


async def test_failed_exchange_state_cannot_be_replayed(client, google):
    url = await begin(client)
    google.error = ProviderError("PROVIDER_TEMPORARY_ERROR")
    assert (await client.get(url)).headers["location"].endswith("error")
    google.error = None
    assert (await client.get(url)).headers["location"].endswith("error")
    assert google.calls.count("exchange") == 1


@pytest.mark.parametrize(
    "environment,host",
    [("production", "127.0.0.1"), ("development", "127.0.0.1"), ("test", "remote.invalid")],
)
def test_fake_provider_startup_cannot_escape_isolated_test_environment(environment, host):
    from cryptography.fernet import Fernet
    from pydantic import ValidationError

    from hub.core.config import Settings

    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            app_env=environment,
            cookie_secure=True,
            allowed_origins=["https://hub.example.invalid"],
            google_mode="fake",
            database_url=f"postgresql+asyncpg://hub:test@{host}:5439/technician_hub_test",
            google_calendar_credential_encryption_key=Fernet.generate_key().decode(),
        )


async def test_callback_different_manager_and_logout_new_login(client, app, google):
    import secrets

    from httpx import ASGITransport, AsyncClient

    from hub.auth.service import create_manager

    url = await begin(client)
    password = secrets.token_urlsafe(24)
    async with app.state.session_factory() as db:
        other = await create_manager(db, "second-audit-manager", password)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://127.0.0.1:3000",
        headers={"Origin": "http://127.0.0.1:3000", "X-Hub-Request": "1"},
    ) as second:
        assert (
            await second.post(
                "/api/auth/login", json={"username": other.username, "password": password}
            )
        ).status_code == 200
        assert (await second.get(url)).headers["location"].endswith("error")
    assert (await client.get(url)).headers["location"].endswith("connected")


async def test_retry_http_date_rounds_up(monkeypatch):
    from datetime import UTC, datetime
    from email.utils import format_datetime

    import hub.google_calendar.provider as module

    class Fixed(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 17, 0, 0, 0, 500000, tzinfo=UTC)

    monkeypatch.setattr(module, "datetime", Fixed)
    with pytest.raises(ProviderError) as raised:
        module.GoogleCalendarProvider._check(
            Reply(
                status=429,
                headers={
                    "Retry-After": format_datetime(datetime(2026, 9, 17, 0, 2, 0, tzinfo=UTC))
                },
            )
        )
    assert raised.value.retry_after == 120


async def test_refresh_lifecycle_serializes_reconnect_without_sql_transaction(
    client, app, google, monkeypatch
):
    from sqlalchemy import text

    await connect(client)
    url = await begin(client, "RECONNECT")
    started, release = asyncio.Event(), asyncio.Event()
    original = google.refresh_credentials

    async def refresh(token):
        started.set()
        await release.wait()
        return await original(token)

    monkeypatch.setattr(google, "refresh_credentials", refresh)
    scan = asyncio.create_task(client.post(BASE + "/scan"))
    await asyncio.wait_for(started.wait(), 3)
    before = google.calls.count("exchange")
    reconnect = asyncio.create_task(client.get(url))
    try:
        await asyncio.sleep(0.1)
        assert google.calls.count("exchange") == before
        async with app.state.session_factory() as db:
            assert (
                await db.scalar(
                    text(
                        "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() "
                        "AND state='idle in transaction'"
                    )
                )
                == 0
            )
    finally:
        release.set()
    responses = await asyncio.wait_for(asyncio.gather(scan, reconnect), 5)
    assert responses[0].status_code in {200, 409}
    assert responses[1].headers["location"].endswith("connected")


async def test_thread_cancellation_waits_for_network_completion(monkeypatch):
    import threading

    from hub.google_calendar.provider import GoogleCalendarProvider
    from tests.test_google_calendar import real_settings

    started, release = threading.Event(), threading.Event()

    def blocked(token):
        started.set()
        assert release.wait(3)
        return []

    adapter = GoogleCalendarProvider(real_settings())
    monkeypatch.setattr(adapter, "_list", blocked)
    task = asyncio.create_task(adapter.list_calendars("synthetic"))
    while not started.is_set():
        await asyncio.sleep(0.01)
    task.cancel()
    try:
        await asyncio.sleep(0.02)
        assert not task.done()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_refresh_transport_disables_redirects_and_preserves_retry_after(monkeypatch):
    from hub.google_calendar import provider as module
    from tests.test_google_calendar import real_settings

    def transport(self, *args, **kwargs):
        assert kwargs["allow_redirects"] is False and kwargs["timeout"] == (5, 15)
        return SimpleNamespace(status=429, headers={"Retry-After": "7200"}, data=b"{}")

    def refresh(self, request):
        request("https://oauth2.googleapis.com/token", method="POST")

    monkeypatch.setattr(module.Request, "__call__", transport)
    monkeypatch.setattr(module.Credentials, "refresh", refresh)
    with pytest.raises(ProviderError, match="RATE_LIMITED") as exc:
        await module.GoogleCalendarProvider(real_settings()).refresh_credentials("synthetic")
    assert exc.value.retry_after == 7200


async def test_pending_oauth_cannot_reconnect_after_disconnect(client, app, google):
    await connect(client)
    url = await begin(client, "RECONNECT")
    before = google.calls.count("exchange")
    assert (await disconnect(client)).status_code == 204
    assert (await client.get(url)).headers["location"].endswith("error")
    assert google.calls.count("exchange") == before
    async with app.state.session_factory() as db:
        value = await db.scalar(select(CalendarConnection))
        assert value.status == "DISCONNECTED" and value.encrypted_refresh_token is None


async def test_disconnect_waiting_for_reconnect_requires_fresh_confirmation(
    client, app, google, monkeypatch
):
    state = await connect(client)
    url = await begin(client, "RECONNECT")
    started, release = asyncio.Event(), asyncio.Event()
    original = google.exchange_authorization_code

    async def blocked(code, verifier):
        started.set()
        await release.wait()
        return await original(code, verifier)

    monkeypatch.setattr(google, "exchange_authorization_code", blocked)
    callback = asyncio.create_task(client.get(url))
    await asyncio.wait_for(started.wait(), 3)
    removal = asyncio.create_task(
        client.post(
            BASE + "/disconnect",
            json={
                "confirmation": "DISCONNECT",
                "expected_connection_id": state["id"],
                "expected_generation": state["generation"],
            },
        )
    )
    try:
        await asyncio.sleep(0.1)
        assert not removal.done()
    finally:
        release.set()
    assert (await callback).headers["location"].endswith("connected")
    assert (await removal).status_code == 409  # Never disconnect an unconfirmed new generation.
    assert (await disconnect(client)).status_code == 204
    async with app.state.session_factory() as db:
        assert (await db.scalar(select(CalendarConnection))).encrypted_refresh_token is None


async def test_two_sessions_switch_concurrently_only_one_account_activates(
    client, app, google, credentials
):
    from httpx import ASGITransport, AsyncClient

    await connect(client)
    first = await begin(client, "SWITCH", True)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://127.0.0.1:3000",
        headers={"Origin": "http://127.0.0.1:3000", "X-Hub-Request": "1"},
    ) as second:
        login = await second.post(
            "/api/auth/login",
            json={"username": credentials["username"], "password": credentials["password"]},
        )
        second.headers["X-CSRF-Token"] = login.json()["csrf_token"]
        other = await begin(second, "SWITCH", True)
        google.calendars[0] = replace(google.calendars[0], provider_id="second-account")
        responses = await asyncio.gather(client.get(first), second.get(other))
    assert sorted(r.headers["location"] for r in responses) == [
        "/calendars?google=connected",
        "/calendars?google=error",
    ]
    async with app.state.session_factory() as db:
        active = (
            await db.scalars(
                select(CalendarConnection).where(CalendarConnection.is_current.is_(True))
            )
        ).all()
        assert len(active) == 1 and active[0].generation == 1
        assert active[0].account_key == "second-account"


@pytest.mark.parametrize("secure", [False, True])
async def test_oauth_start_reissues_same_session_cookie_lax_without_extending_expiry(
    client, app, google, secure
):
    from http.cookies import SimpleCookie

    from hub.auth.middleware import COOKIE_NAME
    from hub.auth.models import ManagerSession
    from hub.auth.security import digest

    token = client.cookies.get(COOKIE_NAME)
    async with app.state.session_factory() as db:
        record = await db.scalar(
            select(ManagerSession).where(ManagerSession.token_hash == digest(token))
        )
        remaining = int((record.expires_at - now()).total_seconds())
    app.state.settings.cookie_secure = secure
    response = await client.post(BASE + "/start", json={})
    assert response.status_code == 200
    cookie = SimpleCookie(response.headers["set-cookie"])[COOKIE_NAME]
    assert cookie.value == token and cookie["samesite"] == "lax" and cookie["httponly"]
    assert bool(cookie["secure"]) == secure
    assert 0 < int(cookie["max-age"]) <= remaining
