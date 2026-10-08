"""Temporary Google-only presentation compatibility; never mutates provider events."""

import re
from dataclasses import dataclass

from hub.report_mirror.presentation import END, START

PHONE = re.compile(
    r"(?<![\w\d])(?:\+?1[ .-]?)?(?:\([2-9]\d{2}\)|[2-9]\d{2})[ .-]?[2-9]\d{2}[ .-]?\d{4}(?!\d)"
)
HISTORY = re.compile(
    r"^\s*(?:confirmed\s+by\s+.+|lvm\s*[-:]\s*.+|\d{1,2}/\d{1,2}\s*>\s*\d{1,2}/\d{1,2}\b.*)$", re.I
)
REPORT = re.compile(
    r"^\s*(?:amount of closed project|type of payment|who closed this project\??|"
    r"telegram\s*(?:user)?id|groupon review|yearly maintenance plan was provided)\s*:",
    re.I | re.M,
)


@dataclass(frozen=True)
class LegacyPresentation:
    title: str
    phone: str | None
    address: str | None
    details: str | None


def details_only(description):
    value = description or ""
    # Malformed/open managed blocks are hidden from display, never repaired on the source.
    value = re.sub(re.escape(START) + r".*?(?:" + re.escape(END) + r"|$)", "", value, flags=re.S)
    sections = value.split("***")
    value = "\n".join(part for part in sections if not REPORT.search(part))
    return (
        "\n".join(line for line in value.splitlines() if not HISTORY.fullmatch(line)).strip()
        or None
    )


def present(event):
    title = re.sub(r"^\s*\d+\.\s+", "", event.summary)
    match = PHONE.search(title)
    phone = None
    if match:
        digits = re.sub(r"\D", "", match.group())[-10:]
        phone = f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
        title = title[: match.start()] + title[match.end() :]
    from hub.calendar_events.domain import schedule_title

    title = schedule_title(title)
    return LegacyPresentation(
        " ".join(title.split()).strip(" -|"),
        phone,
        event.location if event.location and event.location.strip() else None,
        details_only(event.description),
    )
