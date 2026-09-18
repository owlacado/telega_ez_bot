import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from hub.core.database import Base


class TechnicianFormSession(Base):
    __tablename__ = "technician_form_sessions"
    __table_args__ = (
        CheckConstraint("purpose = 'WORK_REPORT'", name="purpose"),
        CheckConstraint("status IN ('OPEN','SUBMITTED','EXPIRED','REVOKED')", name="status"),
        CheckConstraint("expires_at > created_at", name="expiry"),
        CheckConstraint(
            "(status = 'SUBMITTED') = (report_id IS NOT NULL "
            "AND submitted_at IS NOT NULL AND payload_hash IS NOT NULL)",
            name="submission",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    technician_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("technicians.id", ondelete="CASCADE"), index=True
    )
    purpose: Mapped[str] = mapped_column(
        String(20), default="WORK_REPORT", server_default="WORK_REPORT"
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(16), default="OPEN", server_default="OPEN")
    telegram_user_id: Mapped[int] = mapped_column(BigInteger)
    bot_id: Mapped[int] = mapped_column(BigInteger)
    binding_generation: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    choices: Mapped[list | None] = mapped_column(JSONB)
    selected: Mapped[dict | None] = mapped_column(JSONB)
    report_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("work_reports.id", ondelete="RESTRICT")
    )
    payload_hash: Mapped[str | None] = mapped_column(String(64))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkReport(Base):
    __tablename__ = "work_reports"
    __table_args__ = (
        UniqueConstraint(
            "technician_id", "calendar_id", "occurrence_key", name="uq_work_report_occurrence"
        ),
        CheckConstraint("length(occurrence_key) = 64", name="occurrence"),
        CheckConstraint("current_revision_number > 0", name="current_revision"),
        ForeignKeyConstraint(
            ["id", "current_revision_number"],
            ["work_report_revisions.report_id", "work_report_revisions.revision_number"],
            name="fk_work_report_current_revision",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    technician_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("technicians.id", ondelete="RESTRICT"), index=True
    )
    calendar_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("calendars.id", ondelete="RESTRICT"))
    occurrence_key: Mapped[str] = mapped_column(String(64))
    current_revision_number: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkReportRevision(Base):
    __tablename__ = "work_report_revisions"
    __table_args__ = (
        UniqueConstraint("report_id", "revision_number", name="uq_work_report_revision"),
        CheckConstraint("revision_number > 0", name="positive_revision"),
        CheckConstraint("amount_closed >= 0 AND amount_closed <= 9999999999.99", name="money"),
        CheckConstraint(
            "payment_method IN ('CASH','ZELLE','CHECK','CREDIT_CARD',"
            "'VENMO','SUPER','ESTIMATE','CANCEL')",
            name="payment",
        ),
        CheckConstraint(
            "payment_method NOT IN ('ESTIMATE','CANCEL') OR amount_closed = 0", name="zero_amount"
        ),
        CheckConstraint("closed_by IN ('MYSELF','CALL_CENTER')", name="closer"),
        CheckConstraint(
            "google_reviews BETWEEN 0 AND 100 AND groupon_reviews BETWEEN 0 AND 100 "
            "AND facebook_reviews BETWEEN 0 AND 100",
            name="reviews",
        ),
        CheckConstraint("length(comments) <= 4000", name="comments"),
        CheckConstraint("sequence > 0", name="sequence"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    report_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("work_reports.id", ondelete="RESTRICT"))
    revision_number: Mapped[int] = mapped_column(Integer, default=1)
    technician_name: Mapped[str] = mapped_column(String(250))
    operational_date: Mapped[date] = mapped_column(Date)
    start_time: Mapped[str] = mapped_column(String(16))
    end_time: Mapped[str] = mapped_column(String(16))
    sequence: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(500))
    location: Mapped[str] = mapped_column(String(1000))
    provider_event_id: Mapped[str] = mapped_column(String(1024))
    recurring_event_id: Mapped[str | None] = mapped_column(String(1024))
    original_start_time: Mapped[str | None] = mapped_column(String(64))
    amount_closed: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    payment_method: Mapped[str] = mapped_column(String(20))
    closed_by: Mapped[str] = mapped_column(String(20))
    comments: Mapped[str] = mapped_column(Text)
    yearly_maintenance_plan_provided: Mapped[bool]
    google_reviews: Mapped[int] = mapped_column(Integer)
    groupon_reviews: Mapped[int] = mapped_column(Integer)
    facebook_reviews: Mapped[int] = mapped_column(Integer)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
