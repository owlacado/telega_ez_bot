"""Deterministic, process-local provider. Settings restrict this to isolated tests."""

from dataclasses import replace
from datetime import timedelta
from urllib.parse import urlencode

from hub.google_calendar.types import (
    EVENT_SCOPE,
    SCOPE,
    Authorization,
    DiscoveredCalendar,
    TokenGrant,
)


class FakeCalendarProvider:
    def __init__(self):
        self.calendars = [
            DiscoveredCalendar(
                "test-primary", "Test Google account", primary=True, timezone="America/New_York"
            ),
            DiscoveredCalendar("test-atlanta", "GA - Atlanta", timezone="America/New_York"),
            DiscoveredCalendar("test-savannah", "GA - Savannah", timezone="America/New_York"),
        ]
        self.grant = TokenGrant("fake-access-only", "fake-refresh-only")
        self.event_reads = {}
        self.events = None
        self.error = None
        self.calls = []

    def build_authorization_url(self, state, event_access=False):
        return Authorization(
            "/api/calendar-connections/google/callback?"
            + urlencode(
                {"state": state, "code": "fake-event-code" if event_access else "fake-code"}
            ),
            "fake-pkce-verifier",
        )

    async def exchange_authorization_code(self, code, verifier, event_access=False):
        self.calls.append("exchange")
        if code == "fake-event-code":
            self.grant = replace(self.grant, scopes=(SCOPE, EVENT_SCOPE))
        if self.error:
            raise self.error
        return self.grant

    async def refresh_credentials(self, refresh_token, scopes=(SCOPE,)):
        self.calls.append("refresh")
        if self.error:
            raise self.error
        return self.grant

    async def list_calendars(self, access_token):
        self.calls.append("list")
        if self.error:
            raise self.error
        return list(self.calendars)

    async def revoke_credentials(self, refresh_token):
        self.calls.append("revoke")
        if self.error:
            raise self.error

    async def list_events(self, access_token, provider_calendar_id, time_min, time_max, timezone):
        from hub.calendar_events.domain import calendar_zone
        from hub.calendar_events.normalization import normalize_event

        self.calls.append("events")
        if self.error:
            raise self.error
        if self.events is not None:
            return [
                event
                for item in self.events
                if (event := normalize_event(item, timezone)) is not None
            ]
        key = (provider_calendar_id, time_min.isoformat())
        self.event_reads[key] = self.event_reads.get(key, 0) + 1
        day = time_min.astimezone(calendar_zone(timezone))
        titles = [
            "1. Furnace (old customer) didnt buy",
            "2. Dryer vent cleaning",
            "CANCEL - job",
            "fake job",
            "Unnumbered repair",
        ]
        if self.event_reads[key] > 1:
            titles[0] += f" - refreshed {self.event_reads[key]}"
        rows = []
        for i, title in enumerate(titles):
            start = day.replace(hour=8 + i)
            rows.append(
                normalize_event(
                    {
                        "id": f"fake-event-{i}",
                        "summary": title,
                        "description": "Customer note: do not cancel this valid appointment.",
                        "location": "123 Synthetic Test St",
                        "start": {"dateTime": start.isoformat()},
                        "end": {"dateTime": (start + timedelta(hours=1)).isoformat()},
                    },
                    timezone,
                )
            )
        return rows
