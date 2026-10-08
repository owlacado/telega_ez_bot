"""Deterministic, process-local provider. Settings restrict this to isolated tests."""

from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from urllib.parse import urlencode

from hub.accounting_mirrors.provider import (
    SheetMetadata,
    SheetsProviderError,
    formatting_requests,
)
from hub.google_calendar.types import (
    EVENT_SCOPE,
    REPORT_WRITE_SCOPE,
    SCOPE,
    SHEETS_SCOPE,
    Authorization,
    DiscoveredCalendar,
    ProviderError,
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
        self.sheets_error = None
        self.spreadsheets = {}
        self.sheets_calls = []
        self.report_events = {}
        self.report_sequence = 0
        self.ambiguous_add_once = False

    def build_authorization_url(
        self, state, event_access=False, sheets_access=False, report_write_access=False
    ):
        return Authorization(
            "/api/calendar-connections/google/callback?"
            + urlencode(
                {
                    "state": state,
                    "code": "fake-upgrade-code" if event_access or sheets_access else "fake-code",
                }
            ),
            "fake-pkce-verifier",
        )

    async def exchange_authorization_code(
        self, code, verifier, event_access=False, sheets_access=False, report_write_access=False
    ):
        self.calls.append("exchange")
        scopes = {SCOPE, *self.grant.scopes}
        if event_access:
            scopes.add(EVENT_SCOPE)
        if report_write_access:
            scopes.add(REPORT_WRITE_SCOPE)
        if sheets_access:
            scopes.add(SHEETS_SCOPE)
        self.grant = replace(self.grant, scopes=tuple(sorted(scopes)))
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
        if self.event_reads[key] > 1 and not provider_calendar_id.startswith("test-stable-"):
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

    def _spreadsheet(self, identifier):
        return self.spreadsheets.setdefault(identifier, {"next": 1, "sheets": []})

    def _sheets_failure(self):
        if self.sheets_error:
            raise self.sheets_error

    async def get_spreadsheet_metadata(self, access_token, spreadsheet_id):
        self.sheets_calls.append("metadata")
        self._sheets_failure()
        book = self._spreadsheet(spreadsheet_id)
        return tuple(
            SheetMetadata(item["id"], item["title"], item["rows"], item["columns"])
            for item in book["sheets"]
        )

    async def add_sheet(self, access_token, spreadsheet_id, title, rows, columns):
        self.sheets_calls.append("add_sheet")
        self._sheets_failure()
        book = self._spreadsheet(spreadsheet_id)
        if any(item["title"] == title for item in book["sheets"]):
            raise SheetsProviderError("CONFIGURATION_ERROR")
        item = {
            "id": book["next"],
            "title": title,
            "rows": max(rows, 1),
            "columns": max(columns, 1),
            "values": [],
            "formats": [],
        }
        book["next"] += 1
        book["sheets"].append(item)
        if self.ambiguous_add_once:
            self.ambiguous_add_once = False
            raise SheetsProviderError("PROVIDER_TEMPORARY_ERROR", retryable=True)
        return SheetMetadata(item["id"], title, item["rows"], item["columns"])

    def _sheet(self, spreadsheet_id, *, sheet_id=None, title=None):
        for item in self._spreadsheet(spreadsheet_id)["sheets"]:
            if (sheet_id is not None and item["id"] == sheet_id) or (
                title is not None and item["title"] == title
            ):
                return item
        raise SheetsProviderError("SPREADSHEET_NOT_FOUND")

    async def clear_owned_range(self, access_token, spreadsheet_id, sheet_id, rows, columns):
        self.sheets_calls.append("clear")
        self._sheets_failure()
        sheet = self._sheet(spreadsheet_id, sheet_id=sheet_id)
        for row in range(min(rows, len(sheet["values"]))):
            for column in range(min(columns, len(sheet["values"][row]))):
                sheet["values"][row][column] = ""
        sheet["formats"] = [
            item
            for item in sheet["formats"]
            if item.get("startRowIndex", 0) >= rows or item.get("startColumnIndex", 0) >= columns
        ]

    async def write_values(self, access_token, spreadsheet_id, sheet_title, values):
        self.sheets_calls.append(("values", "RAW"))
        self._sheets_failure()
        sheet = self._sheet(spreadsheet_id, title=sheet_title)
        width = max((len(row) for row in values), default=0)
        sheet["rows"] = max(sheet["rows"], len(values), 1)
        sheet["columns"] = max(sheet["columns"], width, 1)
        while len(sheet["values"]) < len(values):
            sheet["values"].append([])
        for row_index, row in enumerate(values):
            while len(sheet["values"][row_index]) < width:
                sheet["values"][row_index].append("")
            for column_index, value in enumerate(row):
                sheet["values"][row_index][column_index] = value

    async def batch_update_formatting(
        self, access_token, spreadsheet_id, sheet_id, payload, current_rows, current_columns
    ):
        self.sheets_calls.append("format")
        self._sheets_failure()
        sheet = self._sheet(spreadsheet_id, sheet_id=sheet_id)
        sheet["rows"] = max(sheet["rows"], payload.row_count, current_rows, 1)
        sheet["columns"] = max(sheet["columns"], payload.column_count, current_columns, 1)
        sheet["formats"] = formatting_requests(sheet_id, payload, sheet["rows"], sheet["columns"])

    def inspect_sheet(self, spreadsheet_id, title):
        return self._sheet(spreadsheet_id, title=title)

    async def get_report_event(self, access_token, calendar_id, event_id):
        if self.error:
            raise self.error
        value = self.report_events.get((calendar_id, event_id))
        if value is None:
            raise ProviderError("CALENDAR_UNAVAILABLE")
        return deepcopy(value)

    async def patch_report_description(
        self, access_token, calendar_id, event_id, etag, description
    ):
        value = await self.get_report_event(access_token, calendar_id, event_id)
        if value.get("etag") != etag:
            raise ProviderError("EVENT_CHANGED")
        self.report_sequence += 1
        value.update(description=description, etag=f'"fake-report-{self.report_sequence}"')
        self.report_events[(calendar_id, event_id)] = value
        return deepcopy(value)
