"""add manager authentication and audit"""

import sqlalchemy as sa
from alembic import op

revision = "b89e091fa280"
down_revision = "863590d3075e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "managers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("username", sa.String(length=100), nullable=False),
        sa.Column("password_hash", sa.String(length=256), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_managers")),
        sa.UniqueConstraint("username", name=op.f("uq_managers_username")),
    )
    op.create_table(
        "rate_buckets",
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key_hash", name=op.f("pk_rate_buckets")),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("actor_kind", sa.String(length=20), nullable=False),
        sa.Column("action", sa.String(length=50), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=True),
        sa.Column("outcome", sa.String(length=50), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["managers.id"],
            name=op.f("fk_audit_events_actor_id_managers"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
    )
    op.create_index(op.f("ix_audit_events_target_id"), "audit_events", ["target_id"], unique=False)
    op.create_table(
        "manager_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("manager_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["manager_id"],
            ["managers.id"],
            name=op.f("fk_manager_sessions_manager_id_managers"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_manager_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_manager_sessions_token_hash")),
    )
    op.create_index(
        op.f("ix_manager_sessions_manager_id"), "manager_sessions", ["manager_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_manager_sessions_manager_id"), table_name="manager_sessions")
    op.drop_table("manager_sessions")
    op.drop_index(op.f("ix_audit_events_target_id"), table_name="audit_events")
    op.drop_table("audit_events")
    op.drop_table("rate_buckets")
    op.drop_table("managers")
