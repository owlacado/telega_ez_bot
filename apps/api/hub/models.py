"""Register every model with Alembic without application or transport startup."""

from hub.audit.models import AuditEvent
from hub.auth.models import Manager, ManagerSession, RateBucket
from hub.calendars.models import Calendar, CalendarAssignment
from hub.integrations.models import GpsBinding, TelegramBinding
from hub.technicians.models import Technician
from hub.telegram.models import (
    TelegramInvitation,
    TelegramOutbox,
    TelegramProcessedUpdate,
    TelegramWorkerState,
)

__all__ = [
    "AuditEvent",
    "Manager",
    "ManagerSession",
    "RateBucket",
    "Calendar",
    "CalendarAssignment",
    "GpsBinding",
    "TelegramBinding",
    "Technician",
    "TelegramInvitation",
    "TelegramOutbox",
    "TelegramProcessedUpdate",
    "TelegramWorkerState",
]
