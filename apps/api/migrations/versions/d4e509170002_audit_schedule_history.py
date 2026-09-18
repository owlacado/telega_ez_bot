"""Preserve dispatch provenance and terminal receipts; guard rollback with history."""

import sqlalchemy as sa
from alembic import op

revision = "d4e509170002"
down_revision = "d4e509170001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("schedule_dispatches", sa.Column("requested_destination", sa.String(16)))
    op.add_column("schedule_dispatches", sa.Column("fallback_reason", sa.String(48)))
    # Legacy actual destinations cannot reconstruct the original request truthfully.
    # Preserve every existing payload; the existing seven-day purge handles retention.
    for name, expression in [
        (
            "requested_destination",
            "requested_destination IS NULL OR requested_destination IN ('WORK_GROUP','PRIVATE')",
        ),
        (
            "fallback_reason",
            "fallback_reason IS NULL OR (destination = 'PRIVATE' "
            "AND requested_destination IS NOT NULL "
            "AND requested_destination = 'WORK_GROUP' AND fallback_reason IN "
            "('GROUP_UNAVAILABLE_BEFORE_SEND','GROUP_REJECTED_PRIVATE_FALLBACK'))",
        ),
        ("positive_message", "message_id IS NULL OR message_id > 0"),
    ]:
        op.create_check_constraint(
            op.f("ck_schedule_dispatches_" + name), "schedule_dispatches", expression
        )
    op.execute("""
      CREATE FUNCTION guard_schedule_receipt() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF NEW.requested_destination IS DISTINCT FROM OLD.requested_destination
          OR (OLD.status IN ('SENT','FAILED','AMBIGUOUS','CANCELLED') AND
              ROW(NEW.destination, NEW.chat_id, NEW.message_id, NEW.sent_at,
                  NEW.finished_at, NEW.error_code, NEW.fallback_reason, NEW.attempt_count)
              IS DISTINCT FROM
              ROW(OLD.destination, OLD.chat_id, OLD.message_id, OLD.sent_at,
                  OLD.finished_at, OLD.error_code, OLD.fallback_reason, OLD.attempt_count))
          OR (OLD.ack_status = 'ACKNOWLEDGED' AND
              ROW(NEW.ack_status, NEW.acknowledged_at) IS DISTINCT FROM
              ROW(OLD.ack_status, OLD.acknowledged_at))
        THEN RAISE EXCEPTION 'SCHEDULE_RECEIPT_IMMUTABLE' USING ERRCODE = '23514'; END IF;
        RETURN NEW;
      END $$;
    """)
    op.execute(
        "CREATE TRIGGER schedule_receipt_immutable BEFORE UPDATE ON schedule_dispatches "
        "FOR EACH ROW EXECUTE FUNCTION guard_schedule_receipt()"
    )


def downgrade():
    # Fail before removing protections or data. No destructive bypass flag.
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM schedule_dispatches)
         OR EXISTS (SELECT 1 FROM schedule_auto_decisions)
      THEN RAISE EXCEPTION 'SCHEDULE_HISTORY_ROLLBACK_REFUSED'; END IF;
    END $$""")
    op.execute("DROP TRIGGER schedule_receipt_immutable ON schedule_dispatches")
    op.execute("DROP FUNCTION guard_schedule_receipt()")
    for name in ["positive_message", "fallback_reason", "requested_destination"]:
        op.drop_constraint(
            op.f("ck_schedule_dispatches_" + name), "schedule_dispatches", type_="check"
        )
    op.drop_column("schedule_dispatches", "fallback_reason")
    op.drop_column("schedule_dispatches", "requested_destination")
