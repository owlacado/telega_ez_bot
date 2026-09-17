"""add Google Calendar discovery and credentials"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0a542f68aa75"
down_revision = "e7b310920001"
branch_labels = None
depends_on = None


def upgrade():

    op.create_table(
        "calendar_connections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=20), server_default="GOOGLE", nullable=False),
        sa.Column("account_key", sa.String(length=1024), nullable=False),
        sa.Column("account_label", sa.String(length=150), nullable=False),
        sa.Column("is_current", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("status", sa.String(length=25), nullable=False),
        sa.Column("generation", sa.Integer(), server_default="1", nullable=False),
        sa.Column("encrypted_refresh_token", sa.Text(), nullable=True),
        sa.Column("granted_scopes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=50), nullable=True),
        sa.Column("retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("provider = 'GOOGLE'", name=op.f("ck_calendar_connections_provider")),
        sa.CheckConstraint(
            "status != 'CONNECTED' OR (encrypted_refresh_token IS NOT NULL AND is_current)",
            name=op.f("ck_calendar_connections_connected_has_credential"),
        ),
        sa.CheckConstraint(
            "status != 'DISCONNECTED' OR encrypted_refresh_token IS NULL",
            name=op.f("ck_calendar_connections_disconnected_has_no_credential"),
        ),
        sa.CheckConstraint(
            "status IN ('CONNECTED','DISCONNECTED','REAUTH_REQUIRED','ERROR')",
            name=op.f("ck_calendar_connections_status"),
        ),
        sa.CheckConstraint("generation > 0", name=op.f("ck_calendar_connections_generation")),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["managers.id"],
            name=op.f("fk_calendar_connections_created_by_user_id_managers"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_calendar_connections")),
        sa.UniqueConstraint("account_key", name=op.f("uq_calendar_connections_account_key")),
    )
    op.create_index(
        "uq_current_google_connection",
        "calendar_connections",
        ["is_current"],
        unique=True,
        postgresql_where=sa.text("is_current"),
    )
    op.create_table(
        "google_oauth_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("state_hash", sa.String(length=64), nullable=False),
        sa.Column("manager_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("encrypted_verifier", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expected_connection_id", sa.Uuid(), nullable=True),
        sa.Column("expected_generation", sa.Integer(), nullable=True),
        sa.Column("mode", sa.String(length=12), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "mode IN ('CONNECT','RECONNECT','SWITCH')", name=op.f("ck_google_oauth_attempts_mode")
        ),
        sa.ForeignKeyConstraint(
            ["expected_connection_id"],
            ["calendar_connections.id"],
            name=op.f("fk_google_oauth_attempts_expected_connection_id_calendar_connections"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["manager_id"],
            ["managers.id"],
            name=op.f("fk_google_oauth_attempts_manager_id_managers"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["manager_sessions.id"],
            name=op.f("fk_google_oauth_attempts_session_id_manager_sessions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_google_oauth_attempts")),
        sa.UniqueConstraint("state_hash", name=op.f("uq_google_oauth_attempts_state_hash")),
    )
    op.add_column(
        "calendars",
        sa.Column("source", sa.String(length=20), server_default="LOCAL_DEMO", nullable=False),
    )
    op.add_column("calendars", sa.Column("provider_connection_id", sa.Uuid(), nullable=True))
    op.add_column(
        "calendars", sa.Column("provider_calendar_id", sa.String(length=1024), nullable=True)
    )
    op.add_column(
        "calendars",
        sa.Column("availability", sa.String(length=20), server_default="AVAILABLE", nullable=False),
    )
    op.add_column("calendars", sa.Column("timezone", sa.String(length=100), nullable=True))
    op.add_column(
        "calendars",
        sa.Column("primary", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column("calendars", sa.Column("access_role", sa.String(length=20), nullable=True))
    op.add_column("calendars", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("calendars", sa.Column("excluded_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("calendars", sa.Column("excluded_by", sa.Uuid(), nullable=True))
    op.drop_constraint(op.f("uq_calendars_name"), "calendars", type_="unique")
    op.create_index(
        op.f("ix_calendars_provider_connection_id"),
        "calendars",
        ["provider_connection_id"],
        unique=False,
    )
    op.create_unique_constraint(
        "uq_calendar_provider_identity",
        "calendars",
        ["provider_connection_id", "provider_calendar_id"],
    )
    op.create_index(
        "uq_local_demo_calendar_name",
        "calendars",
        ["name"],
        unique=True,
        postgresql_where=sa.text("source = 'LOCAL_DEMO'"),
    )
    op.create_foreign_key(
        op.f("fk_calendars_provider_connection_id_calendar_connections"),
        "calendars",
        "calendar_connections",
        ["provider_connection_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        op.f("fk_calendars_excluded_by_managers"),
        "calendars",
        "managers",
        ["excluded_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "availability", "calendars", "availability IN ('AVAILABLE','UNAVAILABLE')"
    )
    op.create_check_constraint(
        "provider_identity",
        "calendars",
        "(source = 'LOCAL_DEMO' AND provider_connection_id IS NULL "
        "AND provider_calendar_id IS NULL) "
        "OR (source = 'GOOGLE' AND provider_connection_id IS NOT NULL "
        "AND provider_calendar_id IS NOT NULL)",
    )


def downgrade():
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM calendar_connections) "
            "OR EXISTS (SELECT 1 FROM google_oauth_attempts)"
        )
    ):
        raise RuntimeError(
            "Stage 2 provider data exists; restore a pre-Stage-2 backup "
            "instead of a destructive downgrade."
        )
    op.drop_constraint(op.f("ck_calendars_provider_identity"), "calendars", type_="check")
    op.drop_constraint(op.f("ck_calendars_availability"), "calendars", type_="check")
    op.drop_constraint(op.f("fk_calendars_excluded_by_managers"), "calendars", type_="foreignkey")
    op.drop_constraint(
        op.f("fk_calendars_provider_connection_id_calendar_connections"),
        "calendars",
        type_="foreignkey",
    )
    op.drop_index(
        "uq_local_demo_calendar_name",
        table_name="calendars",
        postgresql_where=sa.text("source = 'LOCAL_DEMO'"),
    )
    op.drop_constraint("uq_calendar_provider_identity", "calendars", type_="unique")
    op.drop_index(op.f("ix_calendars_provider_connection_id"), table_name="calendars")
    op.create_unique_constraint(
        op.f("uq_calendars_name"), "calendars", ["name"], postgresql_nulls_not_distinct=False
    )
    op.drop_column("calendars", "excluded_by")
    op.drop_column("calendars", "excluded_at")
    op.drop_column("calendars", "last_seen_at")
    op.drop_column("calendars", "access_role")
    op.drop_column("calendars", "primary")
    op.drop_column("calendars", "timezone")
    op.drop_column("calendars", "availability")
    op.drop_column("calendars", "provider_calendar_id")
    op.drop_column("calendars", "provider_connection_id")
    op.drop_column("calendars", "source")
    op.drop_table("google_oauth_attempts")
    op.drop_index(
        "uq_current_google_connection",
        table_name="calendar_connections",
        postgresql_where=sa.text("is_current"),
    )
    op.drop_table("calendar_connections")
