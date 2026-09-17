"""Deterministic, process-local provider. Settings restrict this to isolated tests."""

from urllib.parse import urlencode

from hub.google_calendar.types import Authorization, DiscoveredCalendar, TokenGrant


class FakeCalendarProvider:
    def __init__(self):
        self.calendars = [
            DiscoveredCalendar("test-primary", "Test Google account", primary=True),
            DiscoveredCalendar("test-atlanta", "GA - Atlanta"),
            DiscoveredCalendar("test-savannah", "GA - Savannah"),
        ]
        self.grant = TokenGrant("fake-access-only", "fake-refresh-only")
        self.error = None
        self.calls = []

    def build_authorization_url(self, state):
        return Authorization(
            "/api/calendar-connections/google/callback?"
            + urlencode({"state": state, "code": "fake-code"}),
            "fake-pkce-verifier",
        )

    async def exchange_authorization_code(self, code, verifier):
        self.calls.append("exchange")
        if self.error:
            raise self.error
        return self.grant

    async def refresh_credentials(self, refresh_token):
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
