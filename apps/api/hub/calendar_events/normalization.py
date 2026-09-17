"""Strict Google-to-domain parsing; no raw payload survives this boundary."""

import re
from datetime import UTC, date, datetime
from urllib.parse import urlsplit

from hub.calendar_events.domain import ProviderEvent, calendar_zone, clean_text
from hub.google_calendar.types import ProviderError


def timestamp(value, fallback: str):
    if not isinstance(value, dict):
        raise ProviderError("MALFORMED_RESPONSE")
    if "date" in value:
        if (
            "dateTime" in value
            or not isinstance(value["date"], str)
            or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value["date"])
        ):
            raise ProviderError("MALFORMED_RESPONSE")
        return date.fromisoformat(value["date"])
    raw = value.get("dateTime")
    if not isinstance(raw, str) or not re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
        r"(?:\.[0-9]+)?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])?",
        raw,
        re.IGNORECASE,
    ):
        raise ProviderError("MALFORMED_RESPONSE")
    parsed = datetime.fromisoformat(raw.upper().replace("Z", "+00:00"))
    zone = calendar_zone(value.get("timeZone") or fallback)
    if parsed.tzinfo is None:
        # Google permits offset omission with explicit IANA timezone only.
        if not value.get("timeZone"):
            raise ProviderError("MALFORMED_RESPONSE")
        first, second = parsed.replace(tzinfo=zone, fold=0), parsed.replace(tzinfo=zone, fold=1)
        if first.utcoffset() != second.utcoffset():
            raise ProviderError("MALFORMED_RESPONSE")  # ambiguous/nonexistent local time
        parsed = first
        if parsed.astimezone(UTC).astimezone(zone).replace(tzinfo=None) != parsed.replace(
            tzinfo=None
        ):
            raise ProviderError("MALFORMED_RESPONSE")
    return parsed


def recurrence_identity(item, timezone: str):
    """Cancelled exceptions carry the same instance identity as active ones."""
    try:
        parent, original = item.get("recurringEventId"), item.get("originalStartTime")
        if parent is None and original is None:
            return None
        if (
            not isinstance(parent, str)
            or not parent
            or len(parent) > 1024
            or any(ord(c) < 33 for c in parent)
            or original is None
        ):
            raise ProviderError("MALFORMED_RESPONSE")
        return parent, timestamp(original, timezone)
    except (ValueError, TypeError, OverflowError, AttributeError):
        raise ProviderError("MALFORMED_RESPONSE") from None


def normalize_event(item, timezone: str) -> ProviderEvent | None:
    try:
        if not isinstance(item, dict):
            raise ProviderError("MALFORMED_RESPONSE")
        identifier = item.get("id")
        if (
            not isinstance(identifier, str)
            or not identifier
            or len(identifier) > 1024
            or any(ord(c) < 32 for c in identifier)
        ):
            raise ProviderError("MALFORMED_RESPONSE")
        recurrence = recurrence_identity(item, timezone)
        status = item.get("status", "confirmed")
        if status == "cancelled":
            return None  # tombstones legitimately lack start/end/summary
        if status not in {"confirmed", "tentative"}:
            raise ProviderError("MALFORMED_RESPONSE")
        start, end = timestamp(item.get("start"), timezone), timestamp(item.get("end"), timezone)
        all_day = not isinstance(start, datetime)
        if all_day != (not isinstance(end, datetime)) or end <= start:
            raise ProviderError("MALFORMED_RESPONSE")
        link = item.get("htmlLink")
        if isinstance(link, str) and len(link) <= 4096:
            url = urlsplit(link)
            link = (
                link
                if url.scheme == "https"
                and url.netloc == "calendar.google.com"
                and not any(ord(c) < 33 for c in link)
                else None
            )
        else:
            link = None
        recurring, original = recurrence if recurrence else (None, None)
        if original is not None and all_day != (not isinstance(original, datetime)):
            raise ProviderError("MALFORMED_RESPONSE")
        updated = timestamp({"dateTime": item["updated"]}, timezone) if "updated" in item else None
        if updated is not None and updated.tzinfo is None:
            raise ProviderError("MALFORMED_RESPONSE")
        return ProviderEvent(
            provider_event_id=identifier,
            summary=clean_text(item.get("summary", "Untitled job"), 100_000),
            description=clean_text(item.get("description"), 4000, optional=True),
            location=clean_text(item.get("location"), 1000, optional=True),
            start=start,
            end=end,
            is_all_day=all_day,
            status=status,
            html_link=link,
            recurring_event_id=recurring,
            original_start_time=original,
            provider_updated_at=updated,
        )
    except (ValueError, TypeError, OverflowError, AttributeError):
        raise ProviderError("MALFORMED_RESPONSE") from None
