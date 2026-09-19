"""Register every model with Alembic without application or transport startup."""

from hub.audit.models import AuditEvent
from hub.auth.models import Manager, ManagerSession, RateBucket
from hub.calendars.models import Calendar, CalendarAssignment
from hub.expenses.models import ExpenseRevision, TechnicianExpense
from hub.google_calendar.models import CalendarConnection, GoogleOAuthAttempt
from hub.integrations.models import GpsBinding, TelegramBinding
from hub.schedule_delivery.models import (
    ScheduleAutoDecision,
    ScheduleDeliverySetting,
    ScheduleDispatch,
    ScheduleWorkerState,
)
from hub.technicians.models import Technician
from hub.telegram.models import (
    TelegramInvitation,
    TelegramOutbox,
    TelegramProcessedUpdate,
    TelegramWorkerState,
)
from hub.work_reports.models import TechnicianFormSession, WorkReport, WorkReportRevision

__all__ = [
    "TechnicianFormSession",
    "TechnicianExpense",
    "ExpenseRevision",
    "WorkReport",
    "WorkReportRevision",
    "ScheduleDispatch",
    "ScheduleDeliverySetting",
    "ScheduleAutoDecision",
    "ScheduleWorkerState",
    "AuditEvent",
    "Manager",
    "ManagerSession",
    "RateBucket",
    "CalendarConnection",
    "GoogleOAuthAttempt",
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
