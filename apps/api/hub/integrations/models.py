import uuid

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from hub.core.database import Base, Timestamps

CONNECTION_STATES = "('NOT_CONNECTED', 'PENDING', 'CONNECTED', 'ERROR')"


class TelegramBinding(Timestamps, Base):
    __tablename__ = "telegram_bindings"
    __table_args__ = (
        CheckConstraint(f"private_status IN {CONNECTION_STATES}", name="private_status"),
        CheckConstraint(f"group_status IN {CONNECTION_STATES}", name="group_status"),
        CheckConstraint(
            "private_generation >= 0 AND group_generation >= 0", name="nonnegative_generations"
        ),
        CheckConstraint(
            "private_availability IN "
            "('UNKNOWN','AVAILABLE','BLOCKED','UNAVAILABLE')",
            name="private_availability",
        ),
        CheckConstraint(
            "group_availability IN "
            "('UNKNOWN','AVAILABLE','UNAVAILABLE','REVALIDATION_REQUIRED','MIGRATION_CONFLICT')",
            name="group_availability",
        ),
        CheckConstraint(
            "private_status != 'CONNECTED' OR "
            "(telegram_user_id IS NOT NULL AND bot_id IS NOT NULL "
            "AND private_generation > 0)",
            name="private_connected_identity",
        ),
        CheckConstraint(
            "group_status != 'CONNECTED' OR "
            "(telegram_group_chat_id IS NOT NULL AND bot_id IS NOT NULL "
            "AND group_generation > 0)",
            name="group_connected_identity",
        ),
        CheckConstraint(
            "private_availability != 'AVAILABLE' OR private_status = 'CONNECTED'",
            name="private_available_connected",
        ),
        CheckConstraint(
            "group_availability != 'AVAILABLE' OR "
            "(group_status = 'CONNECTED' AND private_status = 'CONNECTED' "
            "AND group_private_generation = private_generation)",
            name="group_available_current_private",
        ),
    )
    technician_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("technicians.id", ondelete="CASCADE"), primary_key=True
    )
    private_status: Mapped[str] = mapped_column(
        String(20), default="NOT_CONNECTED", server_default="NOT_CONNECTED"
    )
    telegram_user_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    group_status: Mapped[str] = mapped_column(
        String(20), default="NOT_CONNECTED", server_default="NOT_CONNECTED"
    )
    telegram_group_chat_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)

    bot_id: Mapped[int | None] = mapped_column(BigInteger)
    private_generation: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    group_generation: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    group_private_generation: Mapped[int | None] = mapped_column(Integer)
    private_availability: Mapped[str] = mapped_column(
        String(30), default="UNKNOWN", server_default="UNKNOWN"
    )
    group_availability: Mapped[str] = mapped_column(
        String(30), default="UNKNOWN", server_default="UNKNOWN"
    )
    private_display_name: Mapped[str | None] = mapped_column(String(200))
    private_username: Mapped[str | None] = mapped_column(String(64))
    group_title: Mapped[str | None] = mapped_column(String(200))
    group_actor_id: Mapped[int | None] = mapped_column(BigInteger)


class GpsBinding(Timestamps, Base):
    __tablename__ = "gps_bindings"
    __table_args__ = (
        CheckConstraint("provider IN ('NONE', 'MOTOWATCHDOG_SHARE')", name="provider"),
        CheckConstraint(f"status IN {CONNECTION_STATES}", name="status"),
        CheckConstraint(
            "(provider = 'NONE' AND status = 'NOT_CONNECTED') OR "
            "(provider = 'MOTOWATCHDOG_SHARE' AND status != 'NOT_CONNECTED')",
            name="provider_status",
        ),
    )
    technician_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("technicians.id", ondelete="CASCADE"), primary_key=True
    )
    provider: Mapped[str] = mapped_column(String(30), default="NONE", server_default="NONE")
    status: Mapped[str] = mapped_column(
        String(20), default="NOT_CONNECTED", server_default="NOT_CONNECTED"
    )
    # No share token or secret column exists in Stage 0.
