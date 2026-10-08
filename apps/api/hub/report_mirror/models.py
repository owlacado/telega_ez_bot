"""Durable report projection work; canonical money remains in WorkReportRevision."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from hub.core.database import Base


class ReportCalendarMirror(Base):
    __tablename__ = "report_calendar_mirrors"
    __table_args__ = (
        CheckConstraint("status IN ('PENDING','PROCESSING','SYNCED','BLOCKED')", name="status"),
        CheckConstraint("requested_revision > 0 AND synced_revision >= 0", name="revision"),
        CheckConstraint("(claim_token IS NULL) = (lease_until IS NULL)", name="claim_pair"),
    )
    report_id: Mapped[UUID] = mapped_column(
        ForeignKey("work_reports.id", ondelete="RESTRICT"), primary_key=True
    )
    connection_id: Mapped[UUID] = mapped_column(
        ForeignKey("calendar_connections.id", ondelete="RESTRICT")
    )
    calendar_id: Mapped[UUID] = mapped_column(ForeignKey("calendars.id", ondelete="RESTRICT"))
    provider_calendar_id: Mapped[str] = mapped_column(String(1024))
    provider_event_id: Mapped[str] = mapped_column(String(1024))
    requested_revision: Mapped[int] = mapped_column(Integer)
    synced_revision: Mapped[int] = mapped_column(Integer, server_default="0")
    status: Mapped[str] = mapped_column(String(20), server_default="PENDING")
    claim_token: Mapped[UUID | None]
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    error_code: Mapped[str | None] = mapped_column(String(50))
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
