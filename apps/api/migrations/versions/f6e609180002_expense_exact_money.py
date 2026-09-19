"""Reject excess expense precision before coercion and placeholder timezones."""

import sqlalchemy as sa
from alembic import op

revision = "f6e609180002"
down_revision = "f6e609180001"
branch_labels = None
depends_on = None


def upgrade():
    # Removing the typmod preserves every existing value. NUMERIC(p,s) would
    # round BEFORE a CHECK or row trigger can see the original precision.
    op.alter_column(
        "expense_revisions",
        "amount",
        type_=sa.Numeric(),
        existing_type=sa.Numeric(12, 2),
        existing_nullable=False,
    )
    op.create_check_constraint(
        op.f("ck_expense_revisions_money_scale"), "expense_revisions", "scale(amount) <= 2"
    )
    # Do not invent replacement zones or rewrite historical accounting facts.
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM technicians WHERE accounting_timezone IN ('Factory','localtime')
OR accounting_timezone ~ '^(posix|right)/')
      OR EXISTS (SELECT 1 FROM expense_revisions WHERE accounting_timezone IN
('Factory','localtime') OR accounting_timezone ~ '^(posix|right)/')
      THEN RAISE EXCEPTION 'ACCOUNTING_TIMEZONE_REVIEW_REQUIRED'; END IF;
    END $$""")
    op.execute("""CREATE FUNCTION guard_supported_accounting_timezone() RETURNS trigger
    LANGUAGE plpgsql AS $$
      BEGIN
        IF NEW.accounting_timezone IN ('Factory','localtime') OR NEW.accounting_timezone ~
'^(posix|right)/'
        THEN RAISE EXCEPTION 'INVALID_ACCOUNTING_TIMEZONE' USING ERRCODE='23514'; END IF;
        RETURN NEW;
      END $$""")
    for table in ("technicians", "expense_revisions"):
        op.execute(
            f"CREATE TRIGGER {table}_supported_timezone BEFORE INSERT OR UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION guard_supported_accounting_timezone()"
        )


def downgrade():
    op.execute("DROP FUNCTION guard_supported_accounting_timezone() CASCADE")
    # Existing range and scale guards guarantee this conversion is lossless.
    op.alter_column(
        "expense_revisions",
        "amount",
        type_=sa.Numeric(12, 2),
        existing_type=sa.Numeric(),
        existing_nullable=False,
    )
    op.drop_constraint(op.f("ck_expense_revisions_money_scale"), "expense_revisions", type_="check")
