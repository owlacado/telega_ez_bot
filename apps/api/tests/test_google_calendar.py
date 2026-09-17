import asyncio
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import pytest
import requests
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr, ValidationError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from hub.audit.models import AuditEvent
from hub.auth.security import digest, now
from hub.calendars.models import Calendar, CalendarAssignment
from hub.core.config import Settings
from hub.core.secrets import SecretCipher
from hub.google_calendar.fake import FakeCalendarProvider
from hub.google_calendar.models import CalendarConnection, GoogleOAuthAttempt
from hub.google_calendar.provider import GoogleCalendarProvider
from hub.google_calendar.types import SCOPE, DiscoveredCalendar, ProviderError, TokenGrant

BASE = "/api/calendar-connections/google"


@pytest.fixture
async def google(app, client):
    app.state.settings.google_mode = "fake"
    app.state.settings.google_calendar_credential_encryption_key = SecretStr(
        Fernet.generate_key().decode()
    )
    fake = FakeCalendarProvider()
    app.state.google_provider = fake
    return fake


async def begin(client, mode="CONNECT", confirm=False):
    status = (await client.get(BASE)).json()
    response = await client.post(
        BASE + "/start",
        json={
            "mode": mode,
            "expected_connection_id": status["id"],
            "expected_generation": status["generation"],
            "confirm_replace": confirm,
            "expected_impact_version": status.get("impact_version"),
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["authorization_url"]


async def connect(client, mode="CONNECT", confirm=False):
    response = await client.get(await begin(client, mode, confirm))
    assert response.status_code == 303
    assert response.headers["location"] == "/calendars?google=connected"
    return (await client.get(BASE)).json()


async def catalog(client):
    return (await client.get("/api/calendars")).json()


async def technician(client, name="Test"):
    response = await client.post(
        "/api/technicians", json={"first_name": name, "last_name": "Google"}
    )
    assert response.status_code == 201
    return response.json()


async def disconnect(client):
    value = (await client.get(BASE)).json()
    return await client.post(
        BASE + "/disconnect",
        json={
            "confirmation": "DISCONNECT",
            "expected_connection_id": value["id"],
            "expected_generation": value["generation"],
        },
    )


async def test_start_encryption_binding_and_single_use(client, app, google):
    url = await begin(client)
    state = parse_qs(urlsplit(url).query)["state"][0]
    async with app.state.session_factory() as db:
        attempt = await db.scalar(select(GoogleOAuthAttempt))
        assert attempt.state_hash == digest(state) and state != attempt.state_hash
        assert "fake-pkce" not in attempt.encrypted_verifier
        assert attempt.expires_at < now() + timedelta(minutes=11)
        assert attempt.session_id and attempt.manager_id
    assert (await client.get(url)).headers["location"].endswith("connected")
    assert (await client.get(url)).headers["location"].endswith("error")
    assert google.calls.count("exchange") == 1
    async with app.state.session_factory() as db:
        connection = await db.scalar(select(CalendarConnection))
        assert connection.encrypted_refresh_token.startswith("v1:")
        assert google.grant.refresh_token not in connection.encrypted_refresh_token
        assert (
            SecretCipher(
                app.state.settings.google_calendar_credential_encryption_key.get_secret_value()
            ).decrypt(connection.encrypted_refresh_token)
            == google.grant.refresh_token
        )
        attempt = await db.scalar(select(GoogleOAuthAttempt))
        assert attempt.consumed_at and attempt.encrypted_verifier is None
        events = (await db.scalars(select(AuditEvent))).all()
        assert {"google.connection.initiated", "google.connection.completed"} <= {
            e.action for e in events
        }
        assert "fake-code" not in str([vars(e) for e in events])
    public = (await client.get(BASE)).text + (await client.get("/api/calendars")).text
    assert all(
        secret not in public
        for secret in (
            "fake-access-only",
            "fake-refresh-only",
            "encrypted_refresh_token",
            "account_key",
        )
    )


@pytest.mark.parametrize(
    "mutation", ["expired", "random", "missing", "error", "duplicate", "no_state"]
)
async def test_bad_callback(client, app, google, mutation):
    url = await begin(client)
    if mutation == "expired":
        async with app.state.session_factory() as db:
            await db.execute(
                update(GoogleOAuthAttempt).values(expires_at=now() - timedelta(seconds=1))
            )
            await db.commit()
    elif mutation == "random":
        url = url.replace("state=", "state=X")
    elif mutation == "missing":
        url = url.split("&code=")[0]
    elif mutation == "error":
        url += "&error=access_denied"
    elif mutation == "duplicate":
        url += "&code=another-code"
    else:
        url = BASE + "/callback?code=fake-code"
    response = await client.get(url)
    assert response.headers["location"] == "/calendars?google=error"
    assert "exchange" not in google.calls
    assert (await client.get(BASE)).json()["id"] is None


async def test_wrong_manager_session_cannot_consume(client, app, google, credentials):
    url = await begin(client)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://127.0.0.1:3000",
        headers={"Origin": "http://127.0.0.1:3000", "X-Hub-Request": "1"},
    ) as other:
        login = await other.post(
            "/api/auth/login",
            json={"username": credentials["username"], "password": credentials["password"]},
        )
        assert login.status_code == 200
        assert (await other.get(url)).headers["location"].endswith("error")
    assert (await client.get(url)).headers["location"].endswith("connected")


async def test_duplicate_callbacks_concurrent(client, google):
    url = await begin(client)
    responses = await asyncio.gather(client.get(url), client.get(url))
    assert sorted(r.headers["location"] for r in responses) == [
        "/calendars?google=connected",
        "/calendars?google=error",
    ]
    assert google.calls.count("exchange") == 1


async def test_complete_idempotent_reconciliation_and_missing_assignment(client, google):
    await connect(client)
    before = {c["name"]: c for c in await catalog(client)}
    tech = await technician(client)
    atlanta = before["GA - Atlanta"]
    assert (
        await client.put(
            f"/api/technicians/{tech['id']}/calendar", json={"calendar_id": atlanta["id"]}
        )
    ).status_code == 200
    assert (await client.post(BASE + "/scan")).json()["discovered"] == 3
    assert {c["id"] for c in await catalog(client)} == {c["id"] for c in before.values()}
    google.calendars = [
        google.calendars[0],
        replace(google.calendars[2], name="Renamed"),
        DiscoveredCalendar("new-id", "New"),
    ]
    assert (await client.post(BASE + "/scan")).status_code == 200
    after = {c["name"]: c for c in await catalog(client)}
    assert len(after) == 4
    assert after["Renamed"]["id"] == before["GA - Savannah"]["id"]
    assert after["GA - Atlanta"]["availability"] == "UNAVAILABLE"
    value = (await client.get(f"/api/technicians/{tech['id']}")).json()["calendar"]
    assert value["id"] == atlanta["id"] and value["availability"] == "UNAVAILABLE"


async def test_exclude_confirmation_rescan_restore_and_history(client, google):
    await connect(client)
    calendar = next(c for c in await catalog(client) if c["name"] == "GA - Atlanta")
    tech = await technician(client)
    await client.put(
        f"/api/technicians/{tech['id']}/calendar", json={"calendar_id": calendar["id"]}
    )
    path = f"/api/calendars/{calendar['id']}/exclude"
    assert (await client.post(path, json={})).status_code == 422
    assert (
        await client.post(
            path, json={"confirmation": "EXCLUDE", "expected_assigned_technician_id": None}
        )
    ).status_code == 409
    assert (
        await client.post(
            path, json={"confirmation": "EXCLUDE", "expected_assigned_technician_id": tech["id"]}
        )
    ).status_code == 204
    assert (await client.get(f"/api/technicians/{tech['id']}")).json()["calendar"] is None
    history = (await client.get(f"/api/technicians/{tech['id']}/calendar-assignments")).json()
    assert len(history) == 1 and not history[0]["is_active"]
    await client.post(BASE + "/scan")
    assert next(c for c in await catalog(client) if c["id"] == calendar["id"])["excluded_at"]
    assert (
        await client.put(
            f"/api/technicians/{tech['id']}/calendar", json={"calendar_id": calendar["id"]}
        )
    ).status_code == 409
    assert (await client.post(f"/api/calendars/{calendar['id']}/restore")).status_code == 204
    assert (
        next(c for c in await catalog(client) if c["id"] == calendar["id"])["excluded_at"] is None
    )
    assert "revoke" not in google.calls


async def test_disconnect_reconnect_and_missing_refresh(client, app, google):
    first = await connect(client)
    ids = {c["id"] for c in await catalog(client)}
    google.grant = TokenGrant("second-access", None)
    second = await connect(client, "RECONNECT")
    assert first["id"] == second["id"]
    async with app.state.session_factory() as db:
        assert (await db.scalar(select(CalendarConnection))).encrypted_refresh_token
    assert (await disconnect(client)).status_code == 204
    assert "revoke" in google.calls
    assert all(c["availability"] == "UNAVAILABLE" for c in await catalog(client))
    assert (await client.post(BASE + "/scan")).status_code == 409
    response = await client.get(await begin(client, "RECONNECT"))
    assert response.headers["location"].endswith("error")
    google.grant = TokenGrant("third-access", "third-refresh")
    await connect(client, "RECONNECT")
    assert {c["id"] for c in await catalog(client)} == ids
    assert all(c["availability"] == "AVAILABLE" for c in await catalog(client))


async def test_account_switch_requires_confirmation_and_separates_identity(client, google):
    old = await connect(client)
    old_ids = {c["id"] for c in await catalog(client)}
    google.calendars[0] = replace(google.calendars[0], provider_id="other-primary")
    assert (
        (await client.get(await begin(client, "RECONNECT"))).headers["location"].endswith("error")
    )
    assert (await client.get(BASE)).json()["id"] == old["id"]
    bad = await client.post(
        BASE + "/start",
        json={
            "mode": "SWITCH",
            "expected_connection_id": old["id"],
            "expected_generation": old["generation"],
        },
    )
    assert bad.status_code == 409
    new = await connect(client, "SWITCH", True)
    assert new["id"] != old["id"]
    rows = await catalog(client)
    assert len(rows) == 6  # Identical provider IDs in different account context never merge.
    assert all(c["availability"] == "UNAVAILABLE" for c in rows if c["id"] in old_ids)
    google.calendars[0] = replace(google.calendars[0], provider_id="test-primary")
    restored = await connect(client, "SWITCH", True)
    assert restored["id"] == old["id"]
    assert len(await catalog(client)) == 6


@pytest.mark.parametrize(
    "failure",
    [
        ProviderError("REAUTH_REQUIRED"),
        ProviderError("SCOPE_REQUIRED"),
        ProviderError("RATE_LIMITED", 120),
        ProviderError("PROVIDER_TEMPORARY_ERROR"),
        TimeoutError("access-token-secret"),
        RuntimeError("refresh-token-secret"),
    ],
)
async def test_provider_failure_safe_catalog_preserved_and_backoff(client, google, failure):
    await connect(client)
    before = await catalog(client)
    google.error = failure
    response = await client.post(BASE + "/scan")
    assert response.status_code in {429, 503}
    assert "token-secret" not in response.text
    assert {c["id"] for c in await catalog(client)} == {c["id"] for c in before}
    calls = len(google.calls)
    assert (await client.post(BASE + "/scan")).status_code in {409, 429}
    assert len(google.calls) == calls
    if not isinstance(failure, ProviderError) or failure.code not in {
        "REAUTH_REQUIRED",
        "SCOPE_REQUIRED",
    }:
        assert await catalog(client) == before


@pytest.mark.parametrize("corruption", ["ciphertext", "key"])
async def test_corrupt_credential_fails_closed(client, app, google, corruption):
    await connect(client)
    if corruption == "key":
        app.state.settings.google_calendar_credential_encryption_key = SecretStr(
            Fernet.generate_key().decode()
        )
    else:
        async with app.state.session_factory() as db:
            await db.execute(update(CalendarConnection).values(encrypted_refresh_token="broken"))
            await db.commit()
    google.calls.clear()
    assert (await client.post(BASE + "/scan")).status_code == 503
    assert not google.calls
    assert (await client.get(BASE)).json()["status"] == "REAUTH_REQUIRED"


async def test_scans_concurrent_and_disconnect_during_fetch(client, google, monkeypatch):
    await connect(client)
    entered, release = asyncio.Event(), asyncio.Event()

    async def slow(access):
        entered.set()
        await release.wait()
        return google.calendars

    monkeypatch.setattr(google, "list_calendars", slow)
    first = asyncio.create_task(client.post(BASE + "/scan"))
    await asyncio.wait_for(entered.wait(), 5)
    assert (await client.post(BASE + "/scan")).status_code == 409
    assert (await disconnect(client)).status_code == 204
    release.set()
    assert (await first).status_code == 409
    assert (await client.get(BASE)).json()["status"] == "DISCONNECTED"
    assert all(c["availability"] == "UNAVAILABLE" for c in await catalog(client))


async def test_assignment_races_and_atomic_transfer(client, google):
    await connect(client)
    a, b = (await catalog(client))[:2]
    t1, t2 = await technician(client, "One"), await technician(client, "Two")
    responses = await asyncio.gather(
        *[
            client.put(f"/api/technicians/{t['id']}/calendar", json={"calendar_id": a["id"]})
            for t in (t1, t2)
        ]
    )
    assert sorted(r.status_code for r in responses) == [200, 409]
    winner = t1 if responses[0].status_code == 200 else t2
    loser = t2 if winner == t1 else t1
    assert (
        await client.put(f"/api/technicians/{winner['id']}/calendar", json={"calendar_id": b["id"]})
    ).status_code == 200
    history = (await client.get(f"/api/technicians/{winner['id']}/calendar-assignments")).json()
    assert sum(h["is_active"] for h in history) == 1 and len(history) == 2
    assert (
        await client.put(
            f"/api/calendars/{b['id']}/assignment",
            json={"technician_id": loser["id"], "expected_assigned_technician_id": winner["id"]},
        )
    ).status_code == 204
    assert (await client.get(f"/api/technicians/{winner['id']}")).json()["calendar"] is None
    assert (await client.get(f"/api/technicians/{loser['id']}")).json()["calendar"]["id"] == b["id"]


async def test_db_provider_identity_and_active_assignment_constraints(client, app, google):
    await connect(client)
    rows = await catalog(client)
    t1, t2 = await technician(client, "One"), await technician(client, "Two")
    async with app.state.session_factory() as db:
        original = await db.get(Calendar, UUID(rows[0]["id"]))
        db.add(
            Calendar(
                source="GOOGLE",
                name="Collision",
                provider_connection_id=original.provider_connection_id,
                provider_calendar_id=original.provider_calendar_id,
            )
        )
        with pytest.raises(IntegrityError):
            await db.commit()
    await client.put(f"/api/technicians/{t1['id']}/calendar", json={"calendar_id": rows[0]["id"]})
    for tech, cal in [(t1, rows[1]), (t2, rows[0])]:
        async with app.state.session_factory() as db:
            db.add(
                CalendarAssignment(
                    technician_id=UUID(tech["id"]),
                    calendar_id=UUID(cal["id"]),
                    calendar_name=cal["name"],
                )
            )
            with pytest.raises(IntegrityError):
                await db.commit()


@pytest.mark.parametrize(
    "path,method",
    [
        (BASE, "GET"),
        (BASE + "/start", "POST"),
        (BASE + "/scan", "POST"),
        (BASE + "/disconnect", "POST"),
        ("/api/calendars/00000000-0000-0000-0000-000000000001/exclude", "POST"),
        ("/api/calendars/00000000-0000-0000-0000-000000000001/restore", "POST"),
        ("/api/calendars/00000000-0000-0000-0000-000000000001/assignment", "PUT"),
    ],
)
async def test_all_google_routes_require_manager(anonymous, path, method):
    assert (await anonymous.request(method, path, json={})).status_code == 401


async def test_csrf_and_demo_production_guard(client, app, google):
    original = client.headers.pop("X-CSRF-Token")
    assert (await client.post(BASE + "/start", json={})).status_code == 403
    client.headers["X-CSRF-Token"] = original
    local = (await client.post("/api/calendars", json={"name": "Demo"})).json()
    app.state.settings.app_env = "production"
    assert await catalog(client) == []
    assert (await client.post("/api/calendars", json={"name": "Fake"})).status_code == 403
    assert (
        await client.request(
            "DELETE", f"/api/calendars/{local['id']}", json={"confirmation": "DELETE"}
        )
    ).status_code == 403


def real_settings():
    return Settings(
        _env_file=None,
        google_mode="real",
        google_client_id="test-client",
        google_client_secret="test-secret",
        google_oauth_redirect_uri="http://127.0.0.1:3000/api/calendar-connections/google/callback",
        google_calendar_credential_encryption_key=Fernet.generate_key().decode(),
    )


def test_official_oauth_pkce_offline_scope_and_cipher():
    adapter = GoogleCalendarProvider(real_settings())
    result = adapter.build_authorization_url("test-state")
    query = parse_qs(urlsplit(result.url).query)
    assert query["scope"] == [SCOPE]
    assert query["access_type"] == ["offline"] and query["include_granted_scopes"] == ["true"]
    assert query["code_challenge_method"] == ["S256"] and len(result.verifier) == 128
    assert query["state"] == ["test-state"] and "test-secret" not in result.url
    secret = SecretCipher(Fernet.generate_key().decode())
    token = secret.encrypt("test-secret")
    assert secret.decrypt(token) == "test-secret" and "test-secret" not in token
    with pytest.raises(ValueError):
        secret.decrypt(token[:-3] + "xxx")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, google_mode="real")
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            google_mode="fake",
            google_calendar_credential_encryption_key=Fernet.generate_key().decode(),
        )


class Reply:
    def __init__(self, body=None, status=200, headers=None):
        self.body, self.status_code, self.headers = body, status, headers or {}

    def json(self):
        return self.body


def entry(i):
    return {"id": str(i), "summary": f"Calendar {i}", "accessRole": "reader", "primary": i == 0}


def paged_adapter(monkeypatch, pages):
    calls = []

    def get(session, url, **kwargs):
        calls.append(kwargs)
        value = pages.pop(0)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(requests.Session, "get", get)
    return GoogleCalendarProvider(real_settings()), calls


async def test_provider_237_calendars_all_pages(monkeypatch):
    adapter, calls = paged_adapter(
        monkeypatch,
        [
            Reply({"items": [entry(i) for i in range(100)], "nextPageToken": "page2"}),
            Reply({"items": [entry(i) for i in range(100, 200)], "nextPageToken": "page3"}),
            Reply({"items": [entry(i) for i in range(200, 237)]}),
        ],
    )
    result = await adapter.list_calendars("synthetic-access")
    assert len(result) == 237 and len({c.provider_id for c in result}) == 237
    assert [c["params"].get("pageToken") for c in calls] == [None, "page2", "page3"]
    assert all(c["params"]["showHidden"] == "true" and not c["allow_redirects"] for c in calls)


async def test_page_two_failure_never_reconciles(client, google, monkeypatch):
    await connect(client)
    before = await catalog(client)
    adapter, _ = paged_adapter(
        monkeypatch, [Reply({"items": [entry(0)], "nextPageToken": "page2"}), Reply(status=503)]
    )
    monkeypatch.setattr(google, "list_calendars", adapter.list_calendars)
    assert (await client.post(BASE + "/scan")).status_code == 503
    assert await catalog(client) == before


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "REAUTH_REQUIRED"),
        (403, "SCOPE_REQUIRED"),
        (429, "RATE_LIMITED"),
        (500, "PROVIDER_TEMPORARY_ERROR"),
        (503, "PROVIDER_TEMPORARY_ERROR"),
    ],
)
async def test_http_error_mapping(monkeypatch, status, code):
    adapter, _ = paged_adapter(monkeypatch, [Reply(status=status, headers={"Retry-After": "123"})])
    with pytest.raises(ProviderError) as failure:
        await adapter.list_calendars("secret")
    assert failure.value.code == code
    if status == 429:
        assert failure.value.retry_after == 123


@pytest.mark.parametrize(
    "pages",
    [
        [Reply({"items": "bad"})],
        [Reply({"items": [{"id": "bad"}]})],
        [
            Reply({"items": [], "nextPageToken": "repeat"}),
            Reply({"items": [], "nextPageToken": "repeat"}),
        ],
        [Reply({"items": [entry(1), {**entry(1), "summary": "collision"}]})],
        [requests.Timeout("synthetic-secret")],
    ],
)
async def test_malformed_or_timeout_provider_safe(monkeypatch, pages):
    adapter, _ = paged_adapter(monkeypatch, pages)
    with pytest.raises(ProviderError) as failure:
        await adapter.list_calendars("secret")
    assert "secret" not in str(failure.value)


async def test_deleted_technician_during_transfer_rolls_back(client, google):
    await connect(client)
    calendar = (await catalog(client))[0]
    source, target = await technician(client, "Source"), await technician(client, "Target")
    await client.put(
        f"/api/technicians/{source['id']}/calendar", json={"calendar_id": calendar["id"]}
    )
    assert (
        await client.request(
            "DELETE",
            f"/api/technicians/{target['id']}",
            json={"confirmation": "DELETE", "expected_updated_at": target["updated_at"]},
        )
    ).status_code == 204
    response = await client.put(
        f"/api/calendars/{calendar['id']}/assignment",
        json={"technician_id": target["id"], "expected_assigned_technician_id": source["id"]},
    )
    assert response.status_code == 404
    assert (await client.get(f"/api/technicians/{source['id']}")).json()["calendar"][
        "id"
    ] == calendar["id"]


async def test_same_technician_two_calendar_race(client, google):
    await connect(client)
    tech = await technician(client)
    calendars = (await catalog(client))[:2]
    responses = await asyncio.gather(
        *[
            client.put(f"/api/technicians/{tech['id']}/calendar", json={"calendar_id": c["id"]})
            for c in calendars
        ]
    )
    assert all(r.status_code == 200 for r in responses)
    history = (await client.get(f"/api/technicians/{tech['id']}/calendar-assignments")).json()
    assert len(history) == 2 and sum(h["is_active"] for h in history) == 1


async def test_scan_failure_is_retryable_after_deadline(client, app, google):
    await connect(client)
    google.error = ProviderError("RATE_LIMITED", 172800)
    assert (await client.post(BASE + "/scan")).status_code == 429
    async with app.state.session_factory() as db:
        connection = await db.scalar(select(CalendarConnection))
        assert connection.retry_at > now() + timedelta(hours=47)
        connection.retry_at = now() - timedelta(seconds=1)
        await db.commit()
    google.error = None
    assert (await client.post(BASE + "/scan")).status_code == 200
    assert (await client.get(BASE)).json()["last_error_code"] is None


async def test_callback_after_session_revoked_during_exchange(client, app, google, monkeypatch):
    from hub.auth.models import ManagerSession

    async def exchange(code, verifier):
        async with app.state.session_factory() as db:
            await db.execute(update(ManagerSession).values(revoked_at=now()))
            await db.commit()
        return google.grant

    monkeypatch.setattr(google, "exchange_authorization_code", exchange)
    url = await begin(client)
    assert (await client.get(url)).headers["location"].endswith("error")
    async with app.state.session_factory() as db:
        assert await db.scalar(select(CalendarConnection)) is None


async def test_disconnection_revocation_failure_still_wipes_credential(client, app, google):
    await connect(client)
    google.error = RuntimeError("provider-secret-in-error")
    assert (await disconnect(client)).status_code == 204
    async with app.state.session_factory() as db:
        connection = await db.scalar(select(CalendarConnection))
        assert connection.status == "DISCONNECTED" and connection.encrypted_refresh_token is None
        events = (await db.scalars(select(AuditEvent))).all()
        assert "google.revocation.failed" in {e.action for e in events}
        assert "provider-secret" not in str([vars(e) for e in events])


async def test_session_rotation_requires_original_session(client, app, google, credentials):
    from hub.auth.service import create_manager

    async with app.state.session_factory() as db:
        await create_manager(db, "different-manager", credentials["password"])
    url = await begin(client)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://127.0.0.1:3000",
        headers={"Origin": "http://127.0.0.1:3000", "X-Hub-Request": "1"},
    ) as other:
        assert (
            await other.post(
                "/api/auth/login",
                json={"username": "different-manager", "password": credentials["password"]},
            )
        ).status_code == 200
        assert (await other.get(url)).headers["location"].endswith("error")
    assert (await client.get(url)).headers["location"].endswith("connected")


async def test_unexpected_account_identity_fails_closed(client, google):
    google.calendars = [replace(c, primary=False) for c in google.calendars]
    assert (await client.get(await begin(client))).headers["location"].endswith("error")
    assert (await client.get(BASE)).json()["id"] is None


async def test_official_library_exchange_and_refresh_are_normalized(monkeypatch):
    from google.auth.exceptions import RefreshError
    from google.oauth2.credentials import Credentials

    adapter = GoogleCalendarProvider(real_settings())
    closed = []

    class FlowStub:
        oauth2session = SimpleNamespace(close=lambda: closed.append(True))

        def fetch_token(self, **kwargs):
            assert kwargs == {
                "code": "synthetic-code",
                "timeout": (5, 15),
                "allow_redirects": False,
            }
            return {
                "access_token": "synthetic-access",
                "refresh_token": "synthetic-refresh",
                "scope": SCOPE,
            }

    monkeypatch.setattr(adapter, "_flow", lambda verifier, **kwargs: FlowStub())
    grant = await adapter.exchange_authorization_code("synthetic-code", "verifier")
    assert grant.refresh_token == "synthetic-refresh" and closed

    def refresh(self, transport):
        raise RefreshError("secret raw failure", {"error": "invalid_grant"})

    monkeypatch.setattr(Credentials, "refresh", refresh)
    with pytest.raises(ProviderError, match="REAUTH_REQUIRED") as failure:
        await adapter.refresh_credentials("synthetic-refresh")
    assert "secret raw" not in str(failure.value)


async def test_empty_malformed_catalog_does_not_reconcile(monkeypatch):
    adapter, _ = paged_adapter(monkeypatch, [Reply({})])
    with pytest.raises(ProviderError, match="MALFORMED_RESPONSE"):
        await adapter.list_calendars("synthetic-access")


async def test_callback_scope_redacted_before_access_log(client, app, google):
    url = await begin(client)
    seen = []
    original = app.router

    class Capture:
        async def __call__(self, scope, receive, send):
            if scope.get("type") == "http" and scope.get("path") == BASE + "/callback":
                seen.append(scope["query_string"])
            await original(scope, receive, send)

    # Replace the innermost router after the authentication/redaction middleware.
    node = app.middleware_stack
    while hasattr(node, "app") and node.app is not original:
        node = node.app
    assert node.app is original
    node.app = Capture()
    assert (await client.get(url)).headers["location"].endswith("connected")
    assert seen == [b""]


async def test_secret_config_validation_never_echoes_input():
    with pytest.raises(ValidationError) as failure:
        Settings(_env_file=None, google_mode="real", google_client_secret="synthetic-client-secret")
    assert "synthetic-client-secret" not in str(failure.value)


async def test_encryption_absent_fails_closed_even_in_production():
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            app_env="production",
            cookie_secure=True,
            allowed_origins=["https://hub.example.test"],
            google_mode="real",
            google_client_id="test-client",
            google_client_secret="test-client-secret",
            google_oauth_redirect_uri="https://hub.example.test/api/calendar-connections/google/callback",
        )


@pytest.mark.parametrize("scopes", [[SCOPE, "previously-granted-scope"], ["unrelated-scope"]])
async def test_incremental_scope_warning_requires_discovery_scope(monkeypatch, scopes):
    adapter = GoogleCalendarProvider(real_settings())

    class ScopeFlow:
        oauth2session = SimpleNamespace(close=lambda: None)

        def fetch_token(self, **kwargs):
            warning = Warning("Scope changed")
            warning.token = {
                "access_token": "synthetic-access",
                "refresh_token": "synthetic-refresh",
                "scope": scopes,
            }
            raise warning

    monkeypatch.setattr(adapter, "_flow", lambda verifier, **kwargs: ScopeFlow())
    if SCOPE in scopes:
        grant = await adapter.exchange_authorization_code("code", "verifier")
        assert grant.scopes == tuple(scopes)
    else:
        with pytest.raises(ProviderError, match="SCOPE_REQUIRED"):
            await adapter.exchange_authorization_code("code", "verifier")
