"""Stage 3 domain, transport, PostgreSQL lifecycle and adversarial regressions."""

import asyncio
import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import requests
from sqlalchemy import select, update

from hub.auth.models import ManagerSession
from hub.calendar_events import service
from hub.calendar_events.domain import (
    build_technician_schedule,
    calendar_zone,
    next_schedule_date,
    operational_window,
)
from hub.calendar_events.normalization import normalize_event
from hub.calendars.models import Calendar, CalendarAssignment
from hub.core.config import Settings
from hub.google_calendar.models import CalendarConnection
from hub.google_calendar.provider import GoogleCalendarProvider
from hub.google_calendar.types import EVENT_SCOPE, SCOPE, ProviderError, TokenGrant
from tests.test_google_calendar import (  # noqa: F401
    BASE,
    catalog,
    connect,
    disconnect,
    technician,
)
from tests.test_google_calendar import google as google

DAY = date(2026, 9, 17)
ZONE = "America/New_York"


def item(identifier="job", title="1. Furnace", hour="08:00", day=DAY, **extra):
    return {
        "id": identifier,
        "summary": title,
        "start": {"dateTime": f"{day}T{hour}:00-04:00"},
        "end": {"dateTime": f"{day}T23:00:00-04:00"},
        **extra,
    }


def jobs(*items):
    return build_technician_schedule(
        uuid4(),
        DAY,
        ZONE,
        [event for raw in items if (event := normalize_event(raw, ZONE)) is not None],
    )


@pytest.mark.parametrize(
    "word",
    (
        "cancel cancelled canceled canceling cancelling cancellation "
        "reschedule rescheduled rescheduling fake faked faking redo redone redoing"
    ).split(),
)
def test_title_filters(word):
    assert jobs(item(title=f"  2. {word.upper()} - Job!  "))[0] == []


@pytest.mark.parametrize(
    "title", ["Cancellationist repair", "Refaked part", "1. Furnace", "Repair (notes)"]
)
def test_description_keywords_do_not_filter(title):
    assert len(jobs(item(title=title, description="cancel cancelled fake redo reschedule"))[0]) == 1


@pytest.mark.parametrize(
    "hour,expected", [("07:59", 0), ("08:00", 1), ("21:59", 1), ("22:00", 1), ("22:01", 0)]
)
def test_work_window(hour, expected):
    assert len(jobs(item(hour=hour))[0]) == expected


def test_number_order_and_cleanup():
    result, warnings = jobs(
        item("b", "2. Duct", "09:00"),
        item("c", "1. Furnace (old customer) didnt buy", "10:00"),
        item("a", "1. Dryer", "08:00"),
        item("d", "Unnumbered", "08:00"),
    )
    assert [e.provider_event_id for e in result] == ["a", "c", "b", "d"]
    assert result[1].summary == "1. Furnace (old customer) didnt buy"
    assert result[1].schedule_summary == "1. Furnace"
    assert warnings == ["Duplicate job sequence number"]


def test_all_day_cancelled_and_cross_midnight():
    assert (
        jobs(
            item(status="cancelled"),
            {"id": "dead", "status": "cancelled"},
            item(start={"date": "2026-09-17"}, end={"date": "2026-09-18"}),
            item(day=DAY - timedelta(days=1)),
        )[0]
        == []
    )


@pytest.mark.parametrize("weekday,delta", [(0, 1), (1, 1), (2, 1), (3, 1), (4, 1), (5, 2), (6, 1)])
def test_next_weekday(weekday, delta):
    day = date(2026, 9, 14) + timedelta(days=weekday)
    assert next_schedule_date(day) == day + timedelta(days=delta)


@pytest.mark.parametrize("zone", ["America/New_York", "America/Los_Angeles"])
@pytest.mark.parametrize("day,hours", [(date(2026, 3, 8), 23), (date(2026, 11, 1), 25), (DAY, 24)])
def test_dst_day_window(zone, day, hours):
    start, end = operational_window(day, zone)
    assert (end - start).total_seconds() == hours * 3600
    assert start.astimezone(calendar_zone(zone)).hour == 0
    assert end.astimezone(calendar_zone(zone)).date() == day + timedelta(days=1)


@pytest.mark.parametrize(
    "zone,offset", [("America/New_York", "-04:00"), ("America/Los_Angeles", "-07:00")]
)
def test_calendar_wall_clock(zone, offset):
    raw = item(
        start={"dateTime": f"{DAY}T08:00:00{offset}"}, end={"dateTime": f"{DAY}T09:00:00{offset}"}
    )
    result, _ = build_technician_schedule(uuid4(), DAY, zone, [normalize_event(raw, zone)])
    assert result[0].display_start_time == "08:00"
    assert result[0].start.utcoffset().total_seconds() != 0


@pytest.mark.parametrize(
    "change",
    [
        {"start": None},
        {"end": None},
        {"start": {"dateTime": "bad"}},
        {"start": {"dateTime": "2026-09-17T08:00:00", "timeZone": "Invalid/Zone"}},
        {"start": {"dateTime": "2026-09-17T08:00:00"}},
        {"end": {"dateTime": "2026-09-17T07:00:00-04:00"}},
        {"summary": "x" * 100001},
        {"id": "bad\x00id"},
        {"start": {"dateTime": "2026-11-01T01:30:00", "timeZone": ZONE}},
        {"start": {"dateTime": "2026-03-08T02:30:00", "timeZone": ZONE}},
    ],
)
def test_malformed_event_fails_closed(change):
    with pytest.raises(ProviderError):
        normalize_event(item(**change), ZONE)


@pytest.mark.parametrize(
    "link",
    [
        "javascript:alert(1)",
        "data:text/html,x",
        "https://calendar.google.com.evil.test/",
        "https://evil@calendar.google.com/",
        "https://calendar.google.com:443/",
        "//calendar.google.com/x",
    ],
)
def test_unsafe_links(link):
    assert normalize_event(item(htmlLink=link), ZONE).html_link is None


def test_metadata_bounds_plain_text():
    event = normalize_event(
        item(
            title="<script>alert(1)</script> 😀 مرحبا " * 100,
            location="<b>Street</b>" * 500,
            description="Note\n<script>cancel</script>\x00",
            htmlLink="https://calendar.google.com/calendar/event?eid=test",
        ),
        ZONE,
    )
    assert len(event.location) <= 1000
    projected, _ = build_technician_schedule(uuid4(), DAY, ZONE, [event])
    assert len(projected[0].summary) <= 500
    assert "<script>" in event.summary and "\x00" not in event.description
    assert "😀" in event.summary and "مرحبا" in event.summary
    assert event.html_link


class Response:
    def __init__(self, body, status=200, headers=None):
        self.body, self.status_code, self.headers = body, status, headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def iter_content(self, size):
        yield json.dumps(self.body).encode()


async def transport(monkeypatch, pages):
    calls = []

    def get(session, url, **kwargs):
        calls.append((url, kwargs))
        value = pages[len(calls) - 1]
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(requests.Session, "get", get)
    start, end = operational_window(DAY, ZONE)
    value = await GoogleCalendarProvider(Settings()).list_events(
        "secret", "cal/id", start, end, ZONE
    )
    return value, calls


async def test_event_pagination_recurring_and_empty_page(monkeypatch):
    recurring = item(
        "instance",
        recurringEventId="parent",
        originalStartTime={"dateTime": "2026-09-17T08:00:00-04:00"},
    )
    result, calls = await transport(
        monkeypatch,
        [
            Response({"items": [], "nextPageToken": "a"}),
            Response({"items": [recurring], "nextPageToken": "b"}),
            Response({"items": [recurring, item("second")]}),
        ],
    )
    assert len(result) == 2 and result[0].recurring_event_id == "parent"
    assert len(calls) == 3 and calls[2][1]["params"]["pageToken"] == "b"
    url, options = calls[0]
    assert "cal%2Fid/events" in url
    assert options["params"]["singleEvents"] == "true"
    assert options["params"]["orderBy"] == "startTime"
    assert options["params"]["showDeleted"] == "false"
    assert options["params"]["timeZone"] == ZONE
    assert options["allow_redirects"] is False and options["stream"] is True


@pytest.mark.parametrize(
    "last",
    [
        Response({}, 503),
        requests.ConnectionError("secret customer"),
        Response({"items": [item("same", title="Changed")]}),
        Response({"items": [], "nextPageToken": "a"}),
        Response({"items": [], "nextPageToken": 42}),
    ],
)
async def test_no_partial_pagination_result(monkeypatch, last):
    with pytest.raises(ProviderError):
        await transport(
            monkeypatch, [Response({"items": [item("same")], "nextPageToken": "a"}), last]
        )


@pytest.mark.parametrize(
    "status,reason,code",
    [
        (401, "", "REAUTH_REQUIRED"),
        (403, "insufficientPermissions", "EVENT_SCOPE_REQUIRED"),
        (403, "forbidden", "CALENDAR_UNAVAILABLE"),
        (403, "rateLimitExceeded", "RATE_LIMITED"),
        (429, "", "RATE_LIMITED"),
        (500, "", "PROVIDER_TEMPORARY_ERROR"),
        (404, "", "CALENDAR_UNAVAILABLE"),
    ],
)
async def test_event_http_errors(monkeypatch, status, reason, code):
    with pytest.raises(ProviderError) as error:
        await transport(
            monkeypatch, [Response({"error": {"errors": [{"reason": reason}]}}, status)]
        )
    assert error.value.code == code


@pytest.fixture
async def assigned(client, google, monkeypatch):
    monkeypatch.setattr(service, "now", lambda: datetime(2026, 9, 17, 16, tzinfo=UTC))
    google.grant = replace(google.grant, scopes=(SCOPE, EVENT_SCOPE))
    await connect(client)
    cal = next(c for c in await catalog(client) if c["name"] == "GA - Atlanta")
    tech = await technician(client)
    response = await client.put(
        f"/api/technicians/{tech['id']}/calendar", json={"calendar_id": cal["id"]}
    )
    assert response.status_code == 200, response.text
    return tech, cal


async def get_today(client, assigned):
    return await client.get(f"/api/technicians/{assigned[0]['id']}/calendar/today")


async def test_today_preview_and_privacy(client, google, assigned, caplog):
    google.events = [
        item(description="cancel note", location="CUSTOMER_PRIVATE_ADDRESS"),
        item("fake", title="fake job"),
    ]
    response = await get_today(client, assigned)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["state"] == "READY" and len(data["jobs"]) == 1
    assert data["operational_date"] == "2026-09-17" and data["next_schedule_date"] == "2026-09-18"
    assert response.headers["cache-control"] == "no-store"
    assert "CUSTOMER_PRIVATE_ADDRESS" not in caplog.text
    google.events = [item(day=DAY + timedelta(days=1))]
    preview = (
        await client.get(f"/api/technicians/{assigned[0]['id']}/calendar/next-schedule")
    ).json()
    assert preview["operational_date"] == "2026-09-18" and len(preview["jobs"]) == 1


async def test_anonymous_and_no_calendar(anonymous, client, google):
    # separate client has no auth cookie
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(
        transport=ASGITransport(app=client._transport.app), base_url="http://127.0.0.1:3000"
    ) as guest:
        assert (await guest.get(f"/api/technicians/{uuid4()}/calendar/today")).status_code == 401
    tech = await technician(client)
    assert (await client.get(f"/api/technicians/{tech['id']}/calendar/today")).json()[
        "state"
    ] == "NO_CALENDAR"
    assert "events" not in google.calls


@pytest.mark.parametrize("state", ["scope", "unavailable", "reauth", "disconnected"])
async def test_preflight_states_do_not_call_provider(client, google, assigned, app, state):
    async with app.state.session_factory() as db:
        connection = await db.scalar(select(CalendarConnection))
        if state == "scope":
            connection.granted_scopes = [SCOPE]
        if state == "unavailable":
            await db.execute(update(Calendar).values(availability="UNAVAILABLE"))
        if state == "reauth":
            connection.status = "REAUTH_REQUIRED"
        if state == "disconnected":
            connection.status = "DISCONNECTED"
            connection.encrypted_refresh_token = None
        await db.commit()
    data = (await get_today(client, assigned)).json()
    assert (
        data["state"]
        == {
            "scope": "EVENT_SCOPE_REQUIRED",
            "unavailable": "CALENDAR_UNAVAILABLE",
            "reauth": "REAUTH_REQUIRED",
            "disconnected": "REAUTH_REQUIRED",
        }[state]
    )
    assert "events" not in google.calls


@pytest.mark.parametrize(
    "code,expected",
    [
        ("EVENT_SCOPE_REQUIRED", "EVENT_SCOPE_REQUIRED"),
        ("REAUTH_REQUIRED", "REAUTH_REQUIRED"),
        ("RATE_LIMITED", "PROVIDER_ERROR"),
        ("PROVIDER_TEMPORARY_ERROR", "PROVIDER_ERROR"),
    ],
)
async def test_error_scope_revocation_and_backoff(client, google, assigned, app, code, expected):
    async def fail(*args):
        raise ProviderError(code, 120)

    google.list_events = fail
    data = (await get_today(client, assigned)).json()
    assert data["state"] == expected
    async with app.state.session_factory() as db:
        connection = await db.scalar(select(CalendarConnection))
        if code == "EVENT_SCOPE_REQUIRED":
            assert connection.status == "CONNECTED" and connection.granted_scopes == [SCOPE]
            assert (await client.post(BASE + "/scan")).status_code == 200
        if code == "RATE_LIMITED":
            assert connection.retry_at is not None


@pytest.mark.parametrize(
    "change", ["unavailable", "reassign", "deactivate", "disconnect", "upgrade", "expiry"]
)
async def test_event_request_concurrency(client, google, assigned, app, change):
    entered, release = asyncio.Event(), asyncio.Event()
    original = google.list_events

    async def paused(*args):
        entered.set()
        await release.wait()
        return await original(*args)

    google.list_events = paused
    task = asyncio.create_task(get_today(client, assigned))
    await asyncio.wait_for(entered.wait(), 5)
    try:
        async with app.state.session_factory() as db:
            if change == "unavailable":
                await db.execute(update(Calendar).values(availability="UNAVAILABLE"))
            if change == "reassign":
                await db.execute(update(CalendarAssignment).values(is_active=False))
            if change == "deactivate":
                from hub.technicians.models import Technician

                await db.execute(
                    update(Technician)
                    .where(Technician.id == UUID(assigned[0]["id"]))
                    .values(status="INACTIVE")
                )
            if change == "upgrade":
                conn = await db.scalar(select(CalendarConnection))
                conn.generation += 1
            if change == "expiry":
                await db.execute(update(ManagerSession).values(revoked_at=datetime.now(UTC)))
            await db.commit()
        if change == "disconnect":
            assert (await disconnect(client)).status_code == 204
    finally:
        release.set()
    response = await task
    if change == "expiry":
        assert response.status_code == 401
    else:
        assert response.json()["state"] == "CHANGED" and response.json()["jobs"] == []


@pytest.mark.parametrize("omitted", [False, True])
async def test_scope_upgrade_same_account(client, google, app, omitted):
    await connect(client)
    before = (await client.get(BASE)).json()
    response = await client.post(
        BASE + "/start",
        json={
            "mode": "RECONNECT",
            "request_event_access": True,
            "expected_connection_id": before["id"],
            "expected_generation": before["generation"],
        },
    )
    assert response.status_code == 200
    if omitted:
        google.grant = replace(google.grant, refresh_token=None)
    url = response.json()["authorization_url"]
    assert (await client.get(url)).headers["location"].endswith("connected")
    assert EVENT_SCOPE in (await client.get(BASE)).json()["granted_scopes"]
    assert (await client.get(url)).headers["location"].endswith("error")
    assert (await client.post(BASE + "/scan")).status_code == 200


@pytest.mark.parametrize("failure", ["partial", "wrong_account", "expired"])
async def test_upgrade_failure_preserves_discovery(client, google, app, failure):
    await connect(client)
    before = (await client.get(BASE)).json()
    response = await client.post(
        BASE + "/start",
        json={
            "mode": "RECONNECT",
            "request_event_access": True,
            "expected_connection_id": before["id"],
            "expected_generation": before["generation"],
        },
    )
    url = response.json()["authorization_url"]

    async def exchange(*args, **kwargs):
        return TokenGrant("access", "refresh", (SCOPE,))

    if failure == "partial":
        google.exchange_authorization_code = exchange
    if failure == "wrong_account":
        google.calendars = [
            replace(c, provider_id="other") if c.primary else c for c in google.calendars
        ]
    if failure == "expired":
        from hub.google_calendar.models import GoogleOAuthAttempt

        async with app.state.session_factory() as db:
            await db.execute(
                update(GoogleOAuthAttempt).values(
                    expires_at=datetime.now(UTC) - timedelta(minutes=1)
                )
            )
            await db.commit()
    callback = await client.get(url)
    if failure != "partial":
        assert callback.headers["location"].endswith("error")
    assert (await client.get(BASE)).json()["status"] == "CONNECTED"
    if failure == "partial":
        assert EVENT_SCOPE not in (await client.get(BASE)).json()["granted_scopes"]
    assert (await client.post(BASE + "/scan")).status_code == 200


async def test_cancelled_conflict_fails_full_fetch(monkeypatch):
    with pytest.raises(ProviderError):
        await transport(
            monkeypatch,
            [
                Response({"items": [item()], "nextPageToken": "next"}),
                Response({"items": [{"id": "job", "status": "cancelled"}]}),
            ],
        )


async def test_large_body_and_page_budget(monkeypatch):
    with pytest.raises(ProviderError) as error:
        await transport(monkeypatch, [Response({"padding": "x" * 8_000_001})])
    assert error.value.code == "REQUEST_LIMIT"
    pages = [Response({"items": [], "nextPageToken": str(i)}) for i in range(100)]
    with pytest.raises(ProviderError) as error:
        await transport(monkeypatch, pages)
    assert error.value.code == "REQUEST_LIMIT"


async def test_event_scope_incremental_authorization_url():
    from urllib.parse import parse_qs, urlsplit

    from pydantic import SecretStr

    adapter = GoogleCalendarProvider(
        Settings(
            google_client_id="synthetic-client",
            google_client_secret=SecretStr("synthetic-secret"),
            google_oauth_redirect_uri="http://localhost:3000/api/calendar-connections/google/callback",
        )
    )
    values = parse_qs(
        urlsplit(adapter.build_authorization_url("state", event_access=True).url).query
    )
    assert set(values["scope"][0].split()) == {SCOPE, EVENT_SCOPE}
    assert values["include_granted_scopes"] == ["true"]
    assert values["code_challenge_method"] == ["S256"]


async def test_scope_upgrade_omitted_token_does_not_invent_refresh_capability(client, google):
    await connect(client)
    before = (await client.get(BASE)).json()

    async def exchange(*args, **kwargs):
        return TokenGrant("access", None, (SCOPE, EVENT_SCOPE))

    async def refresh(*args, **kwargs):
        return TokenGrant("old-access", "old-refresh", (SCOPE,))

    google.exchange_authorization_code = exchange
    google.refresh_credentials = refresh
    url = (
        await client.post(
            BASE + "/start",
            json={
                "mode": "RECONNECT",
                "request_event_access": True,
                "expected_connection_id": before["id"],
                "expected_generation": before["generation"],
            },
        )
    ).json()["authorization_url"]
    assert (await client.get(url)).headers["location"].endswith("connected")
    assert (await client.get(BASE)).json()["granted_scopes"] == [SCOPE]
    assert (await client.post(BASE + "/scan")).status_code == 200


async def test_event_fetch_no_idle_sql_and_double_request(client, google, assigned, app):
    from sqlalchemy import text

    entered, release = asyncio.Event(), asyncio.Event()
    original = google.list_events

    async def held(*args):
        entered.set()
        await release.wait()
        return await original(*args)

    google.list_events = held
    first = asyncio.create_task(get_today(client, assigned))
    await asyncio.wait_for(entered.wait(), 5)
    try:
        async with app.state.session_factory() as db:
            assert (
                await db.scalar(
                    text(
                        "SELECT count(*) FROM pg_stat_activity "
                        "WHERE datname=current_database() AND state='idle in transaction'"
                    )
                )
                == 0
            )
        assert (await get_today(client, assigned)).json()["state"] == "BUSY"
    finally:
        release.set()
    assert (await first).json()["state"] == "READY"


async def test_unknown_provider_failure_does_not_leak_pii(client, google, assigned, caplog):
    async def fail(*args):
        raise RuntimeError("CUSTOMER_SECRET_ADDRESS authorization_code_secret")

    google.list_events = fail
    response = await get_today(client, assigned)
    assert response.json()["state"] == "PROVIDER_ERROR"
    assert "CUSTOMER_SECRET" not in response.text + caplog.text
    assert "authorization_code_secret" not in response.text + caplog.text


@pytest.mark.parametrize("day", [date(2026, 9, 19), date(2026, 9, 20)])
async def test_weekend_preview_operational_date(client, google, assigned, monkeypatch, day):
    monkeypatch.setattr(
        service,
        "now",
        lambda: datetime.combine(day, datetime.min.time(), UTC) + timedelta(hours=12),
    )
    # Authentication uses real time; only the operational clock is advanced here.
    # Test sessions must remain valid across the simulated weekend.
    from sqlalchemy import update

    from hub.auth import security
    from hub.auth.models import ManagerSession

    # snapshot compares expiry to the operational clock; extend only this test session.
    # Access the test application's session factory through the ASGI transport.
    async with client._transport.app.state.session_factory() as db:
        await db.execute(
            update(ManagerSession).values(expires_at=security.now() + timedelta(days=10))
        )
        await db.commit()
    data = (await client.get(f"/api/technicians/{assigned[0]['id']}/calendar/next-schedule")).json()
    assert data["operational_date"] == "2026-09-21"


def test_cancelled_event_with_valid_title():
    assert jobs(item(status="cancelled"))[0] == []


@pytest.mark.parametrize(
    "day,zone,offset",
    [
        (date(2026, 3, 8), "America/New_York", "-04:00"),
        (date(2026, 11, 1), "America/New_York", "-05:00"),
        (date(2026, 3, 8), "America/Los_Angeles", "-07:00"),
        (date(2026, 11, 1), "America/Los_Angeles", "-08:00"),
    ],
)
def test_dst_display_keeps_eight(day, zone, offset):
    raw = item(
        start={"dateTime": f"{day}T08:00:00{offset}", "timeZone": zone},
        end={"dateTime": f"{day}T09:00:00{offset}", "timeZone": zone},
    )
    result, _ = build_technician_schedule(uuid4(), day, zone, [normalize_event(raw, zone)])
    assert result[0].display_start_time == "08:00"


def test_title_filter_uses_full_title_before_display_truncation():
    assert jobs(item(title="Valid text " * 100 + " CANCEL"))[0] == []


async def test_discovery_refresh_updates_granted_capabilities(client, google, assigned):
    google.grant = replace(google.grant, scopes=(SCOPE,))
    assert (await client.post(BASE + "/scan")).status_code == 200
    assert (await client.get(BASE)).json()["granted_scopes"] == [SCOPE]
    assert (await get_today(client, assigned)).json()["state"] == "EVENT_SCOPE_REQUIRED"
