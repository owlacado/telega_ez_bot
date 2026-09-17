"""Guard calendar invariants without rewriting Stage 0 migration history."""

from alembic import op

revision = "a04e70c92001"
down_revision = "863590d3075e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Validate existing rows; invalid legacy data aborts the migration transaction.
    op.create_check_constraint("name_not_empty", "calendars", "length(btrim(name)) > 0")
    op.create_check_constraint(
        "active_has_calendar", "calendar_assignments", "NOT is_active OR calendar_id IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_calendar_assignments_active_has_calendar"), "calendar_assignments", type_="check"
    )
    op.drop_constraint(op.f("ck_calendars_name_not_empty"), "calendars", type_="check")
