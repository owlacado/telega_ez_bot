"""Versioned, immutable schedule presentation; no provider identifiers or report blocks."""

import hashlib
import html
import json
import unicodedata
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict

from hub.core.secrets import SecretCipher


class PayloadJob(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    time: str
    title: str
    location: str | None
    phone: str | None = None
    details: str | None = None


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Literal[1, 2] = 2
    target_date: date
    technician_name: str
    jobs: tuple[PayloadJob, ...]

    def copy_addresses(self):
        return tuple((i, job.location) for i, job in enumerate(self.jobs, 1) if job.location)

    def canonical(self):
        value = self.model_dump(mode="json")
        if self.version == 1:
            for job in value["jobs"]:
                job.pop("phone", None)
                job.pop("details", None)
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    @property
    def fingerprint(self):
        return hashlib.sha256(self.canonical().encode()).hexdigest()

    def render(self, *, waiting_confirmation=False, plain=False):
        if any(len(address) > 256 for _, address in self.copy_addresses()):
            raise ValueError("SCHEDULE_TOO_LARGE")
        escape = html.escape
        lines = [
            f"<b>{escape(self.technician_name)}</b>",
            self.target_date.strftime("%A, %B %d, %Y"),
            "",
        ]
        for index, job in enumerate(self.jobs, 1):
            if index > 1:
                lines.extend(["", "\u2501" * 20, ""])
            number = "".join(digit + "\ufe0f\u20e3" for digit in str(index))
            lines.extend([f"<b>{number} {escape(job.time)}</b>", escape(job.title), ""])
            if job.location:
                lines.append("\U0001f3e0 " + escape(job.location))
            if job.phone:
                lines.append("\U0001f4de " + escape(job.phone))
            if job.details:
                lines.extend(["", "\U0001f4dc Details", escape(job.details)])
        if not self.jobs:
            lines.append("No scheduled jobs.")
        if waiting_confirmation:
            lines.extend(["", "\u23f3 Waiting for technician confirmation"])
        message = "\n".join(lines)
        # Conservative bound includes escaped HTML and tags, measured as UTF-16 units.
        # This is stricter than Telegram's 4096 characters after entity parsing.
        if len(message.encode("utf-16-le")) // 2 > 4096:
            raise ValueError("SCHEDULE_TOO_LARGE")
        return html.unescape(message.replace("<b>", "").replace("</b>", "")) if plain else message


def normalized_text(value):
    return unicodedata.normalize("NFC", " ".join(value.split()))


def from_schedule(schedule):
    from hub.google_calendar.legacy_presentation import present

    jobs = []
    for job in schedule.jobs:
        view = present(job)
        jobs.append(
            PayloadJob(
                time=f"{job.display_start_time}\u2013{job.display_end_time}",
                title=view.title,
                location=view.address,
                phone=view.phone,
                details=view.details,
            )
        )
    return Payload(
        target_date=schedule.operational_date,
        technician_name=normalized_text(
            f"{schedule.technician.first_name} {schedule.technician.last_name}"
        ),
        jobs=tuple(jobs),
    )


def cipher(settings):
    if not settings.schedule_delivery_enabled or not settings.schedule_payload_encryption_key:
        raise ValueError("DELIVERY_DISABLED")
    return SecretCipher(settings.schedule_payload_encryption_key.get_secret_value())


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def source_version(identity):
    return hashlib.sha256(repr(identity).encode()).hexdigest()
