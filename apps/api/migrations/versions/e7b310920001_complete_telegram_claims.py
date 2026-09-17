"""Preserve existing review invitations; new invitations connect on verified claim."""

import sqlalchemy as sa
from alembic import op

revision = "e7b310920001"
down_revision = "d6c2f8a14001"
branch_labels = None
depends_on = None


def purpose(old, new):
    for table, column, constraint in [
        ("telegram_invitations", "purpose", "ck_telegram_invitations_purpose"),
        ("telegram_outbox", "destination", "ck_telegram_outbox_destination"),
    ]:
        op.drop_constraint(op.f(constraint), table, type_="check")
        op.execute(
            sa.text(f"UPDATE {table} SET {column}=:new WHERE {column}=:old").bindparams(
                new=new, old=old
            )
        )
        op.create_check_constraint(op.f(constraint), table, f"{column} IN ('{new}', 'WORK_GROUP')")


def upgrade():
    op.add_column(
        "telegram_invitations",
        sa.Column("automatic", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("telegram_invitations", "automatic", server_default=sa.true())
    purpose("PRIVATE_ACCOUNT", "PRIVATE_TELEGRAM")


def downgrade():
    purpose("PRIVATE_TELEGRAM", "PRIVATE_ACCOUNT")
    op.drop_column("telegram_invitations", "automatic")
