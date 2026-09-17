from datetime import timedelta

import pytest
from sqlalchemy import select, update

from hub.audit.models import AuditEvent
from hub.auth.models import ManagerSession
from hub.auth.security import digest, now
from hub.core.config import Settings


@pytest.mark.parametrize(
    "path",
    [
        "/api/technicians",
        "/api/calendars",
        "/api/technicians/11111111-1111-4111-8111-111111111111",
        "/api/technicians/11111111-1111-4111-8111-111111111111/calendar-assignments",
        "/api/auth/me",
        "/docs",
        "/openapi.json",
    ],
)
async def test_unauthenticated_data_denied(anonymous, path):
    assert (await anonymous.get(path)).status_code == 401


async def test_login_logout_and_revocation(client, engine):
    me = await client.get("/api/auth/me")
    assert me.status_code == 200
    token = client.cookies.get("hub_session")
    assert token not in me.text
    assert "password" not in me.text
    async with engine.connect() as db:
        record = (
            await db.execute(select(ManagerSession.token_hash, ManagerSession.revoked_at))
        ).first()
        assert record.token_hash == digest(token)
        assert record.revoked_at is None
    assert (await client.post("/api/auth/logout")).status_code == 204
    client.cookies.set("hub_session", token)
    assert (await client.get("/api/technicians")).status_code == 401


async def test_cookie_flags_and_rotation(anonymous, credentials):
    payload = {key: credentials[key] for key in ["username", "password"]}
    first = await anonymous.post("/api/auth/login", json=payload)
    original = anonymous.cookies.get("hub_session")
    cookie = first.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/" in cookie
    assert credentials["password"] not in first.text
    await anonymous.post("/api/auth/login", json=payload)
    assert anonymous.cookies.get("hub_session") != original
    anonymous.cookies.clear()
    anonymous.cookies.set("hub_session", original)
    assert (await anonymous.get("/api/auth/me")).status_code == 401


async def test_expired_session_denied(client, engine):
    async with engine.begin() as db:
        await db.execute(update(ManagerSession).values(expires_at=now() - timedelta(seconds=1)))
    assert (await client.get("/api/technicians")).status_code == 401


async def test_csrf_and_origin_rejection(client):
    client.headers.pop("X-CSRF-Token")
    assert (
        await client.post("/api/technicians", json={"first_name": "Demo", "last_name": "Name"})
    ).status_code == 403
    client.headers["X-CSRF-Token"] = (await client.get("/api/auth/me")).json()["csrf_token"]
    assert (
        await client.post(
            "/api/technicians",
            headers={"Origin": "https://evil.invalid"},
            json={"first_name": "Demo", "last_name": "Name"},
        )
    ).status_code == 403
    client.headers.pop("Origin")
    assert (await client.post("/api/auth/logout")).status_code == 403


async def test_login_origin_and_custom_header_required(anonymous):
    anonymous.headers.pop("X-Hub-Request")
    assert (
        await anonymous.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    ).status_code == 403
    assert (
        await anonymous.options("/api/technicians", headers={"Origin": "https://evil.invalid"})
    ).status_code == 403


async def test_login_generic_failure_throttled_and_audited(anonymous, engine):
    for _ in range(8):
        response = await anonymous.post(
            "/api/auth/login",
            json={"username": "no-default-admin", "password": "not-a-real-password"},
        )
        assert response.status_code == 401
        assert response.json()["error"]["message"] == "Invalid username or password."
    assert (
        await anonymous.post(
            "/api/auth/login", json={"username": "no-default-admin", "password": "wrong"}
        )
    ).status_code == 429
    async with engine.connect() as db:
        events = (await db.execute(select(AuditEvent.action, AuditEvent.outcome))).all()
        assert ("auth.login", "THROTTLED") in events
        assert all("password" not in str(event).lower() for event in events)


def test_insecure_cookie_configuration_rejected():
    with pytest.raises(ValueError):
        Settings(app_env="production", cookie_secure=False)
    with pytest.raises(ValueError):
        Settings(allowed_origins=["http://public.example"])
    assert Settings(
        app_env="production", cookie_secure=True, allowed_origins=["https://hub.example"]
    ).cookie_secure


async def test_no_default_account(anonymous):
    for username in ["admin", "manager"]:
        assert (
            await anonymous.post(
                "/api/auth/login", json={"username": username, "password": "admin"}
            )
        ).status_code == 401
