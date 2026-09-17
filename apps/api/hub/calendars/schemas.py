from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, StringConstraints

from hub.technicians.schemas import InputModel


class CalendarCreate(InputModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]


class AssignedTechnician(BaseModel):
    id: UUID
    name: str


class CalendarRead(BaseModel):
    source: Literal["LOCAL_DEMO", "GOOGLE"] = "LOCAL_DEMO"
    availability: Literal["AVAILABLE", "UNAVAILABLE"] = "AVAILABLE"
    excluded_at: datetime | None = None
    timezone: str | None = None
    primary: bool = False
    access_role: str | None = None
    last_seen_at: datetime | None = None
    id: UUID
    name: str
    assigned_technician: AssignedTechnician | None = None
    created_at: datetime
    updated_at: datetime


class AssignmentInput(InputModel):
    calendar_id: UUID


class AssignmentRead(BaseModel):
    model_config = {"from_attributes": True}
    id: UUID
    technician_id: UUID
    calendar_id: UUID | None
    calendar_name: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CalendarExclude(InputModel):
    confirmation: Literal["EXCLUDE"]
    expected_assigned_technician_id: UUID | None


class CalendarAssign(InputModel):
    technician_id: UUID | None
    expected_assigned_technician_id: UUID | None
