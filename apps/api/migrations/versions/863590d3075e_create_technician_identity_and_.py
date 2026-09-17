"""create technician identity and integration bindings"""

import sqlalchemy as sa
from alembic import op

revision = "863590d3075e"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "calendars",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_calendars")),
        sa.UniqueConstraint("name", name=op.f("uq_calendars_name")),
    )
    op.create_table(
        "technicians",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("first_name", sa.String(length=100), nullable=False),
        sa.Column("last_name", sa.String(length=100), nullable=False),
        sa.Column("photo_url", sa.String(length=2048), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="ACTIVE", nullable=False),
        sa.Column("driver_license_id", sa.String(length=100), nullable=True),
        sa.Column("ssn_last4", sa.String(length=4), nullable=True),
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
            "ssn_last4 IS NULL OR ssn_last4 ~ '^[0-9]{4}$'", name=op.f("ck_technicians_ssn_last4")
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'INACTIVE')", name=op.f("ck_technicians_valid_status")
        ),
        sa.CheckConstraint(
            "length(trim(first_name)) > 0 AND length(trim(last_name)) > 0",
            name=op.f("ck_technicians_nonempty_name"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_technicians")),
    )
    op.create_table(
        "calendar_assignments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("technician_id", sa.Uuid(), nullable=False),
        sa.Column("calendar_id", sa.Uuid(), nullable=True),
        sa.Column("calendar_name", sa.String(length=150), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["calendar_id"],
            ["calendars.id"],
            name=op.f("fk_calendar_assignments_calendar_id_calendars"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["technician_id"],
            ["technicians.id"],
            name=op.f("fk_calendar_assignments_technician_id_technicians"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_calendar_assignments")),
    )
    op.create_index(
        op.f("ix_calendar_assignments_calendar_id"),
        "calendar_assignments",
        ["calendar_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_calendar_assignments_technician_id"),
        "calendar_assignments",
        ["technician_id"],
        unique=False,
    )
    op.create_index(
        "uq_active_calendar_technician",
        "calendar_assignments",
        ["calendar_id"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
    op.create_index(
        "uq_active_technician_calendar",
        "calendar_assignments",
        ["technician_id"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
    op.create_table(
        "gps_bindings",
        sa.Column("technician_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=30), server_default="NONE", nullable=False),
        sa.Column("status", sa.String(length=20), server_default="NOT_CONNECTED", nullable=False),
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
            "provider IN ('NONE', 'MOTOWATCHDOG_SHARE')", name=op.f("ck_gps_bindings_provider")
        ),
        sa.CheckConstraint(
            "status IN ('NOT_CONNECTED', 'PENDING', 'CONNECTED', 'ERROR')",
            name=op.f("ck_gps_bindings_status"),
        ),
        sa.ForeignKeyConstraint(
            ["technician_id"],
            ["technicians.id"],
            name=op.f("fk_gps_bindings_technician_id_technicians"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("technician_id", name=op.f("pk_gps_bindings")),
    )
    op.create_table(
        "telegram_bindings",
        sa.Column("technician_id", sa.Uuid(), nullable=False),
        sa.Column(
            "private_status", sa.String(length=20), server_default="NOT_CONNECTED", nullable=False
        ),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "group_status", sa.String(length=20), server_default="NOT_CONNECTED", nullable=False
        ),
        sa.Column("telegram_group_chat_id", sa.BigInteger(), nullable=True),
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
            "group_status IN ('NOT_CONNECTED', 'PENDING', 'CONNECTED', 'ERROR')",
            name=op.f("ck_telegram_bindings_group_status"),
        ),
        sa.CheckConstraint(
            "private_status IN ('NOT_CONNECTED', 'PENDING', 'CONNECTED', 'ERROR')",
            name=op.f("ck_telegram_bindings_private_status"),
        ),
        sa.ForeignKeyConstraint(
            ["technician_id"],
            ["technicians.id"],
            name=op.f("fk_telegram_bindings_technician_id_technicians"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("technician_id", name=op.f("pk_telegram_bindings")),
        sa.UniqueConstraint(
            "telegram_group_chat_id", name=op.f("uq_telegram_bindings_telegram_group_chat_id")
        ),
        sa.UniqueConstraint("telegram_user_id", name=op.f("uq_telegram_bindings_telegram_user_id")),
    )


def downgrade() -> None:
    op.drop_table("telegram_bindings")
    op.drop_table("gps_bindings")
    op.drop_index(
        "uq_active_technician_calendar",
        table_name="calendar_assignments",
        postgresql_where=sa.text("is_active"),
    )
    op.drop_index(
        "uq_active_calendar_technician",
        table_name="calendar_assignments",
        postgresql_where=sa.text("is_active"),
    )
    op.drop_index(op.f("ix_calendar_assignments_technician_id"), table_name="calendar_assignments")
    op.drop_index(op.f("ix_calendar_assignments_calendar_id"), table_name="calendar_assignments")
    op.drop_table("calendar_assignments")
    op.drop_table("technicians")
    op.drop_table("calendars")
