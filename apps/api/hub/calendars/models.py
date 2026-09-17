import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from hub.core.database import Base, Timestamps


class Calendar(Timestamps, Base):
    __tablename__ = "calendars"
    __table_args__ = (
        CheckConstraint("length(btrim(name)) > 0", name="name_not_empty"),
        CheckConstraint("availability IN ('AVAILABLE','UNAVAILABLE')", name="availability"),
        CheckConstraint(
            "(source = 'LOCAL_DEMO' AND provider_connection_id IS NULL "
            "AND provider_calendar_id IS NULL) "
            "OR (source = 'GOOGLE' AND provider_connection_id IS NOT NULL "
            "AND provider_calendar_id IS NOT NULL)",
            name="provider_identity",
        ),
        UniqueConstraint(
            "provider_connection_id", "provider_calendar_id", name="uq_calendar_provider_identity"
        ),
        Index(
            "uq_local_demo_calendar_name",
            "name",
            unique=True,
            postgresql_where=text("source = 'LOCAL_DEMO'"),
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(150))
    source: Mapped[str] = mapped_column(
        String(20), default="LOCAL_DEMO", server_default="LOCAL_DEMO"
    )
    provider_connection_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("calendar_connections.id", ondelete="RESTRICT"), index=True
    )
    provider_calendar_id: Mapped[str | None] = mapped_column(String(1024))
    availability: Mapped[str] = mapped_column(
        String(20), default="AVAILABLE", server_default="AVAILABLE"
    )
    timezone: Mapped[str | None] = mapped_column(String(100))
    primary: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    access_role: Mapped[str | None] = mapped_column(String(20))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    excluded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    excluded_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("managers.id", ondelete="SET NULL")
    )


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
