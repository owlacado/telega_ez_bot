"""add Telegram invitation and worker persistence"""

import sqlalchemy as sa
from alembic import op

revision = "4344e0e76774"
down_revision = "5644c8fc030a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "telegram_processed_updates",
        sa.Column("bot_id", sa.BigInteger(), nullable=False),
        sa.Column("update_id", sa.BigInteger(), nullable=False),
        sa.Column("outcome", sa.String(length=40), nullable=False),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("bot_id", "update_id", name=op.f("pk_telegram_processed_updates")),
    )
    op.create_table(
        "telegram_worker_states",
        sa.Column("bot_id", sa.BigInteger(), nullable=False),
        sa.Column("next_update_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("bot_id", name=op.f("pk_telegram_worker_states")),
    )
    op.create_table(
        "telegram_invitations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("technician_id", sa.Uuid(), nullable=False),
        sa.Column("bot_id", sa.BigInteger(), nullable=False),
        sa.Column("purpose", sa.String(length=20), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expected_generation", sa.Integer(), nullable=False),
        sa.Column("expected_private_generation", sa.Integer(), nullable=False),
        sa.Column("created_by_manager_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by_manager_id", sa.Uuid(), nullable=True),
        sa.Column("candidate_user_id", sa.BigInteger(), nullable=True),
        sa.Column("candidate_display_name", sa.String(length=200), nullable=True),
        sa.Column("candidate_username", sa.String(length=64), nullable=True),
        sa.Column("candidate_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("candidate_chat_title", sa.String(length=200), nullable=True),
        sa.Column("initiator_admin", sa.Boolean(), nullable=True),
        sa.Column("bot_admin", sa.Boolean(), nullable=True),
        sa.Column("technician_member", sa.Boolean(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("setup_error", sa.String(length=50), nullable=True),
        sa.CheckConstraint(
            "purpose IN ('PRIVATE_ACCOUNT', 'WORK_GROUP')",
            name=op.f("ck_telegram_invitations_purpose"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_manager_id"],
            ["managers.id"],
            name=op.f("fk_telegram_invitations_created_by_manager_id_managers"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_manager_id"],
            ["managers.id"],
            name=op.f("fk_telegram_invitations_reviewed_by_manager_id_managers"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["technician_id"],
            ["technicians.id"],
            name=op.f("fk_telegram_invitations_technician_id_technicians"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_telegram_invitations")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_telegram_invitations_token_hash")),
    )
    op.create_index(
        op.f("ix_telegram_invitations_technician_id"),
        "telegram_invitations",
        ["technician_id"],
        unique=False,
    )
    op.create_index(
        "uq_open_telegram_invitation",
        "telegram_invitations",
        ["technician_id", "purpose"],
        unique=True,
        postgresql_where=sa.text("closed_at IS NULL"),
    )
    op.create_table(
        "telegram_outbox",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("technician_id", sa.Uuid(), nullable=False),
        sa.Column("invitation_id", sa.Uuid(), nullable=True),
        sa.Column("bot_id", sa.BigInteger(), nullable=False),
        sa.Column("destination", sa.String(length=20), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("private_generation", sa.Integer(), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=True),
        sa.Column("state", sa.String(length=20), server_default="QUEUED", nullable=False),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_message_id", sa.BigInteger(), nullable=True),
        sa.CheckConstraint(
            "destination IN ('PRIVATE_ACCOUNT','WORK_GROUP')",
            name=op.f("ck_telegram_outbox_destination"),
        ),
        sa.CheckConstraint(
            "kind IN ('APPROVED','TEST','VERIFY_GROUP')", name=op.f("ck_telegram_outbox_kind")
        ),
        sa.CheckConstraint(
            "state IN ('QUEUED','PROCESSING','SENT','FAILED','UNKNOWN','CANCELLED')",
            name=op.f("ck_telegram_outbox_state"),
        ),
        sa.ForeignKeyConstraint(
            ["invitation_id"],
            ["telegram_invitations.id"],
            name=op.f("fk_telegram_outbox_invitation_id_telegram_invitations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"],
            ["managers.id"],
            name=op.f("fk_telegram_outbox_requested_by_managers"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["technician_id"],
            ["technicians.id"],
            name=op.f("fk_telegram_outbox_technician_id_technicians"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_telegram_outbox")),
    )
    op.create_index(
        op.f("ix_telegram_outbox_technician_id"), "telegram_outbox", ["technician_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_telegram_outbox_technician_id"), table_name="telegram_outbox")
    op.drop_table("telegram_outbox")
    op.drop_index(
        "uq_open_telegram_invitation",
        table_name="telegram_invitations",
        postgresql_where=sa.text("closed_at IS NULL"),
    )
    op.drop_index(op.f("ix_telegram_invitations_technician_id"), table_name="telegram_invitations")
    op.drop_table("telegram_invitations")
    op.drop_table("telegram_worker_states")
    op.drop_table("telegram_processed_updates")
