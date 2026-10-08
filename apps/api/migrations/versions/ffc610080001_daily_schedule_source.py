"""Record the official schedule trigger without rewriting historic dispatches."""

import sqlalchemy as sa
from alembic import op

revision = "ffc610080001"
down_revision = "ffb610060001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("schedule_dispatches", sa.Column("trigger_source", sa.String(24), nullable=True))
    op.add_column(
        "schedule_dispatches", sa.Column("daily_request_key", sa.String(64), nullable=True)
    )
    op.create_unique_constraint(
        "uq_schedule_daily_request", "schedule_dispatches", ["bot_id", "daily_request_key"]
    )
    op.create_check_constraint(
        op.f("ck_schedule_dispatches_trigger_source"),
        "schedule_dispatches",
        "trigger_source IS NULL OR trigger_source IN ('TECHNICIAN_DAILY','MANAGER_MANUAL')",
    )

    op.execute("""
        CREATE FUNCTION guard_schedule_trigger_source() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.trigger_source IS DISTINCT FROM OLD.trigger_source
               OR NEW.daily_request_key IS DISTINCT FROM OLD.daily_request_key THEN
                RAISE EXCEPTION 'SCHEDULE_IMMUTABLE' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$;
    """)
    op.execute("""
        CREATE TRIGGER schedule_trigger_source_immutable BEFORE UPDATE ON schedule_dispatches
        FOR EACH ROW EXECUTE FUNCTION guard_schedule_trigger_source();
    """)


def downgrade():
    op.execute("DROP TRIGGER IF EXISTS schedule_trigger_source_immutable ON schedule_dispatches")
    op.execute("DROP FUNCTION IF EXISTS guard_schedule_trigger_source()")
    op.drop_constraint(
        op.f("ck_schedule_dispatches_trigger_source"), "schedule_dispatches", type_="check"
    )
    op.drop_constraint("uq_schedule_daily_request", "schedule_dispatches", type_="unique")
    op.drop_column("schedule_dispatches", "daily_request_key")
    op.drop_column("schedule_dispatches", "trigger_source")
