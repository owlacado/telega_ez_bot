import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from hub.core.database import Base, Timestamps


class CalendarConnection(Timestamps, Base):
    __tablename__ = "calendar_connections"
    __table_args__ = (
        CheckConstraint("provider = 'GOOGLE'", name="provider"),
        CheckConstraint(
            "status IN ('CONNECTED','DISCONNECTED','REAUTH_REQUIRED','ERROR')", name="status"
        ),
        CheckConstraint("generation > 0", name="generation"),
        CheckConstraint(
            "status != 'DISCONNECTED' OR encrypted_refresh_token IS NULL",
            name="disconnected_has_no_credential",
        ),
        CheckConstraint(
            "status != 'CONNECTED' OR (encrypted_refresh_token IS NOT NULL AND is_current)",
            name="connected_has_credential",
        ),
        Index(
            "uq_current_google_connection",
            "is_current",
            unique=True,
            postgresql_where=text("is_current"),
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(String(20), default="GOOGLE", server_default="GOOGLE")
    account_key: Mapped[str] = mapped_column(String(1024), unique=True)
    account_label: Mapped[str] = mapped_column(String(150), default="Google Calendar account")
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    status: Mapped[str] = mapped_column(String(25), default="CONNECTED")
    generation: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    encrypted_refresh_token: Mapped[str | None] = mapped_column(Text)
    granted_scopes: Mapped[list[str]] = mapped_column(JSONB, default=list)
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(50))
    retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("managers.id", ondelete="SET NULL")
    )


class GoogleOAuthAttempt(Timestamps, Base):
    __tablename__ = "google_oauth_attempts"
    __table_args__ = (CheckConstraint("mode IN ('CONNECT','RECONNECT','SWITCH')", name="mode"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    state_hash: Mapped[str] = mapped_column(String(64), unique=True)
    manager_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("managers.id", ondelete="CASCADE"))
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("manager_sessions.id", ondelete="CASCADE")
    )
    encrypted_verifier: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expected_connection_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("calendar_connections.id", ondelete="CASCADE")
    )
    expected_generation: Mapped[int | None] = mapped_column(Integer)
    mode: Mapped[str] = mapped_column(String(12))
    request_event_access: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    expected_impact_version: Mapped[str | None] = mapped_column(String(64))
