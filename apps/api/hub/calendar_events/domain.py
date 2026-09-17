"""Pure schedule projection. Calendar wall clock never follows the browser timezone."""

import re
import unicodedata
from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict

from hub.google_calendar.types import ProviderError

TECHNICIAN_JOB_DAY_START = time(8)
TECHNICIAN_JOB_DAY_END = time(22)
EXCLUDED_TITLE = re.compile(
    r"\b(?:cancel|cancelled|canceled|canceling|cancelling|cancellation|reschedule|rescheduled|rescheduling|fake|faked|faking|redo|redone|redoing)\b",
    re.IGNORECASE,
)
JOB_NUMBER = re.compile(r"^\s*([0-9]{1,9})\.")


class ProviderEvent(BaseModel):
    model_config = ConfigDict(frozen=True)
    provider_event_id: str
    summary: str
    description: str | None = None
    location: str | None = None
    start: datetime | date
    end: datetime | date
    is_all_day: bool
    status: str
    html_link: str | None = None
    recurring_event_id: str | None = None
    original_start_time: datetime | date | None = None
    provider_updated_at: datetime | None = None


class CalendarEventView(ProviderEvent):
    calendar_id: UUID
    display_date: date
    display_start_time: str
    display_end_time: str
    schedule_summary: str
    job_number: int | None


def calendar_zone(name: str | None) -> ZoneInfo:
    if not name:
        raise ProviderError("TIMEZONE_REQUIRED")
    try:
        return ZoneInfo(name)
    except (ValueError, ZoneInfoNotFoundError):
        raise ProviderError("TIMEZONE_REQUIRED") from None


def operational_window(day: date, timezone: str) -> tuple[datetime, datetime]:
    zone = calendar_zone(timezone)
    return (
        datetime.combine(day, time.min, zone).astimezone(UTC),
        datetime.combine(day + timedelta(days=1), time.min, zone).astimezone(UTC),
    )


def next_schedule_date(day: date) -> date:
    return day + timedelta(days=2 if day.weekday() == 5 else 1)


def clean_text(value, limit: int, optional=False):
    if value is None and optional:
        return None
    if not isinstance(value, str) or len(value) > 100_000:
        raise ProviderError("MALFORMED_RESPONSE")
    # Keep readable whitespace; discard invisible controls, including bidi overrides.
    value = "".join(c for c in value if not unicodedata.category(c).startswith("C") or c in "\n\t")
    return value.strip()[:limit]


def schedule_title(summary: str) -> str:
    value = re.sub(r"\([^()]*\)", "", summary)
    value = re.sub(r"\bdidn['’]?t\s+buy\b", "", value, flags=re.IGNORECASE)
    return " ".join(value.split()).strip() or summary


class JobEventFilter:
    @staticmethod
    def includes(event: ProviderEvent, day: date, timezone: str) -> bool:
        if event.status == "cancelled" or event.is_all_day:
            return False
        if EXCLUDED_TITLE.search(event.summary):
            return False
        start = event.start.astimezone(calendar_zone(timezone))
        return (
            start.date() == day
            and TECHNICIAN_JOB_DAY_START <= start.time() <= TECHNICIAN_JOB_DAY_END
        )


def build_technician_schedule(
    calendar_id: UUID, day: date, timezone: str, events: list[ProviderEvent]
):
    zone = calendar_zone(timezone)
    jobs = []
    for event in events:
        if not JobEventFilter.includes(event, day, timezone):
            continue
        start, end = event.start.astimezone(zone), event.end.astimezone(zone)
        match = JOB_NUMBER.match(event.summary)
        jobs.append(
            CalendarEventView(
                **{**event.model_dump(), "summary": event.summary[:500]},
                calendar_id=calendar_id,
                display_date=start.date(),
                display_start_time=start.strftime("%H:%M"),
                display_end_time=end.strftime("%H:%M"),
                schedule_summary=schedule_title(event.summary)[:500],
                job_number=int(match[1]) if match else None,
            )
        )
    jobs.sort(
        key=lambda e: (
            e.job_number is None,
            e.job_number or 0,
            e.display_start_time,
            e.start.astimezone(UTC),
            e.provider_event_id,
        )
    )
    counts = Counter(e.job_number for e in jobs if e.job_number is not None)
    warnings = ["Duplicate job sequence number"] if any(n > 1 for n in counts.values()) else []
    return jobs, warnings
