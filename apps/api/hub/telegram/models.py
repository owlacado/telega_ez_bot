import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from hub.core.database import Base


class TelegramInvitation(Base):
    __tablename__ = "telegram_invitations"
    __table_args__ = (
        CheckConstraint("purpose IN ('PRIVATE_TELEGRAM', 'WORK_GROUP')", name="purpose"),
        Index(
            "uq_open_telegram_invitation",
            "technician_id",
            "purpose",
            unique=True,
            postgresql_where=text("closed_at IS NULL"),
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    technician_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("technicians.id", ondelete="CASCADE"), index=True
    )
    automatic: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    bot_id: Mapped[int] = mapped_column(BigInteger)
    purpose: Mapped[str] = mapped_column(String(20))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expected_generation: Mapped[int] = mapped_column(Integer)
    expected_private_generation: Mapped[int] = mapped_column(Integer)
    created_by_manager_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("managers.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by_manager_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("managers.id", ondelete="SET NULL")
    )
    candidate_user_id: Mapped[int | None] = mapped_column(BigInteger)
    candidate_display_name: Mapped[str | None] = mapped_column(String(200))
    candidate_username: Mapped[str | None] = mapped_column(String(64))
    candidate_chat_id: Mapped[int | None] = mapped_column(BigInteger)
    candidate_chat_title: Mapped[str | None] = mapped_column(String(200))
    initiator_admin: Mapped[bool | None] = mapped_column(Boolean)
    bot_admin: Mapped[bool | None] = mapped_column(Boolean)
    technician_member: Mapped[bool | None] = mapped_column(Boolean)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    setup_error: Mapped[str | None] = mapped_column(String(50))


class TelegramOutbox(Base):
    __tablename__ = "telegram_outbox"
    __table_args__ = (
        CheckConstraint(
            "state IN ('QUEUED','PROCESSING','SENT','FAILED','UNKNOWN','CANCELLED')", name="state"
        ),
        CheckConstraint("destination IN ('PRIVATE_TELEGRAM','WORK_GROUP')", name="destination"),
        CheckConstraint("kind IN ('APPROVED','TEST','VERIFY_GROUP')", name="kind"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    technician_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("technicians.id", ondelete="CASCADE"), index=True
    )
    invitation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("telegram_invitations.id", ondelete="CASCADE")
    )
    bot_id: Mapped[int] = mapped_column(BigInteger)
    destination: Mapped[str] = mapped_column(String(20))
    kind: Mapped[str] = mapped_column(String(20))
    generation: Mapped[int] = mapped_column(Integer)
    private_generation: Mapped[int] = mapped_column(Integer)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("managers.id", ondelete="SET NULL")
    )
    state: Mapped[str] = mapped_column(String(20), default="QUEUED", server_default="QUEUED")
    error_code: Mapped[str | None] = mapped_column(String(50))
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_message_id: Mapped[int | None] = mapped_column(BigInteger)


class TelegramWorkerState(Base):
    __tablename__ = "telegram_worker_states"
    bot_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    next_update_id: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(30), default="STOPPED")
    error_code: Mapped[str | None] = mapped_column(String(50))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TelegramProcessedUpdate(Base):
    __tablename__ = "telegram_processed_updates"
    bot_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    update_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    outcome: Mapped[str] = mapped_column(String(40))
    processed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
