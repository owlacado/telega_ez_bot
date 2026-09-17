"""add secure Telegram invitations worker and delivery"""

import sqlalchemy as sa
from alembic import op

revision = "5644c8fc030a"
down_revision = "b89e091fa280"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("telegram_bindings", sa.Column("bot_id", sa.BigInteger(), nullable=True))
    op.add_column(
        "telegram_bindings",
        sa.Column("private_generation", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "telegram_bindings",
        sa.Column("group_generation", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "telegram_bindings", sa.Column("group_private_generation", sa.Integer(), nullable=True)
    )
    op.add_column(
        "telegram_bindings",
        sa.Column(
            "private_availability", sa.String(length=30), server_default="UNKNOWN", nullable=False
        ),
    )
    op.add_column(
        "telegram_bindings",
        sa.Column(
            "group_availability", sa.String(length=30), server_default="UNKNOWN", nullable=False
        ),
    )
    op.add_column(
        "telegram_bindings", sa.Column("private_display_name", sa.String(length=200), nullable=True)
    )
    op.add_column(
        "telegram_bindings", sa.Column("private_username", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "telegram_bindings", sa.Column("group_title", sa.String(length=200), nullable=True)
    )
    op.add_column("telegram_bindings", sa.Column("group_actor_id", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("telegram_bindings", "group_actor_id")
    op.drop_column("telegram_bindings", "group_title")
    op.drop_column("telegram_bindings", "private_username")
    op.drop_column("telegram_bindings", "private_display_name")
    op.drop_column("telegram_bindings", "group_availability")
    op.drop_column("telegram_bindings", "private_availability")
    op.drop_column("telegram_bindings", "group_private_generation")
    op.drop_column("telegram_bindings", "group_generation")
    op.drop_column("telegram_bindings", "private_generation")
    op.drop_column("telegram_bindings", "bot_id")
