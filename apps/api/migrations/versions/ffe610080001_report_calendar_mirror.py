"""Approved Calendar report mirror and retained private schedule snapshot."""

import sqlalchemy as sa
from alembic import op

revision = "ffe610080001"
down_revision = "ffd610080001"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint(
        op.f("ck_schedule_dispatches_sent_payload_purged"), "schedule_dispatches", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_schedule_dispatches_sent_payload_purged"),
        "schedule_dispatches",
        "status <> 'SENT' OR encrypted_payload IS NULL OR "
        "(private_ack_required AND ack_message_id IS NULL)",
    )
    op.add_column(
        "google_oauth_attempts",
        sa.Column(
            "request_report_write_access",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.create_table(
        "report_calendar_mirrors",
        sa.Column(
            "report_id",
            sa.Uuid(),
            sa.ForeignKey("work_reports.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column(
            "connection_id",
            sa.Uuid(),
            sa.ForeignKey("calendar_connections.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "calendar_id",
            sa.Uuid(),
            sa.ForeignKey("calendars.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("provider_calendar_id", sa.String(1024), nullable=False),
        sa.Column("provider_event_id", sa.String(1024), nullable=False),
        sa.Column("requested_revision", sa.Integer(), nullable=False),
        sa.Column("synced_revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("claim_token", sa.Uuid()),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column(
            "available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(50)),
        sa.Column("synced_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('PENDING','PROCESSING','SYNCED','BLOCKED')",
            name=op.f("ck_report_calendar_mirrors_status"),
        ),
        sa.CheckConstraint(
            "requested_revision > 0 AND synced_revision >= 0",
            name=op.f("ck_report_calendar_mirrors_revision"),
        ),
        sa.CheckConstraint(
            "(claim_token IS NULL) = (lease_until IS NULL)",
            name=op.f("ck_report_calendar_mirrors_claim_pair"),
        ),
    )
    # Current-pointer transitions AND current revision insertion enqueue in the business
    # transaction.
    # No history backfill: this approval applies to new submissions/revisions, not old customer
    # events.
    op.execute("""
    CREATE FUNCTION enqueue_report_calendar_mirror() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE rid uuid;
    BEGIN
      IF TG_TABLE_NAME = 'work_reports' THEN rid := NEW.id; ELSE rid := NEW.report_id; END IF;
      INSERT INTO report_calendar_mirrors
        (report_id, connection_id, calendar_id, provider_calendar_id, provider_event_id,
        requested_revision)
      SELECT r.id, c.provider_connection_id, c.id, c.provider_calendar_id, v.provider_event_id,
        r.current_revision_number
      FROM work_reports r JOIN calendars c ON c.id=r.calendar_id
      JOIN work_report_revisions v ON v.report_id=r.id AND
        v.revision_number=r.current_revision_number
      WHERE r.id=rid AND c.source='GOOGLE' AND c.provider_connection_id IS NOT NULL AND
        c.provider_calendar_id IS NOT NULL
      ON CONFLICT (report_id) DO UPDATE SET
        requested_revision=EXCLUDED.requested_revision,
        status=CASE WHEN report_calendar_mirrors.status='PROCESSING' THEN 'PROCESSING' ELSE
        'PENDING' END,
        available_at=clock_timestamp()
      WHERE report_calendar_mirrors.requested_revision < EXCLUDED.requested_revision;
      RETURN NEW;
    END $$;
    """)
    op.execute(
        "CREATE TRIGGER report_calendar_mirror_revision AFTER INSERT ON "
        "work_report_revisions FOR EACH ROW EXECUTE FUNCTION "
        "enqueue_report_calendar_mirror()"
    )
    op.execute(
        "CREATE TRIGGER report_calendar_mirror_current AFTER INSERT OR UPDATE OF "
        "current_revision_number ON work_reports FOR EACH ROW EXECUTE FUNCTION "
        "enqueue_report_calendar_mirror()"
    )
    op.execute("""
    CREATE FUNCTION guard_report_calendar_mirror_target() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF
        ROW(NEW.report_id,NEW.connection_id,NEW.calendar_id,NEW.provider_calendar_id,NEW.provider_event_id)
         IS DISTINCT FROM
        ROW(OLD.report_id,OLD.connection_id,OLD.calendar_id,OLD.provider_calendar_id,OLD.provider_event_id)
      THEN RAISE EXCEPTION 'REPORT_MIRROR_TARGET_IMMUTABLE'; END IF;
      RETURN NEW;
    END $$;
    """)
    op.execute(
        "CREATE TRIGGER report_calendar_mirror_target BEFORE UPDATE ON "
        "report_calendar_mirrors FOR EACH ROW EXECUTE FUNCTION "
        "guard_report_calendar_mirror_target()"
    )


def downgrade():
    op.execute("""DO $$ BEGIN IF EXISTS (SELECT 1 FROM report_calendar_mirrors)
      OR EXISTS (SELECT 1 FROM schedule_dispatches WHERE status='SENT' AND encrypted_payload IS
        NOT NULL)
      THEN RAISE EXCEPTION 'REPORT_MIRROR_HISTORY_ROLLBACK_REFUSED'; END IF; END $$""")
    op.execute("DROP TRIGGER report_calendar_mirror_revision ON work_report_revisions")
    op.execute("DROP TRIGGER report_calendar_mirror_current ON work_reports")
    op.execute("DROP FUNCTION enqueue_report_calendar_mirror()")
    op.drop_table("report_calendar_mirrors")
    op.execute("DROP FUNCTION guard_report_calendar_mirror_target()")
    op.drop_column("google_oauth_attempts", "request_report_write_access")
    op.drop_constraint(
        op.f("ck_schedule_dispatches_sent_payload_purged"), "schedule_dispatches", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_schedule_dispatches_sent_payload_purged"),
        "schedule_dispatches",
        "status <> 'SENT' OR encrypted_payload IS NULL",
    )
