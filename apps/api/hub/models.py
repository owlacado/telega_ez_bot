"""Metadata registration only; modules own their models."""

from hub.calendars.models import Calendar, CalendarAssignment
from hub.integrations.models import GpsBinding, TelegramBinding
from hub.technicians.models import Technician

__all__ = ["Calendar", "CalendarAssignment", "GpsBinding", "TelegramBinding", "Technician"]
