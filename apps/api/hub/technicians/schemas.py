from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Last4 = Annotated[str, StringConstraints(pattern=r"^[0-9]{4}$")]
Status = Literal["ACTIVE", "INACTIVE"]
ConnectionStatus = Literal["NOT_CONNECTED", "PENDING", "CONNECTED", "ERROR"]
ReadinessStatus = Literal["READY", "OPTIONAL", "BLOCKED", "NEEDS_ACTION"]


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @field_validator("*", mode="before")
    @classmethod
    def reject_controls(cls, value):
        if isinstance(value, str) and any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("Control characters are not allowed")
        return value


class TechnicianCreate(InputModel):
    first_name: Name
    last_name: Name
    calendar_id: UUID | None = None


class TechnicianUpdate(InputModel):
    expected_record_version: int = Field(ge=1)
    first_name: Name | None = None
    last_name: Name | None = None
    status: Status | None = None
    accounting_timezone: str | None = Field(default=None, max_length=64)

    @field_validator("accounting_timezone")
    @classmethod
    def timezone_name(cls, value):
        if value is not None:
            try:
                if value not in available_timezones() or value in {"Factory", "localtime"}:
                    raise ValueError("Unsupported timezone")
                ZoneInfo(value)
            except (ZoneInfoNotFoundError, ValueError):
                raise ValueError(
                    "Use a valid IANA timezone, for example America/Los_Angeles."
                ) from None
        return value

    @field_validator("first_name", "last_name", "status")
    @classmethod
    def non_nullable(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("This field cannot be null")
        return value

class DeleteConfirmation(InputModel):
    confirmation: Literal["DELETE"]


class TechnicianDelete(DeleteConfirmation):
    expected_record_version: int = Field(ge=1)


class CalendarSummary(BaseModel):
    source: Literal["LOCAL_DEMO", "GOOGLE"] = "LOCAL_DEMO"
    availability: Literal["AVAILABLE", "UNAVAILABLE"] = "AVAILABLE"
    id: UUID
    name: str


class IntegrationSummary(BaseModel):
    telegram_private: ConnectionStatus = "NOT_CONNECTED"
    telegram_group: ConnectionStatus = "NOT_CONNECTED"
    gps_provider: Literal["NONE", "MOTOWATCHDOG_SHARE"] = "NONE"
    gps_status: ConnectionStatus = "NOT_CONNECTED"


class PilotRequirement(BaseModel):
    key: str
    label: str
    status: ReadinessStatus
    required: bool
    reason: str
    action: str | None = None


class TechnicianPilotReadiness(BaseModel):
    ready: bool
    blocking_count: int
    requirements: list[PilotRequirement]


class TechnicianSummary(BaseModel):
    id: UUID
    first_name: str
    last_name: str
    status: Status
    record_version: int
    accounting_timezone: str | None = None
    calendar: CalendarSummary | None
    integrations: IntegrationSummary
    pilot_readiness: TechnicianPilotReadiness
    created_at: datetime
    updated_at: datetime


class TechnicianDetail(TechnicianSummary):
    pass
