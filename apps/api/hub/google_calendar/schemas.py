from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from hub.technicians.schemas import InputModel


class GoogleConnectionRead(BaseModel):
    enabled: bool
    id: UUID | None = None
    generation: int | None = None
    status: Literal["DISCONNECTED", "CONNECTED", "REAUTH_REQUIRED", "ERROR"] = "DISCONNECTED"
    account_label: str | None = None
    last_success_at: datetime | None = None
    last_error_code: str | None = None
    retry_at: datetime | None = None
    calendar_count: int = 0
    assignment_count: int = 0
    demo_enabled: bool = False
    impact_version: str | None = None


class StartInput(InputModel):
    mode: Literal["CONNECT", "RECONNECT", "SWITCH"] = "CONNECT"
    expected_connection_id: UUID | None = None
    expected_generation: int | None = None
    confirm_replace: bool = False
    expected_impact_version: str | None = None


class AuthorizationRead(BaseModel):
    authorization_url: str


class DisconnectInput(InputModel):
    confirmation: Literal["DISCONNECT"]
    expected_connection_id: UUID
    expected_generation: int


class ScanRead(BaseModel):
    discovered: int
