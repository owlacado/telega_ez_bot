"""Add durable Google Sheets accounting mirror targets and refresh work."""

import sqlalchemy as sa
from alembic import op

revision = "f9a609190001"
down_revision = "f6e609180002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "google_oauth_attempts",
        sa.Column("request_sheets_access", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_table(
        "accounting_mirror_targets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("technician_id", sa.Uuid(), nullable=True),
        sa.Column("google_connection_id", sa.Uuid(), nullable=False),
        sa.Column("spreadsheet_id", sa.String(length=200), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("generation", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "kind IN ('INDIVIDUAL','ALL_TECH')",
            name=op.f("ck_accounting_mirror_targets_kind"),
        ),
        sa.CheckConstraint(
            "(kind = 'INDIVIDUAL' AND technician_id IS NOT NULL) OR "
            "(kind = 'ALL_TECH' AND technician_id IS NULL)",
            name=op.f("ck_accounting_mirror_targets_kind_technician"),
        ),
        sa.CheckConstraint("generation > 0", name=op.f("ck_accounting_mirror_targets_generation")),
        sa.ForeignKeyConstraint(
            ["technician_id"],
            ["technicians.id"],
            name=op.f("fk_accounting_mirror_targets_technician_id_technicians"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["google_connection_id"],
            ["calendar_connections.id"],
            name=op.f("fk_accounting_mirror_targets_google_connection_id_calendar_connections"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_accounting_mirror_targets")),
    )
    op.create_index(
        "uq_accounting_mirror_individual_target",
        "accounting_mirror_targets",
        ["technician_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'INDIVIDUAL'"),
    )
    op.create_index(
        "uq_accounting_mirror_all_tech_target",
        "accounting_mirror_targets",
        ["kind"],
        unique=True,
        postgresql_where=sa.text("kind = 'ALL_TECH'"),
    )
    op.create_table(
        "accounting_mirror_refreshes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("target_id", sa.Uuid(), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("requested_generation", sa.Integer(), server_default="1", nullable=False),
        sa.Column("completed_generation", sa.Integer(), server_default="0", nullable=False),
        sa.Column("status", sa.String(length=20), server_default="PENDING", nullable=False),
        sa.Column("claim_token", sa.Uuid(), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("provider_attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=50), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_successful_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("successful_target_generation", sa.Integer(), nullable=True),
        sa.Column("successful_connection_generation", sa.Integer(), nullable=True),
        sa.Column("google_sheet_id", sa.Integer(), nullable=True),
        sa.Column("owned_rows", sa.Integer(), server_default="0", nullable=False),
        sa.Column("owned_columns", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('PENDING','PROCESSING','SUCCEEDED','FAILED')",
            name=op.f("ck_accounting_mirror_refreshes_status"),
        ),
        sa.CheckConstraint(
            "extract(isodow from week_start) = 1",
            name=op.f("ck_accounting_mirror_refreshes_week_start_monday"),
        ),
        sa.CheckConstraint(
            "requested_generation > 0",
            name=op.f("ck_accounting_mirror_refreshes_requested_generation"),
        ),
        sa.CheckConstraint(
            "completed_generation >= 0",
            name=op.f("ck_accounting_mirror_refreshes_completed_generation_nonnegative"),
        ),
        sa.CheckConstraint(
            "completed_generation <= requested_generation",
            name=op.f("ck_accounting_mirror_refreshes_completed_not_ahead"),
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name=op.f("ck_accounting_mirror_refreshes_attempt_count_nonnegative"),
        ),
        sa.CheckConstraint(
            "owned_rows >= 0 AND owned_columns >= 0",
            name=op.f("ck_accounting_mirror_refreshes_owned_extent_nonnegative"),
        ),
        sa.CheckConstraint(
            "(status = 'PROCESSING' AND claim_token IS NOT NULL AND claimed_at IS NOT NULL "
            "AND lease_until IS NOT NULL) OR (status != 'PROCESSING' AND claim_token IS NULL "
            "AND claimed_at IS NULL AND lease_until IS NULL)",
            name=op.f("ck_accounting_mirror_refreshes_claim_metadata"),
        ),
        sa.ForeignKeyConstraint(
            ["target_id"],
            ["accounting_mirror_targets.id"],
            name=op.f("fk_accounting_mirror_refreshes_target_id_accounting_mirror_targets"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_accounting_mirror_refreshes")),
    )
    op.create_index(
        "uq_accounting_mirror_target_week",
        "accounting_mirror_refreshes",
        ["target_id", "week_start"],
        unique=True,
    )
    op.create_index(
        "ix_accounting_mirror_refresh_claim",
        "accounting_mirror_refreshes",
        ["status", "retry_at", "lease_until"],
    )
    op.create_table(
        "accounting_mirror_worker_states",
        sa.Column("worker_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error_code", sa.String(length=50), nullable=True),
        sa.CheckConstraint(
            "status IN ('STARTING','RUNNING','STOPPED','ERROR')",
            name=op.f("ck_accounting_mirror_worker_states_status"),
        ),
        sa.PrimaryKeyConstraint("worker_id", name=op.f("pk_accounting_mirror_worker_states")),
    )


def downgrade():
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM accounting_mirror_targets)
      THEN RAISE EXCEPTION 'ACCOUNTING_MIRROR_DATA_REVIEW_REQUIRED'; END IF;
    END $$""")
    op.drop_table("accounting_mirror_worker_states")
    op.drop_index("ix_accounting_mirror_refresh_claim", table_name="accounting_mirror_refreshes")
    op.drop_index("uq_accounting_mirror_target_week", table_name="accounting_mirror_refreshes")
    op.drop_table("accounting_mirror_refreshes")
    op.drop_index("uq_accounting_mirror_all_tech_target", table_name="accounting_mirror_targets")
    op.drop_index("uq_accounting_mirror_individual_target", table_name="accounting_mirror_targets")
    op.drop_table("accounting_mirror_targets")
    op.drop_column("google_oauth_attempts", "request_sheets_access")
