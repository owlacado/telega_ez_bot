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
    )
    technician_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("technicians.id", ondelete="CASCADE"), primary_key=True
    )
    provider: Mapped[str] = mapped_column(String(30), default="NONE", server_default="NONE")
    status: Mapped[str] = mapped_column(
        String(20), default="NOT_CONNECTED", server_default="NOT_CONNECTED"
    )
    # No share token or secret column exists in Stage 0.
