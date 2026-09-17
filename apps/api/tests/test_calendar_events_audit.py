"""Independent adversarial Stage 3 evidence; all provider responses are synthetic."""

import asyncio
import logging
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text, update

from hub.auth.models import Manager
from hub.calendar_events.domain import (
    build_technician_schedule,
    next_schedule_date,
    operational_window,
    schedule_title,
)
from hub.calendar_events.normalization import normalize_event
from hub.google_calendar.models import CalendarConnection
from hub.google_calendar.types import SCOPE, ProviderError, TokenGrant
from tests.test_calendar_events import (
    DAY,
    ZONE,
    Response,
    get_today,
    item,
    jobs,
    transport,
)
from tests.test_calendar_events import (
    assigned as assigned,
)
from tests.test_google_calendar import (
    BASE,
    catalog,
    connect,
    disconnect,
    technician,
)
from tests.test_google_calendar import (
    google as google,
)


@pytest.mark.parametrize("reverse", [False, True])
async def test_cancelled_recurrence_conflict_across_ids(monkeypatch, reverse):
    metadata = {
        "recurringEventId": "parent",
        "originalStartTime": {"dateTime": "2026-09-17T12:00:00Z"},
    }
    active = item("active", **metadata)
    tombstone = {"id": "tombstone", "status": "cancelled", **metadata}
    pages = [Response({"items": [active], "nextPageToken": "p"}), Response({"items": [tombstone]})]
    if reverse:
        pages = [
            Response({"items": [tombstone], "nextPageToken": "p"}),
            Response({"items": [active]}),
        ]
    with pytest.raises(ProviderError, match="MALFORMED_RESPONSE"):
        await transport(monkeypatch, pages)


@pytest.mark.parametrize(
    "change",
    [
        {"start": {"date": "2026-09-17", "dateTime": "2026-09-17T08:00:00-04:00"}},
        {"start": {"dateTime": "20260917T080000-0400"}},
        {"start": {"dateTime": "2026-09-17T08:00:00-04:99"}},
        {"updated": "20260917T080000-0400"},
        {"start": {"dateTime": "2026-09-17T08:00:00-04:00:30"}},
        {"recurringEventId": "parent"},
        {"originalStartTime": {"dateTime": "2026-09-17T08:00:00-04:00"}},
    ],
)
def test_ambiguous_provider_shape_rejected(change):
    with pytest.raises(ProviderError, match="MALFORMED_RESPONSE"):
        normalize_event(item(**change), ZONE)


@pytest.mark.parametrize(
    "title,expected",
    [
        ("1. Repair (outer (inner) note) dIdNt BuY", "1. Repair"),
        ("1. Repair (old) Furnace (note)", "1. Repair Furnace"),
        ("1. Repair(unrelated note)Furnace", "1. Repair Furnace"),
        ("1. Repair (unfinished note", "1. Repair (unfinished note"),
    ],
)
def test_preview_nested_cleanup_preserves_source(title, expected):
    source = normalize_event(item(title=title), ZONE)
    assert schedule_title(source.summary) == expected
    assert source.summary == title


async def test_projection_limit_fails_whole_http_schedule(client, google, assigned):
    google.events = [item(str(i)) for i in range(501)]
    response = await get_today(client, assigned)
    assert response.json()["state"] == "PROVIDER_ERROR"
    assert response.json()["error_code"] == "REQUEST_LIMIT"
    assert response.json()["jobs"] == []


@pytest.mark.parametrize(
    "code,result_code",
    [
        (None, "NO_JOBS"),
        ("RATE_LIMITED", "RATE_LIMITED"),
        ("MALFORMED_RESPONSE", "INVALID_PROVIDER_DATA"),
        ("PROVIDER_TEMPORARY_ERROR", "TEMPORARY_PROVIDER_FAILURE"),
    ],
)
async def test_observability_safe_distinct_results(
    client, google, assigned, caplog, code, result_code
):
    caplog.set_level(logging.INFO, logger="hub.calendar_events.service")

    async def read(*args):
        if code:
            raise ProviderError(code)
        return []

    google.list_events = read
    await get_today(client, assigned)
    assert f"result={result_code} " in caplog.text


async def test_observability_preflight(client, google, caplog):
    caplog.set_level(logging.INFO, logger="hub.calendar_events.service")
    tech = await technician(client)
    await client.get(f"/api/technicians/{tech['id']}/calendar/today")
    assert "result=NO_CALENDAR " in caplog.text


@pytest.mark.parametrize(
    "zone,normal,spring,fall",
    [
        ("America/New_York", 4, 5, 4),
        ("America/Chicago", 5, 6, 5),
        ("America/Denver", 6, 7, 6),
        ("America/Los_Angeles", 7, 8, 7),
        ("America/Phoenix", 7, 7, 7),
    ],
)
@pytest.mark.parametrize(
    "day,kind", [(DAY, "normal"), (date(2026, 3, 8), "spring"), (date(2026, 11, 1), "fall")]
)
async def test_exact_dst_query_and_wall_clock(monkeypatch, zone, normal, spring, fall, day, kind):
    import requests

    from hub.core.config import Settings
    from hub.google_calendar.provider import GoogleCalendarProvider

    hour = {"normal": normal, "spring": spring, "fall": fall}[kind]
    delta = 0 if zone == "America/Phoenix" or kind == "normal" else -1 if kind == "spring" else 1
    start, end = operational_window(day, zone)
    assert start == datetime.combine(day, datetime.min.time(), UTC) + timedelta(hours=hour)
    assert end == datetime.combine(day + timedelta(days=1), datetime.min.time(), UTC) + timedelta(
        hours=hour + delta
    )
    from zoneinfo import ZoneInfo

    wall = datetime.combine(day, datetime.min.time(), ZoneInfo(zone)).replace(hour=8)
    raw = item(
        start={"dateTime": wall.isoformat()},
        end={"dateTime": (wall + timedelta(hours=1)).isoformat()},
    )

    def get(session, url, **options):
        assert options["params"]["timeMin"] == start.isoformat()
        assert options["params"]["timeMax"] == end.isoformat()
        assert options["params"]["timeZone"] == zone
        return Response({"items": [raw]})

    monkeypatch.setattr(requests.Session, "get", get)
    events = await GoogleCalendarProvider(Settings()).list_events(
        "synthetic", "synthetic", start, end, zone
    )
    projected, _ = build_technician_schedule(uuid4(), day, zone, events)
    assert projected[0].display_date == day
    assert projected[0].display_start_time == "08:00"


@pytest.mark.parametrize(
    "clock,included",
    [
        ("07:59:59", False),
        ("08:00:00", True),
        ("21:59:59", True),
        ("22:00:00", True),
        ("22:00:01", False),
        ("21:30:00", True),
        ("23:59:59", False),
    ],
)
def test_work_window_exact_seconds(clock, included):
    raw = item(
        start={"dateTime": f"{DAY}T{clock}-04:00"}, end={"dateTime": "2026-09-18T00:30:00-04:00"}
    )
    assert bool(jobs(raw)[0]) == included
    assert jobs(item(day=DAY + timedelta(days=1), hour="00:00"))[0] == []


@pytest.mark.parametrize(
    "stamp", ["2026-09-17T12:00:00Z", "2026-09-17T08:00:00-04:00", "2026-09-17T05:00:00-07:00"]
)
def test_event_zone_and_offset_authoritative_instant(stamp):
    raw = item(start={"dateTime": stamp, "timeZone": "America/Los_Angeles"})
    assert jobs(raw)[0][0].display_start_time == "08:00"


def test_explicit_floating_timezone_and_no_server_fallback():
    raw = item(start={"dateTime": "2026-09-17T08:00:00", "timeZone": ZONE})
    assert jobs(raw)[0][0].display_start_time == "08:00"
    for field in ("start", "end"):
        missing = item()
        missing.pop(field)
        with pytest.raises(ProviderError):
            normalize_event(missing, ZONE)


@pytest.mark.parametrize(
    "word",
    (
        "cancel cancelled canceled canceling cancelling cancellation "
        "reschedule rescheduled rescheduling fake faked faking redo redone redoing"
    ).split(),
)
def test_unicode_whitespace_title_only_keywords(word):
    assert jobs(item(title=f"\u2003\u00a0 1. ({word.upper()}?) \u202f"))[0] == []
    assert (
        len(
            jobs(
                item(
                    title="1. Redondo Beach Faker Street",
                    description=word,
                    location=word,
                    attendees=[{"comment": word}],
                    notes=word,
                )
            )[0]
        )
        == 1
    )


def test_order_and_all_day_recurring():
    rows = [
        item("z", "Unnumbered"),
        item("a", "Unnumbered"),
        item("ten", " 10. Repair"),
        item("two", "2. Repair"),
        item("one", "1. Repair"),
    ]
    first, warning = jobs(*rows)
    assert [r.provider_event_id for r in first] == ["one", "two", "ten", "a", "z"]
    assert [r.provider_event_id for r in jobs(*reversed(rows))[0]] == [
        r.provider_event_id for r in first
    ]
    raw = item(
        title="1. Repair",
        start={"date": "2026-09-17"},
        end={"date": "2026-09-18"},
        recurringEventId="parent",
        originalStartTime={"date": "2026-09-17"},
    )
    assert jobs(raw)[0] == []


@pytest.mark.parametrize(
    "day,target",
    [("2022-12-31", "2023-01-02"), ("2026-01-31", "2026-02-02"), ("2026-05-31", "2026-06-01")],
)
def test_next_workday_month_year(day, target):
    assert next_schedule_date(date.fromisoformat(day)) == date.fromisoformat(target)


@pytest.mark.parametrize("route", ["today", "next-schedule"])
@pytest.mark.parametrize(
    "state", ["anonymous", "inactive", "logout", "missing", "invalid", "valid"]
)
async def test_http_authorization_cache_security_headers(
    client, app, google, assigned, route, state
):
    identifier = assigned[0]["id"]
    if state == "anonymous":
        client.cookies.clear()
    elif state == "logout":
        assert (await client.post("/api/auth/logout")).status_code == 204
    elif state == "inactive":
        async with app.state.session_factory() as db:
            await db.execute(update(Manager).values(is_active=False))
            await db.commit()
    elif state == "missing":
        identifier = str(uuid4())
    elif state == "invalid":
        identifier = "invalid"
    response = await client.get(f"/api/technicians/{identifier}/calendar/{route}")
    assert (
        response.status_code
        == {
            "anonymous": 401,
            "inactive": 401,
            "logout": 401,
            "missing": 404,
            "invalid": 422,
            "valid": 200,
        }[state]
    )
    for header, value in {
        "cache-control": "no-store",
        "referrer-policy": "no-referrer",
        "x-content-type-options": "nosniff",
    }.items():
        assert response.headers[header] == value


@pytest.mark.parametrize("route", ["today", "next-schedule"])
@pytest.mark.parametrize("change", ["assign_b", "exclude", "scope", "inactive"])
async def test_final_http_authoritative_lifecycle_race(
    client, app, google, assigned, route, change
):
    entered, release = asyncio.Event(), asyncio.Event()
    private = "CALENDAR_A_PRIVATE_CUSTOMER"

    async def held(*args):
        entered.set()
        await release.wait()
        return [
            normalize_event(
                item(title=private, day=DAY + timedelta(days=route == "next-schedule")), ZONE
            )
        ]

    google.list_events = held
    task = asyncio.create_task(client.get(f"/api/technicians/{assigned[0]['id']}/calendar/{route}"))
    await asyncio.wait_for(entered.wait(), 5)
    try:
        if change == "assign_b":
            other = next(c for c in await catalog(client) if c["name"] == "GA - Savannah")
            assert (
                await client.put(
                    f"/api/technicians/{assigned[0]['id']}/calendar",
                    json={"calendar_id": other["id"]},
                )
            ).status_code == 200
        elif change == "exclude":
            assert (
                await client.post(
                    f"/api/calendars/{assigned[1]['id']}/exclude",
                    json={
                        "confirmation": "EXCLUDE",
                        "expected_assigned_technician_id": assigned[0]["id"],
                    },
                )
            ).status_code == 204
        else:
            async with app.state.session_factory() as db:
                if change == "scope":
                    await db.execute(update(CalendarConnection).values(granted_scopes=[SCOPE]))
                else:
                    await db.execute(update(Manager).values(is_active=False))
                await db.commit()
    finally:
        release.set()
    response = await asyncio.wait_for(task, 5)
    assert private not in response.text
    if change == "inactive":
        assert response.status_code == 401
    else:
        assert response.json()["state"] == "CHANGED"
        assert response.json()["jobs"] == []
        if change == "assign_b":
            assert response.json()["calendar"]["id"] == other["id"]
    assert response.headers["cache-control"] == "no-store"


async def upgrade_url(client):
    state = (await client.get(BASE)).json()
    response = await client.post(
        BASE + "/start",
        json={
            "mode": "RECONNECT",
            "request_event_access": True,
            "expected_connection_id": state["id"],
            "expected_generation": state["generation"],
        },
    )
    assert response.status_code == 200
    return response.json()["authorization_url"]


@pytest.mark.parametrize("change", ["disconnect", "replace", "event_fetch"])
async def test_incremental_upgrade_lifecycle_race(client, google, assigned, change):
    from tests.test_google_calendar import begin

    url = await upgrade_url(client)
    if change == "disconnect":
        assert (await disconnect(client)).status_code == 204
        assert (await client.get(url)).headers["location"].endswith("error")
        assert (await client.get(BASE)).json()["status"] == "DISCONNECTED"
    elif change == "replace":
        replacement = await begin(client, "SWITCH", True)
        google.calendars = [
            replace(c, provider_id="new-primary") if c.primary else c for c in google.calendars
        ]
        assert (await client.get(replacement)).headers["location"].endswith("connected")
        assert (await client.get(url)).headers["location"].endswith("error")
    else:
        entered, release = asyncio.Event(), asyncio.Event()
        original = google.list_events

        async def held(*args):
            entered.set()
            await release.wait()
            return await original(*args)

        google.list_events = held
        pending = asyncio.create_task(get_today(client, assigned))
        await asyncio.wait_for(entered.wait(), 5)
        try:
            assert (await client.get(url)).headers["location"].endswith("connected")
        finally:
            release.set()
        result = (await pending).json()
        assert result["state"] == "CHANGED" and result["jobs"] == []


async def test_incremental_empty_scope_preserves_discovery(client, google):
    await connect(client)
    url = await upgrade_url(client)

    async def empty(*args, **kwargs):
        return TokenGrant("synthetic", None, ())

    google.exchange_authorization_code = empty
    assert (await client.get(url)).headers["location"].endswith("error")
    assert (await client.get(BASE)).json()["granted_scopes"] == [SCOPE]
    assert (await client.post(BASE + "/scan")).status_code == 200


async def test_several_slow_reads_leave_transaction_pool_free(client, google, assigned, app):
    from time import perf_counter

    from hub.google_calendar.types import DiscoveredCalendar

    google.calendars += [
        DiscoveredCalendar(f"slow-{i}", f"Slow {i}", timezone=ZONE) for i in range(6)
    ]
    assert (await client.post(BASE + "/scan")).status_code == 200
    selected = [c for c in await catalog(client) if c["name"].startswith("Slow ")]
    techs = []
    for cal in selected:
        tech = await technician(client, cal["name"])
        assert (
            await client.put(
                f"/api/technicians/{tech['id']}/calendar", json={"calendar_id": cal["id"]}
            )
        ).status_code == 200
        techs.append(tech)
    entered, release, count = asyncio.Event(), asyncio.Event(), 0

    async def slow(*args):
        nonlocal count
        count += 1
        if count == len(techs):
            entered.set()
        await release.wait()
        return []

    google.list_events = slow
    pending = [
        asyncio.create_task(client.get(f"/api/technicians/{tech['id']}/calendar/today"))
        for tech in techs
    ]
    try:
        await asyncio.wait_for(entered.wait(), 10)
        started = perf_counter()
        async with asyncio.timeout(2):
            async with app.state.session_factory() as db:
                assert await db.scalar(text("SELECT 1")) == 1
                assert (
                    await db.scalar(
                        text(
                            "SELECT count(*) FROM pg_stat_activity "
                            "WHERE datname=current_database() "
                            "AND state='idle in transaction'"
                        )
                    )
                    == 0
                )
        assert perf_counter() - started < 2
        assert (await client.get("/api/health")).status_code == 200
    finally:
        release.set()
        responses = await asyncio.gather(*pending)
    assert all(r.json()["state"] == "READY" for r in responses)


async def test_pii_log_audit_and_no_event_persistence(client, google, assigned, app, caplog):
    import json

    caplog.set_level(logging.INFO, logger="hub.calendar_events.service")
    sentinel = "PRIVATE_CUSTOMER_ADDRESS_AUDIT_SENTINEL"
    google.events = [item(title=sentinel, location=sentinel, description=sentinel)]
    response = await get_today(client, assigned)
    assert sentinel in response.text
    assert sentinel not in caplog.text
    assert "result=SUCCESS " in caplog.text
    async with app.state.session_factory() as db:
        rows = (
            (await db.execute(text("SELECT row_to_json(a)::text FROM audit_events a")))
            .scalars()
            .all()
        )
        assert sentinel not in json.dumps(rows)
        tables = (
            (await db.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public'")))
            .scalars()
            .all()
        )
        assert not any(
            "event" in t and t not in {"audit_events", "telegram_processed_updates"} for t in tables
        )


async def test_malformed_one_event_fails_whole_schedule(client, google, assigned):
    google.events = [item(title="VALID_PRIVATE_JOB"), item("broken", start=None)]
    response = await get_today(client, assigned)
    assert response.json()["error_code"] == "MALFORMED_RESPONSE"
    assert response.json()["jobs"] == []
    assert "VALID_PRIVATE_JOB" not in response.text


@pytest.mark.parametrize(
    "link",
    [
        "http://calendar.google.com/x",
        "https://[malformed",
        "https://evil.test/x",
        "data:text/html,test",
        "javascript:alert(1)",
    ],
)
def test_link_invalid_or_inert(link):
    try:
        result = normalize_event(item(htmlLink=link), ZONE)
        assert result.html_link is None
    except ProviderError as exc:
        assert exc.code == "MALFORMED_RESPONSE"


@pytest.mark.parametrize("action", ["disconnect", "replacement"])
async def test_upgrade_inflight_serializes_lifecycle(client, google, assigned, app, action):
    from tests.test_google_calendar import begin

    url = await upgrade_url(client)
    entered, release = asyncio.Event(), asyncio.Event()
    original = google.exchange_authorization_code

    async def exchange(*args, **kwargs):
        entered.set()
        await release.wait()
        return await original(*args, **kwargs)

    google.exchange_authorization_code = exchange
    upgrade = asyncio.create_task(client.get(url))
    await asyncio.wait_for(entered.wait(), 5)
    other = None
    try:
        if action == "disconnect":
            other = asyncio.create_task(disconnect(client))
        else:
            other_url = await begin(client, "SWITCH", True)
            other = asyncio.create_task(client.get(other_url))
        await asyncio.sleep(0.1)
        assert not other.done()
        async with app.state.session_factory() as db:
            assert await db.scalar(text("SELECT 1")) == 1
    finally:
        release.set()
        responses = await asyncio.gather(upgrade, other) if other else [await upgrade]
    assert responses[0].headers["location"].endswith("connected")
    # Both actions captured the old generation; neither may overwrite the upgrade.
    if action == "disconnect":
        assert responses[1].status_code == 409
    else:
        assert responses[1].headers["location"].endswith("error")
    assert (await client.get(BASE)).json()["status"] == "CONNECTED"


async def test_moved_recurring_instance_and_equivalent_offsets(monkeypatch):
    raw = item(
        "moved",
        hour="10:00",
        recurringEventId="parent",
        originalStartTime={"dateTime": "2026-09-16T08:00:00-04:00"},
    )
    same = {**raw, "originalStartTime": {"dateTime": "2026-09-16T12:00:00Z"}}
    other = item(
        "other",
        recurringEventId="parent",
        originalStartTime={"dateTime": "2026-09-17T08:00:00-04:00"},
    )
    events, _ = await transport(
        monkeypatch,
        [Response({"items": [raw, other], "nextPageToken": "n"}), Response({"items": [same]})],
    )
    assert len(events) == 2
    assert events[0].start.hour == 10
    assert events[0].original_start_time.day == 16


async def test_invalid_json_is_invalid_data(monkeypatch):
    class InvalidJSON(Response):
        def iter_content(self, size):
            yield b'{"PRIVATE_CUSTOMER": broken'

    with pytest.raises(ProviderError, match="MALFORMED_RESPONSE"):
        await transport(monkeypatch, [InvalidJSON({})])


async def test_allowed_large_response_is_bounded(client, google, assigned):
    google.events = [
        item(str(i), description="x" * 100_000, location="x" * 100_000) for i in range(500)
    ]
    response = await get_today(client, assigned)
    data = response.json()
    assert data["state"] == "READY" and len(data["jobs"]) == 500
    assert len(response.content) < 3_500_000
    assert all(len(j["description"]) == 4000 and len(j["location"]) == 1000 for j in data["jobs"])


@pytest.mark.parametrize("route", ["today", "next-schedule"])
async def test_unexpected_schedule_error_keeps_privacy_headers(
    client, app, assigned, monkeypatch, route
):
    from httpx import ASGITransport, AsyncClient

    from hub.calendar_events import router

    async def broken(*args, **kwargs):
        raise RuntimeError("PRIVATE_PROVIDER_PAYLOAD")

    monkeypatch.setattr(router, "read_schedule", broken)
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://127.0.0.1:3000",
        cookies=client.cookies,
    ) as probe:
        response = await probe.get(f"/api/technicians/{assigned[0]['id']}/calendar/{route}")
    assert response.status_code == 500
    assert response.headers.get("cache-control") == "no-store"
    assert response.headers.get("referrer-policy") == "no-referrer"
    assert response.headers.get("x-content-type-options") == "nosniff"
    assert "PRIVATE_PROVIDER_PAYLOAD" not in response.text
