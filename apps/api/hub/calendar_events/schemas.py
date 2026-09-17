from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from hub.calendar_events.domain import CalendarEventView


class ScheduleTechnician(BaseModel):
    id: UUID
    first_name: str
    last_name: str


class ScheduleCalendar(BaseModel):
    id: UUID
    name: str


class ScheduleRead(BaseModel):
    technician: ScheduleTechnician
    calendar: ScheduleCalendar | None = None
    state: Literal[
        "READY",
        "NO_CALENDAR",
        "CALENDAR_UNAVAILABLE",
        "EVENT_SCOPE_REQUIRED",
        "REAUTH_REQUIRED",
        "PROVIDER_ERROR",
        "TIMEZONE_REQUIRED",
        "CHANGED",
        "BUSY",
    ]
    operational_date: date | None = None
    next_schedule_date: date | None = None
    timezone: str | None = None
    display_semantics: Literal["CALENDAR_WALL_CLOCK"] = "CALENDAR_WALL_CLOCK"
    jobs: list[CalendarEventView] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    last_fetched_at: datetime | None = None
    error_code: str | None = None
    retry_at: datetime | None = None
