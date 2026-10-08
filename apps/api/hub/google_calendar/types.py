from dataclasses import dataclass, field
from typing import Protocol

REPORT_WRITE_SCOPE = "https://www.googleapis.com/auth/calendar.events"

EVENT_SCOPE = "https://www.googleapis.com/auth/calendar.events.readonly"

SCOPE = "https://www.googleapis.com/auth/calendar.calendarlist.readonly"

SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"


@dataclass(frozen=True)
class Authorization:
    url: str = field(repr=False)
    verifier: str = field(repr=False)


@dataclass(frozen=True)
class TokenGrant:
    access_token: str = field(repr=False)
    refresh_token: str | None = field(default=None, repr=False)
    scopes: tuple[str, ...] = (SCOPE,)


@dataclass(frozen=True)
class DiscoveredCalendar:
    provider_id: str
    name: str
    timezone: str | None = None
    primary: bool = False
    access_role: str = "reader"


class ProviderError(Exception):
    CODES = {
        "EVENT_CHANGED",
        "REAUTH_REQUIRED",
        "SCOPE_REQUIRED",
        "EVENT_SCOPE_REQUIRED",
        "CALENDAR_UNAVAILABLE",
        "TIMEZONE_REQUIRED",
        "REQUEST_LIMIT",
        "RATE_LIMITED",
        "PROVIDER_TEMPORARY_ERROR",
        "CONFIGURATION_ERROR",
        "MALFORMED_RESPONSE",
        "ACCOUNT_IDENTITY_UNAVAILABLE",
    }

    def __init__(self, code: str, retry_after: int = 60):
        self.code = code if code in self.CODES else "PROVIDER_TEMPORARY_ERROR"
        self.retry_after = max(retry_after, 1)
        super().__init__(self.code)


class CalendarProvider(Protocol):
    def build_authorization_url(
        self,
        state: str,
        event_access: bool = False,
        sheets_access: bool = False,
        report_write_access: bool = False,
    ) -> Authorization: ...
    async def exchange_authorization_code(
        self,
        code: str,
        verifier: str,
        event_access: bool = False,
        sheets_access: bool = False,
        report_write_access: bool = False,
    ) -> TokenGrant: ...
    async def refresh_credentials(
        self, refresh_token: str, scopes: tuple[str, ...] = (SCOPE,)
    ) -> TokenGrant: ...
    async def revoke_credentials(self, refresh_token: str) -> None: ...
    async def list_calendars(self, access_token: str) -> list[DiscoveredCalendar]: ...

    async def list_events(
        self, access_token: str, provider_calendar_id: str, time_min, time_max, timezone: str
    ): ...

    async def get_report_event(self, access_token, calendar_id, event_id): ...
    async def patch_report_description(
        self, access_token, calendar_id, event_id, etag, description
    ): ...
