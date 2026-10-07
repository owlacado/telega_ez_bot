"""Add nullable singleton polling lease, preserving durable offsets and history."""

import sqlalchemy as sa
from alembic import op

revision = "ffb610060001"
down_revision = "fea610060001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("telegram_worker_states", sa.Column("poll_owner", sa.Uuid(), nullable=True))
    op.add_column(
        "telegram_worker_states",
        sa.Column("poll_lease_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_telegram_worker_states_poll_lease_pair"),
        "telegram_worker_states",
        "(poll_owner IS NULL) = (poll_lease_until IS NULL)",
    )


def downgrade():
    op.drop_constraint(
        op.f("ck_telegram_worker_states_poll_lease_pair"), "telegram_worker_states", type_="check"
    )
    op.drop_column("telegram_worker_states", "poll_lease_until")
    op.drop_column("telegram_worker_states", "poll_owner")
