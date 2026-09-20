"""Harden accounting mirror ownership and refresh invariants."""

from alembic import op

revision = "faa609190001"
down_revision = "f9a609190001"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """DO $$ BEGIN
          IF EXISTS (
            SELECT spreadsheet_id
            FROM accounting_mirror_targets
            GROUP BY spreadsheet_id
            HAVING count(*) > 1
          ) THEN
            RAISE EXCEPTION 'ACCOUNTING_MIRROR_SPREADSHEET_REVIEW_REQUIRED';
          END IF;
        END $$"""
    )
    op.create_index(
        "uq_accounting_mirror_spreadsheet_target",
        "accounting_mirror_targets",
        ["spreadsheet_id"],
        unique=True,
    )
    op.create_check_constraint(
        op.f("ck_accounting_mirror_refreshes_lease_order"),
        "accounting_mirror_refreshes",
        "claimed_at IS NULL OR lease_until > claimed_at",
    )
    op.create_check_constraint(
        op.f("ck_accounting_mirror_refreshes_google_sheet_id_nonnegative"),
        "accounting_mirror_refreshes",
        "google_sheet_id IS NULL OR google_sheet_id >= 0",
    )
    op.create_check_constraint(
        op.f("ck_accounting_mirror_refreshes_success_metadata"),
        "accounting_mirror_refreshes",
        "(last_success_at IS NULL AND last_successful_fingerprint IS NULL "
        "AND successful_target_generation IS NULL "
        "AND successful_connection_generation IS NULL) OR "
        "(last_success_at IS NOT NULL AND last_successful_fingerprint IS NOT NULL "
        "AND successful_target_generation > 0 "
        "AND successful_connection_generation > 0 AND completed_generation > 0)",
    )
    op.create_check_constraint(
        op.f("ck_accounting_mirror_refreshes_succeeded_current"),
        "accounting_mirror_refreshes",
        "status != 'SUCCEEDED' OR "
        "(completed_generation = requested_generation AND last_success_at IS NOT NULL)",
    )


def downgrade():
    op.drop_constraint(
        op.f("ck_accounting_mirror_refreshes_succeeded_current"),
        "accounting_mirror_refreshes",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_accounting_mirror_refreshes_success_metadata"),
        "accounting_mirror_refreshes",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_accounting_mirror_refreshes_google_sheet_id_nonnegative"),
        "accounting_mirror_refreshes",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_accounting_mirror_refreshes_lease_order"),
        "accounting_mirror_refreshes",
        type_="check",
    )
    op.drop_index(
        "uq_accounting_mirror_spreadsheet_target",
        table_name="accounting_mirror_targets",
    )
