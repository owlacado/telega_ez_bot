"""Versioned, immutable technician-facing content; no provider identifiers or notes."""

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


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Literal[1] = 1
    target_date: date
    technician_name: str
    jobs: tuple[PayloadJob, ...]

    def canonical(self):
        return json.dumps(
            self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        )

    @property
    def fingerprint(self):
        return hashlib.sha256(self.canonical().encode()).hexdigest()

    def render(self):
        escape = html.escape
        lines = [
            f"<b>{escape(self.technician_name)}</b>",
            self.target_date.strftime("%A, %B %d, %Y"),
            "",
        ]
        for job in self.jobs:
            lines.append(f"<b>{escape(job.time)}</b> {escape(job.title)}")
            if job.location:
                lines.append(escape(job.location))
        if not self.jobs:
            lines.append("No scheduled jobs.")
        message = "\n".join(lines)
        # Conservative bound includes escaped HTML and tags, measured as UTF-16 units.
        # This is stricter than Telegram's 4096 characters after entity parsing.
        if len(message.encode("utf-16-le")) // 2 > 4096:
            raise ValueError("SCHEDULE_TOO_LARGE")
        return message


def normalized_text(value):
    return unicodedata.normalize("NFC", " ".join(value.split()))


def from_schedule(schedule):
    return Payload(
        target_date=schedule.operational_date,
        technician_name=normalized_text(
            f"{schedule.technician.first_name} {schedule.technician.last_name}"
        ),
        jobs=tuple(
            PayloadJob(
                time=j.display_start_time,
                title=normalized_text(j.schedule_summary),
                location=normalized_text(j.location) or None if j.location else None,
            )
            for j in schedule.jobs
        ),
    )


def cipher(settings):
    if not settings.schedule_delivery_enabled or not settings.schedule_payload_encryption_key:
        raise ValueError("DELIVERY_DISABLED")
    return SecretCipher(settings.schedule_payload_encryption_key.get_secret_value())


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def source_version(identity):
    return hashlib.sha256(repr(identity).encode()).hexdigest()
