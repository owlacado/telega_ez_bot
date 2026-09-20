import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from hub.core.database import Base, Timestamps


class AccountingMirrorTarget(Timestamps, Base):
    __tablename__ = "accounting_mirror_targets"
    __table_args__ = (
        CheckConstraint("kind IN ('INDIVIDUAL','ALL_TECH')", name="kind"),
        CheckConstraint(
            "(kind = 'INDIVIDUAL' AND technician_id IS NOT NULL) OR "
            "(kind = 'ALL_TECH' AND technician_id IS NULL)",
            name="kind_technician",
        ),
        CheckConstraint("generation > 0", name="generation"),
        Index(
            "uq_accounting_mirror_individual_target",
            "technician_id",
            unique=True,
            postgresql_where=text("kind = 'INDIVIDUAL'"),
        ),
        Index(
            "uq_accounting_mirror_all_tech_target",
            "kind",
            unique=True,
            postgresql_where=text("kind = 'ALL_TECH'"),
        ),
        Index("uq_accounting_mirror_spreadsheet_target", "spreadsheet_id", unique=True),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(20))
    technician_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("technicians.id", ondelete="CASCADE")
    )
    google_connection_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("calendar_connections.id", ondelete="CASCADE")
    )
    spreadsheet_id: Mapped[str] = mapped_column(String(200))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    generation: Mapped[int] = mapped_column(Integer, default=1, server_default="1")


class AccountingMirrorRefresh(Timestamps, Base):
    __tablename__ = "accounting_mirror_refreshes"
    __table_args__ = (
        CheckConstraint("status IN ('PENDING','PROCESSING','SUCCEEDED','FAILED')", name="status"),
        CheckConstraint("extract(isodow from week_start) = 1", name="week_start_monday"),
        CheckConstraint("requested_generation > 0", name="requested_generation"),
        CheckConstraint("completed_generation >= 0", name="completed_generation_nonnegative"),
        CheckConstraint("completed_generation <= requested_generation", name="completed_not_ahead"),
        CheckConstraint("attempt_count >= 0", name="attempt_count_nonnegative"),
        CheckConstraint("owned_rows >= 0 AND owned_columns >= 0", name="owned_extent_nonnegative"),
        CheckConstraint(
            "(status = 'PROCESSING' AND claim_token IS NOT NULL AND claimed_at IS NOT NULL "
            "AND lease_until IS NOT NULL) OR (status != 'PROCESSING' AND claim_token IS NULL "
            "AND claimed_at IS NULL AND lease_until IS NULL)",
            name="claim_metadata",
        ),
        CheckConstraint(
            "claimed_at IS NULL OR lease_until > claimed_at",
            name="lease_order",
        ),
        CheckConstraint(
            "google_sheet_id IS NULL OR google_sheet_id >= 0",
            name="google_sheet_id_nonnegative",
        ),
        CheckConstraint(
            "(last_success_at IS NULL AND last_successful_fingerprint IS NULL "
            "AND successful_target_generation IS NULL "
            "AND successful_connection_generation IS NULL) OR "
            "(last_success_at IS NOT NULL AND last_successful_fingerprint IS NOT NULL "
            "AND successful_target_generation > 0 "
            "AND successful_connection_generation > 0 AND completed_generation > 0)",
            name="success_metadata",
        ),
        CheckConstraint(
            "status != 'SUCCEEDED' OR "
            "(completed_generation = requested_generation AND last_success_at IS NOT NULL)",
            name="succeeded_current",
        ),
        Index("uq_accounting_mirror_target_week", "target_id", "week_start", unique=True),
        Index("ix_accounting_mirror_refresh_claim", "status", "retry_at", "lease_until"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    target_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounting_mirror_targets.id", ondelete="CASCADE")
    )
    week_start: Mapped[date] = mapped_column(Date)
    requested_generation: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    completed_generation: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    status: Mapped[str] = mapped_column(String(20), default="PENDING", server_default="PENDING")
    claim_token: Mapped[uuid.UUID | None] = mapped_column()
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    provider_attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(50))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_successful_fingerprint: Mapped[str | None] = mapped_column(String(64))
    successful_target_generation: Mapped[int | None] = mapped_column(Integer)
    successful_connection_generation: Mapped[int | None] = mapped_column(Integer)
    google_sheet_id: Mapped[int | None] = mapped_column(Integer)
    owned_rows: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    owned_columns: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class AccountingMirrorWorkerState(Base):
    __tablename__ = "accounting_mirror_worker_states"
    __table_args__ = (
        CheckConstraint("status IN ('STARTING','RUNNING','STOPPED','ERROR')", name="status"),
    )
    worker_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String(20))
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(50))
