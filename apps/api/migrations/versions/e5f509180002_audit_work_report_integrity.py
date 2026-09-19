"""Audit Work Report revision sequence and session consistency; no data rewrites."""

from alembic import op

revision = "e5f509180002"
down_revision = "e5f509180001"
branch_labels = None
depends_on = None


def upgrade():
    # Fail closed on existing inconsistent history; never silently delete/repair it.
    op.execute("""DO $$ BEGIN
      IF EXISTS (
        SELECT 1 FROM work_reports r LEFT JOIN work_report_revisions v ON v.report_id=r.id
        GROUP BY r.id HAVING count(v.id) <> r.current_revision_number
          OR min(v.revision_number) <> 1 OR max(v.revision_number) <> r.current_revision_number
      ) THEN RAISE EXCEPTION 'WORK_REPORT_REVISION_SEQUENCE_INVALID'; END IF;
    END $$""")
    op.drop_constraint(op.f("ck_technician_form_sessions_submission"), "technician_form_sessions")
    op.create_check_constraint(
        op.f("ck_technician_form_sessions_submission"),
        "technician_form_sessions",
        "(status = 'SUBMITTED' AND report_id IS NOT NULL AND submitted_at IS NOT NULL "
        "AND payload_hash IS NOT NULL) OR (status <> 'SUBMITTED' AND report_id IS NULL "
        "AND submitted_at IS NULL AND payload_hash IS NULL)",
    )
    op.execute("""
      CREATE FUNCTION guard_work_report_sequence() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE target uuid; pointer integer; total bigint; first_number integer; last_number integer;
      BEGIN
        IF TG_TABLE_NAME = 'work_reports' THEN target := NEW.id;
        ELSE target := NEW.report_id; END IF;
        SELECT current_revision_number INTO pointer FROM work_reports WHERE id=target;
        SELECT count(*),min(revision_number),max(revision_number)
          INTO total,first_number,last_number FROM work_report_revisions WHERE report_id=target;
        IF pointer IS NULL OR total <> pointer OR first_number <> 1 OR last_number <> pointer
        THEN RAISE EXCEPTION 'WORK_REPORT_REVISION_SEQUENCE_INVALID' USING ERRCODE='23514'; END IF;
        RETURN NULL;
      END $$;
    """)
    # Deferred: report plus all revisions are inserted atomically, in either order.
    # Existing immutable UPDATE/DELETE triggers remain authoritative.
    for table in ("work_reports", "work_report_revisions"):
        op.execute(
            f"CREATE CONSTRAINT TRIGGER {table}_sequence AFTER INSERT ON {table} "
            "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
            "EXECUTE FUNCTION guard_work_report_sequence()"
        )


def downgrade():
    op.execute("DROP FUNCTION guard_work_report_sequence() CASCADE")
    op.drop_constraint(op.f("ck_technician_form_sessions_submission"), "technician_form_sessions")
    op.create_check_constraint(
        op.f("ck_technician_form_sessions_submission"),
        "technician_form_sessions",
        "(status = 'SUBMITTED') = (report_id IS NOT NULL "
        "AND submitted_at IS NOT NULL AND payload_hash IS NOT NULL)",
    )
