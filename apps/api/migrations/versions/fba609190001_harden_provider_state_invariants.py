"""Harden legacy Telegram and GPS provider state invariants."""

from alembic import op

revision = "fba609190001"
down_revision = "faa609190001"
branch_labels = None
depends_on = None


def upgrade():
    constraints = (
        (
            "telegram_bindings",
            "nonnegative_generations",
            "private_generation >= 0 AND group_generation >= 0",
        ),
        (
            "telegram_bindings",
            "private_availability",
            "private_availability IN ('UNKNOWN','AVAILABLE','BLOCKED','UNAVAILABLE')",
        ),
        (
            "telegram_bindings",
            "group_availability",
            "group_availability IN "
            "('UNKNOWN','AVAILABLE','UNAVAILABLE','REVALIDATION_REQUIRED','MIGRATION_CONFLICT')",
        ),
        (
            "telegram_bindings",
            "private_connected_identity",
            "private_status != 'CONNECTED' OR "
            "(telegram_user_id IS NOT NULL AND bot_id IS NOT NULL AND private_generation > 0)",
        ),
        (
            "telegram_bindings",
            "group_connected_identity",
            "group_status != 'CONNECTED' OR "
            "(telegram_group_chat_id IS NOT NULL AND bot_id IS NOT NULL AND group_generation > 0)",
        ),
        (
            "telegram_bindings",
            "private_available_connected",
            "private_availability != 'AVAILABLE' OR private_status = 'CONNECTED'",
        ),
        (
            "telegram_bindings",
            "group_available_current_private",
            "group_availability != 'AVAILABLE' OR "
            "(group_status = 'CONNECTED' AND private_status = 'CONNECTED' "
            "AND group_private_generation = private_generation)",
        ),
        (
            "gps_bindings",
            "provider_status",
            "(provider = 'NONE' AND status = 'NOT_CONNECTED') OR "
            "(provider = 'MOTOWATCHDOG_SHARE' AND status != 'NOT_CONNECTED')",
        ),
    )
    for table, name, expression in constraints:
        op.create_check_constraint(op.f(f"ck_{table}_{name}"), table, expression)


def downgrade():
    for table, name in reversed(
        (
            ("telegram_bindings", "nonnegative_generations"),
            ("telegram_bindings", "private_availability"),
            ("telegram_bindings", "group_availability"),
            ("telegram_bindings", "private_connected_identity"),
            ("telegram_bindings", "group_connected_identity"),
            ("telegram_bindings", "private_available_connected"),
            ("telegram_bindings", "group_available_current_private"),
            ("gps_bindings", "provider_status"),
        )
    ):
        op.drop_constraint(op.f(f"ck_{table}_{name}"), table, type_="check")
