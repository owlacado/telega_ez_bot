import uuid

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hub.core.database import Base, Timestamps


class Calendar(Timestamps, Base):
    __tablename__ = "calendars"
    __table_args__ = (CheckConstraint("length(btrim(name)) > 0", name="name_not_empty"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(150), unique=True)
    # A local calendar record; external Google identifiers are intentionally absent.


class CalendarAssignment(Timestamps, Base):
    __tablename__ = "calendar_assignments"
    __table_args__ = (
        CheckConstraint("NOT is_active OR calendar_id IS NOT NULL", name="active_has_calendar"),
        Index(
            "uq_active_technician_calendar",
            "technician_id",
            unique=True,
            postgresql_where=text("is_active"),
        ),
        Index(
            "uq_active_calendar_technician",
            "calendar_id",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    technician_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("technicians.id", ondelete="CASCADE"), index=True
    )
    calendar_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("calendars.id", ondelete="SET NULL"), index=True
    )
    calendar_name: Mapped[str] = mapped_column(String(150))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    calendar = relationship("Calendar", lazy="selectin")
