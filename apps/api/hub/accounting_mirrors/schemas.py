from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from hub.technicians.schemas import InputModel


class MirrorConfigureInput(InputModel):
    spreadsheet: str = Field(min_length=10, max_length=500)
    replace: bool = False


class MirrorActionInput(InputModel):
    action: Literal["ENABLE", "DISABLE", "REMOVE", "SYNC"]
    expected_generation: int = Field(ge=1)


class MirrorStatusRead(BaseModel):
    kind: Literal["INDIVIDUAL", "ALL_TECH"]
    technician_id: UUID | None = None
    week_start: date
    week_end: date
    configured: bool = False
    enabled: bool = False
    target_id: UUID | None = None
    target_generation: int | None = None
    spreadsheet_id: str | None = None
    open_url: str | None = None
    auth_state: Literal["READY", "NEEDS_PERMISSION", "NEEDS_AUTH", "NOT_CONNECTED"]
    state: Literal[
        "NOT_CONFIGURED",
        "NEEDS_PERMISSION",
        "READY",
        "DISABLED",
        "PENDING",
        "SYNCING",
        "SYNCED",
        "FAILED",
        "NEEDS_AUTH",
    ]
    requested_generation: int | None = None
    completed_generation: int | None = None
    pending_newer_generation: bool = False
    last_success_at: datetime | None = None
    last_attempt_at: datetime | None = None
    last_error_code: str | None = None
    google_sheet_id: int | None = None
    worker_state: Literal["RUNNING", "STALE", "MISSING"]


class MirrorWorkerHealthRead(BaseModel):
    state: Literal["RUNNING", "STALE", "MISSING"]
    running_instances: int
