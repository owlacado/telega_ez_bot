import uuid

from sqlalchemy import CheckConstraint, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hub.core.database import Base, Timestamps


class Technician(Timestamps, Base):
    __tablename__ = "technicians"
    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE', 'INACTIVE')", name="valid_status"),
        CheckConstraint(
            "length(trim(first_name)) > 0 AND length(trim(last_name)) > 0", name="nonempty_name"
        ),
        CheckConstraint("ssn_last4 IS NULL OR ssn_last4 ~ '^[0-9]{4}$'", name="ssn_last4"),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    photo_url: Mapped[str | None] = mapped_column(String(2048))
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE", server_default="ACTIVE")
    driver_license_id: Mapped[str | None] = mapped_column(String(100))
    ssn_last4: Mapped[str | None] = mapped_column(String(4))
    assignments = relationship(
        "CalendarAssignment", lazy="selectin", cascade="all, delete-orphan", passive_deletes=True
    )
    telegram = relationship(
        "TelegramBinding",
        lazy="selectin",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    gps = relationship(
        "GpsBinding",
        lazy="selectin",
        uselist=False,
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
