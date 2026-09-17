"""Bind pending Google account replacement to the confirmed catalog impact."""

import sqlalchemy as sa
from alembic import op

revision = "b2917d804e12"
down_revision = "0a542f68aa75"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "google_oauth_attempts", sa.Column("expected_impact_version", sa.String(64), nullable=True)
    )


def downgrade():
    # Old binaries cannot enforce this confirmation. Burn pending switches first.
    op.execute(
        "UPDATE google_oauth_attempts SET consumed_at = now(), encrypted_verifier = NULL "
        "WHERE mode = 'SWITCH' AND consumed_at IS NULL"
    )
    op.drop_column("google_oauth_attempts", "expected_impact_version")
