from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, StringConstraints

from hub.technicians.schemas import InputModel


class CalendarCreate(InputModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=150)]


class AssignedTechnician(BaseModel):
    id: UUID
    name: str


class CalendarRead(BaseModel):
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
