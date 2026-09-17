"""Bind incremental event access to the OAuth attempt."""

import sqlalchemy as sa
from alembic import op

revision = "c3e410a20917"
down_revision = "b2917d804e12"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "google_oauth_attempts",
        sa.Column("request_event_access", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade():
    op.execute(
        "UPDATE google_oauth_attempts SET consumed_at = now(), encrypted_verifier = NULL "
        "WHERE request_event_access AND consumed_at IS NULL"
    )
    op.drop_column("google_oauth_attempts", "request_event_access")
