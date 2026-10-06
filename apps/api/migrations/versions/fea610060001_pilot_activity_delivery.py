"""Durable business activity references and schedule supersession."""

import sqlalchemy as sa
from alembic import op

revision = "fea610060001"
down_revision = "fda609200001"
branch_labels = None
depends_on = None


def upgrade():
    for column, table in [("report_id", "work_reports"), ("expense_id", "technician_expenses")]:
        op.add_column("telegram_outbox", sa.Column(column, sa.Uuid(), nullable=True))
        op.create_foreign_key(
            op.f(f"fk_telegram_outbox_{column}_{table}"),
            "telegram_outbox",
            table,
            [column],
            ["id"],
            ondelete="RESTRICT",
        )
        op.create_unique_constraint(
            op.f(f"uq_telegram_outbox_{column}"), "telegram_outbox", [column]
        )
    for column in ["activity_chat_id", "activity_user_id"]:
        op.add_column("telegram_outbox", sa.Column(column, sa.BigInteger(), nullable=True))
    op.drop_constraint(op.f("ck_telegram_outbox_kind"), "telegram_outbox", type_="check")
    op.create_check_constraint(
        op.f("ck_telegram_outbox_kind"),
        "telegram_outbox",
        "kind IN ('APPROVED','TEST','VERIFY_GROUP','WORK_REPORT','EXPENSE')",
    )
    op.create_check_constraint(
        op.f("ck_telegram_outbox_activity_reference"),
        "telegram_outbox",
        "(kind = 'WORK_REPORT' AND report_id IS NOT NULL AND expense_id IS NULL) OR "
        "(kind = 'EXPENSE' AND expense_id IS NOT NULL AND report_id IS NULL) OR "
        "(kind NOT IN ('WORK_REPORT','EXPENSE') AND report_id IS NULL AND expense_id IS NULL)",
    )
    op.create_check_constraint(
        op.f("ck_telegram_outbox_activity_group"),
        "telegram_outbox",
        "kind NOT IN ('WORK_REPORT','EXPENSE') OR destination = 'WORK_GROUP'",
    )
    op.add_column("schedule_dispatches", sa.Column("superseded_at", sa.DateTime(timezone=True)))
    # Existing receipt/history stays intact. Ties use the same deterministic UI order.
    op.execute("""UPDATE schedule_dispatches older SET superseded_at = newer.created_at
        FROM (SELECT DISTINCT ON (technician_id, target_date)
                     id, technician_id, target_date, created_at
              FROM schedule_dispatches
              ORDER BY technician_id, target_date, created_at DESC, id DESC) newer
        WHERE older.technician_id = newer.technician_id AND older.target_date = newer.target_date
          AND older.id <> newer.id""")


def downgrade():
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM telegram_outbox WHERE kind IN ('WORK_REPORT','EXPENSE'))
         OR EXISTS (SELECT 1 FROM schedule_dispatches WHERE superseded_at IS NOT NULL)
      THEN RAISE EXCEPTION 'PILOT_ACTIVITY_HISTORY_ROLLBACK_REFUSED'; END IF;
    END $$""")
    op.drop_column("schedule_dispatches", "superseded_at")
    for name in ["activity_group", "activity_reference", "kind"]:
        op.drop_constraint(op.f("ck_telegram_outbox_" + name), "telegram_outbox", type_="check")
    op.create_check_constraint(
        op.f("ck_telegram_outbox_kind"),
        "telegram_outbox",
        "kind IN ('APPROVED','TEST','VERIFY_GROUP')",
    )
    for column in ["activity_user_id", "activity_chat_id", "expense_id", "report_id"]:
        op.drop_column("telegram_outbox", column)
