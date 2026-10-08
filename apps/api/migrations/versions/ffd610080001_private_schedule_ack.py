"""Private exact schedule ACK and durable daily/confirmation activity intents."""

import sqlalchemy as sa
from alembic import op

revision = "ffd610080001"
down_revision = "ffc610080001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "schedule_dispatches",
        sa.Column(
            "private_ack_required", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )
    op.add_column("schedule_dispatches", sa.Column("ack_message_id", sa.BigInteger()))
    op.create_check_constraint(
        op.f("ck_schedule_dispatches_private_ack_message"),
        "schedule_dispatches",
        "ack_message_id IS NULL OR (ack_message_id > 0 AND status = 'SENT' "
        "AND private_ack_required)",
    )
    op.add_column("telegram_outbox", sa.Column("schedule_id", sa.Uuid()))
    op.add_column("telegram_outbox", sa.Column("daily_request_key", sa.String(64)))
    op.add_column("telegram_outbox", sa.Column("summary_text", sa.Text()))
    op.create_foreign_key(
        op.f("fk_telegram_outbox_schedule_id_schedule_dispatches"),
        "telegram_outbox",
        "schedule_dispatches",
        ["schedule_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_telegram_schedule_notice", "telegram_outbox", ["schedule_id", "kind"]
    )
    op.create_unique_constraint(
        "uq_telegram_daily_summary", "telegram_outbox", ["bot_id", "daily_request_key"]
    )
    op.drop_constraint(op.f("ck_telegram_outbox_kind"), "telegram_outbox", type_="check")
    for name, expression in [
        (
            "kind",
            "kind IN ('APPROVED','TEST','VERIFY_GROUP','WORK_REPORT','EXPENSE',"
            "'DAILY_SUMMARY','SCHEDULE_PROMPT','SCHEDULE_CONFIRMED')",
        ),
        (
            "schedule_reference",
            "(kind IN ('SCHEDULE_PROMPT','SCHEDULE_CONFIRMED')) = (schedule_id IS NOT NULL)",
        ),
        (
            "daily_reference",
            "(kind = 'DAILY_SUMMARY' AND daily_request_key IS NOT NULL "
            "AND summary_text IS NOT NULL) OR (kind <> 'DAILY_SUMMARY' "
            "AND daily_request_key IS NULL AND summary_text IS NULL)",
        ),
        (
            "notice_destination",
            "(kind <> 'SCHEDULE_PROMPT' OR destination = 'PRIVATE_TELEGRAM') AND "
            "(kind NOT IN ('DAILY_SUMMARY','SCHEDULE_CONFIRMED') OR destination = 'WORK_GROUP')",
        ),
    ]:
        op.create_check_constraint(
            op.f("ck_telegram_outbox_" + name), "telegram_outbox", expression
        )
    op.execute("""
        CREATE FUNCTION guard_private_schedule_ack() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NEW.private_ack_required IS DISTINCT FROM OLD.private_ack_required
             OR (OLD.ack_message_id IS NOT NULL AND
                 ROW(NEW.ack_message_id, NEW.ack_token_hash, NEW.ack_expires_at) IS DISTINCT FROM
                 ROW(OLD.ack_message_id, OLD.ack_token_hash, OLD.ack_expires_at)) THEN
            RAISE EXCEPTION 'SCHEDULE_ACK_RECEIPT_IMMUTABLE' USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END $$;
    """)
    op.execute("""
        CREATE TRIGGER private_schedule_ack_immutable BEFORE UPDATE ON schedule_dispatches
          FOR EACH ROW EXECUTE FUNCTION guard_private_schedule_ack();
    """)
    op.execute("""
        CREATE FUNCTION guard_telegram_notice() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF (OLD.kind IN ('DAILY_SUMMARY','SCHEDULE_PROMPT','SCHEDULE_CONFIRMED') OR
              NEW.kind IN ('DAILY_SUMMARY','SCHEDULE_PROMPT','SCHEDULE_CONFIRMED')) AND
             ROW(NEW.kind, NEW.technician_id, NEW.bot_id, NEW.destination, NEW.generation,
                 NEW.private_generation, NEW.activity_chat_id, NEW.activity_user_id,
                 NEW.schedule_id, NEW.daily_request_key, NEW.summary_text)
             IS DISTINCT FROM
             ROW(OLD.kind, OLD.technician_id, OLD.bot_id, OLD.destination, OLD.generation,
                 OLD.private_generation, OLD.activity_chat_id, OLD.activity_user_id,
                 OLD.schedule_id, OLD.daily_request_key, OLD.summary_text) THEN
            RAISE EXCEPTION 'TELEGRAM_NOTICE_IMMUTABLE' USING ERRCODE = '23514';
          END IF;
          RETURN NEW;
        END $$;
    """)
    op.execute("""
        CREATE TRIGGER telegram_notice_immutable BEFORE UPDATE ON telegram_outbox
          FOR EACH ROW EXECUTE FUNCTION guard_telegram_notice();
    """)


def downgrade():
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM schedule_dispatches WHERE private_ack_required)
         OR EXISTS (SELECT 1 FROM telegram_outbox
                    WHERE kind IN ('DAILY_SUMMARY','SCHEDULE_PROMPT','SCHEDULE_CONFIRMED'))
      THEN RAISE EXCEPTION 'PRIVATE_ACK_HISTORY_ROLLBACK_REFUSED'; END IF;
    END $$""")
    op.execute("DROP TRIGGER telegram_notice_immutable ON telegram_outbox")
    op.execute("DROP FUNCTION guard_telegram_notice()")
    op.execute("DROP TRIGGER private_schedule_ack_immutable ON schedule_dispatches")
    op.execute("DROP FUNCTION guard_private_schedule_ack()")
    for name in ["kind", "schedule_reference", "daily_reference", "notice_destination"]:
        op.drop_constraint(op.f("ck_telegram_outbox_" + name), "telegram_outbox", type_="check")
    op.create_check_constraint(
        op.f("ck_telegram_outbox_kind"),
        "telegram_outbox",
        "kind IN ('APPROVED','TEST','VERIFY_GROUP','WORK_REPORT','EXPENSE')",
    )
    op.drop_constraint("uq_telegram_schedule_notice", "telegram_outbox", type_="unique")
    op.drop_constraint("uq_telegram_daily_summary", "telegram_outbox", type_="unique")
    for column in ["summary_text", "daily_request_key", "schedule_id"]:
        op.drop_column("telegram_outbox", column)
    op.drop_constraint(
        op.f("ck_schedule_dispatches_private_ack_message"), "schedule_dispatches", type_="check"
    )
    op.drop_column("schedule_dispatches", "ack_message_id")
    op.drop_column("schedule_dispatches", "private_ack_required")
