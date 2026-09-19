"""Normalize derived recurring occurrence keys without altering business snapshots."""

import hashlib
import json
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "e5f509180003"
down_revision = "e5f509180002"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    # Exclude concurrent writers while validating and rekeying the derived index.
    op.execute("LOCK TABLE work_reports, work_report_revisions IN ACCESS EXCLUSIVE MODE")
    rows = connection.execute(
        sa.text(
            "SELECT r.id,r.technician_id,r.calendar_id,r.occurrence_key,"
            "v.recurring_event_id,v.original_start_time FROM work_reports r "
            "JOIN work_report_revisions v ON v.report_id=r.id AND v.revision_number=1"
        )
    ).all()
    seen, changes = set(), []
    for row in rows:
        key = row.occurrence_key
        if row.recurring_event_id and row.original_start_time:
            try:
                instant = datetime.fromisoformat(row.original_start_time)
                if instant.tzinfo is None:
                    raise ValueError()
                encoded = json.dumps(
                    [
                        str(row.calendar_id),
                        [row.recurring_event_id, instant.astimezone(UTC).isoformat()],
                    ]
                )
                key = hashlib.sha256(encoded.encode()).hexdigest()
            except (ValueError, TypeError):
                raise RuntimeError("WORK_REPORT_OCCURRENCE_INVALID") from None
        identity = (row.technician_id, row.calendar_id, key)
        if identity in seen:
            # Already-duplicated financial records require an explicit reconciliation
            # decision. Never merge/delete a winner or silently rewrite revisions.
            raise RuntimeError("WORK_REPORT_OCCURRENCE_COLLISION")
        seen.add(identity)
        if key != row.occurrence_key:
            changes.append({"id": row.id, "key": key})
    if changes:
        op.execute("ALTER TABLE work_reports DISABLE TRIGGER work_report_identity_immutable")
        connection.execute(
            sa.text("UPDATE work_reports SET occurrence_key=:key WHERE id=:id"), changes
        )
        op.execute("ALTER TABLE work_reports ENABLE TRIGGER work_report_identity_immutable")
    # Transactional DDL: any failure restores old keys and trigger state together.


def downgrade():
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM work_reports)
      THEN RAISE EXCEPTION 'WORK_REPORT_HISTORY_ROLLBACK_REFUSED'; END IF;
    END $$""")
    # Empty history has no derived keys to restore. Older code must never run with
    # populated canonicalized history because it would recreate the duplicate bug.
