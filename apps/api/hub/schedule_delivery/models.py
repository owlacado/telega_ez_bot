from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from hub.core.database import Base, Timestamps


class ScheduleDeliverySetting(Base, Timestamps):
    __tablename__ = "schedule_delivery_settings"
    technician_id: Mapped[UUID] = mapped_column(
        ForeignKey("technicians.id", ondelete="CASCADE"), primary_key=True
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))


class ScheduleDispatch(Base, Timestamps):
    __tablename__ = "schedule_dispatches"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING','PROCESSING','SENT','FAILED','AMBIGUOUS','CANCELLED')",
            name="status",
        ),
        CheckConstraint("trigger IN ('MANUAL','AUTOMATIC','MANUAL_RESEND')", name="trigger"),
        CheckConstraint("destination IN ('WORK_GROUP','PRIVATE')", name="destination"),
        CheckConstraint(
            "requested_destination IS NULL OR requested_destination IN ('WORK_GROUP','PRIVATE')",
            name="requested_destination",
        ),
        CheckConstraint(
            "fallback_reason IS NULL OR (destination = 'PRIVATE' "
            "AND requested_destination IS NOT NULL "
            "AND requested_destination = 'WORK_GROUP' AND fallback_reason IN "
            "('GROUP_UNAVAILABLE_BEFORE_SEND','GROUP_REJECTED_PRIVATE_FALLBACK'))",
            name="fallback_reason",
        ),
        CheckConstraint("message_id IS NULL OR message_id > 0", name="positive_message"),
        CheckConstraint("ack_status IN ('NOT_SENT','PENDING','ACKNOWLEDGED')", name="ack_status"),
        CheckConstraint("attempt_count >= 0 AND job_count >= 0", name="counts"),
        CheckConstraint(
            "(status = 'PROCESSING') = (claim_owner IS NOT NULL AND claim_expires_at IS NOT NULL)",
            name="claim",
        ),
        CheckConstraint(
            "(status = 'SENT') = (sent_at IS NOT NULL AND message_id IS NOT NULL)", name="sent"
        ),
        CheckConstraint(
            "(status = 'SENT' AND ack_status IN ('PENDING','ACKNOWLEDGED')) "
            "OR (status <> 'SENT' AND ack_status = 'NOT_SENT')",
            name="ack_delivery",
        ),
        CheckConstraint(
            "(ack_status = 'ACKNOWLEDGED') = (acknowledged_at IS NOT NULL)", name="ack_time"
        ),
        CheckConstraint(
            "status <> 'SENT' OR encrypted_payload IS NULL", name="sent_payload_purged"
        ),
        CheckConstraint(
            "status NOT IN ('PENDING','PROCESSING') OR encrypted_payload IS NOT NULL",
            name="active_payload",
        ),
        CheckConstraint("fingerprint ~ '^[0-9a-f]{64}$'", name="fingerprint"),
        CheckConstraint("(claim_owner IS NULL) = (claim_expires_at IS NULL)", name="claim_pair"),
        CheckConstraint("(sent_at IS NULL) = (message_id IS NULL)", name="sent_pair"),
        CheckConstraint("(ack_token_hash IS NULL) = (ack_expires_at IS NULL)", name="ack_pair"),
        CheckConstraint(
            "ack_status = 'NOT_SENT' OR ack_token_hash IS NOT NULL", name="ack_capability"
        ),
        CheckConstraint(
            "(status IN ('PENDING','PROCESSING')) = (finished_at IS NULL)", name="finished"
        ),
        CheckConstraint(
            "(trigger = 'MANUAL_RESEND') = (resend_of_id IS NOT NULL)", name="resend_parent"
        ),
        CheckConstraint(
            "encrypted_payload IS NULL OR encrypted_payload LIKE 'v1:%'", name="cipher_version"
        ),
        UniqueConstraint("resend_of_id"),
        Index(
            "uq_schedule_active_day",
            "technician_id",
            "target_date",
            unique=True,
            postgresql_where=text("status IN ('PENDING','PROCESSING')"),
        ),
        Index(
            "uq_schedule_auto_day",
            "technician_id",
            "target_date",
            unique=True,
            postgresql_where=text("trigger = 'AUTOMATIC'"),
        ),
        Index("ix_schedule_claim", "status", "available_at"),
        Index("ix_schedule_history", "technician_id", "created_at"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    technician_id: Mapped[UUID] = mapped_column(ForeignKey("technicians.id", ondelete="CASCADE"))
    calendar_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("calendars.id", ondelete="SET NULL")
    )
    target_date: Mapped[date] = mapped_column(Date)
    trigger: Mapped[str] = mapped_column(String(20))
    destination: Mapped[str] = mapped_column(String(16))
    requested_destination: Mapped[str | None] = mapped_column(String(16))
    fallback_reason: Mapped[str | None] = mapped_column(String(48))
    status: Mapped[str] = mapped_column(String(16), default="PENDING")
    source_version: Mapped[str] = mapped_column(String(64))
    fingerprint: Mapped[str] = mapped_column(String(64))
    job_count: Mapped[int] = mapped_column(Integer)
    encrypted_payload: Mapped[str | None] = mapped_column(Text)
    payload_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    claim_owner: Mapped[UUID | None]
    claim_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    delivery_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    message_id: Mapped[int | None] = mapped_column(BigInteger)
    error_code: Mapped[str | None] = mapped_column(String(64))
    created_by: Mapped[UUID | None] = mapped_column(ForeignKey("managers.id", ondelete="SET NULL"))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ack_status: Mapped[str] = mapped_column(String(16), default="NOT_SENT")
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ack_token_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    ack_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    bot_id: Mapped[int] = mapped_column(BigInteger)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    private_generation: Mapped[int] = mapped_column(Integer)
    group_generation: Mapped[int] = mapped_column(Integer)
    resend_of_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("schedule_dispatches.id", ondelete="CASCADE")
    )


class ScheduleAutoDecision(Base, Timestamps):
    __tablename__ = "schedule_auto_decisions"
    technician_id: Mapped[UUID] = mapped_column(
        ForeignKey("technicians.id", ondelete="CASCADE"), primary_key=True
    )
    target_date: Mapped[date] = mapped_column(Date, primary_key=True)
    source_date: Mapped[date] = mapped_column(Date)
    state: Mapped[str] = mapped_column(String(20))
    error_code: Mapped[str | None] = mapped_column(String(64))
    retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ScheduleWorkerState(Base):
    __tablename__ = "schedule_worker_states"
    worker_id: Mapped[UUID] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String(20))
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(64))
