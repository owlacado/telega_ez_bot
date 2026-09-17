from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from hub.technicians.schemas import InputModel
from hub.telegram.types import Purpose


class IssueInvitation(InputModel):
    purpose: Purpose
    replace: bool = False
    expected_generation: int
    confirmation: Literal["CONNECT", "REPLACE"]


class InvitationRead(BaseModel):
    automatic: bool
    id: UUID
    purpose: Purpose
    expires_at: datetime
    state: str
    candidate_user_id: str | None = None
    candidate_display_name: str | None = None
    candidate_username: str | None = None
    candidate_chat_id: str | None = None
    candidate_chat_title: str | None = None
    initiator_admin: bool | None = None
    bot_admin: bool | None = None
    technician_member: bool | None = None
    verified_at: datetime | None = None
    setup_error: str | None = None


class IssuedInvitation(BaseModel):
    invitation: InvitationRead
    link: str
    fallback_command: str | None = None


class ReviewInvitation(InputModel):
    decision: Literal["APPROVE", "REJECT"]


class Disconnect(InputModel):
    purpose: Purpose
    expected_generation: int
    confirmation: Literal["DISCONNECT"]


class TestMessage(InputModel):
    destination: Purpose
    expected_generation: int
    confirmation: Literal["SEND TEST"]


class ConnectionRead(BaseModel):
    state: str
    approved: bool
    generation: int
    availability: str
    telegram_id: str | None = None
    display_name: str | None = None
    username: str | None = None
    replacement_pending: bool = False
    invitation: InvitationRead | None = None


class DeliveryRead(BaseModel):
    id: UUID
    destination: str
    kind: str
    state: str
    error_code: str | None
    created_at: datetime


class RuntimeRead(BaseModel):
    mode: str
    state: str
    bot_username: str | None
    heartbeat_at: datetime | None = None
    error_code: str | None = None


class TelegramState(BaseModel):
    private: ConnectionRead
    group: ConnectionRead
    runtime: RuntimeRead
    deliveries: list[DeliveryRead]
