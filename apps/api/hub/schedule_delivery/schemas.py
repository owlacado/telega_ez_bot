from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SendSchedule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_date: date
    fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    resend_of_id: UUID | None = None
    confirm_duplicate_risk: bool = False


class DeliverySettingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


class DispatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    target_date: date
    trigger: Literal["MANUAL", "AUTOMATIC", "MANUAL_RESEND"]
    destination: Literal["WORK_GROUP", "PRIVATE"]
    requested_destination: Literal["WORK_GROUP", "PRIVATE"] | None = None
    fallback_reason: (
        Literal["GROUP_UNAVAILABLE_BEFORE_SEND", "GROUP_REJECTED_PRIVATE_FALLBACK"] | None
    ) = None
    status: Literal["PENDING", "PROCESSING", "SENT", "FAILED", "AMBIGUOUS", "CANCELLED"]
    fingerprint: str
    job_count: int
    attempt_count: int
    error_code: str | None
    created_at: datetime
    sent_at: datetime | None
    finished_at: datetime | None
    ack_status: Literal["NOT_SENT", "PENDING", "ACKNOWLEDGED"]
    acknowledged_at: datetime | None
    superseded_at: datetime | None = None
    resend_of_id: UUID | None


class ScheduleDeliveryRead(BaseModel):
    enabled: bool
    available: bool
    destination: Literal["WORK_GROUP", "PRIVATE"] | None
    local_time: str
    history: list[DispatchRead]
    automatic_state: str | None = None
    automatic_error: str | None = None
