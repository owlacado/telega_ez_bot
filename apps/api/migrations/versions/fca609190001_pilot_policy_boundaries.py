"""Enforce the approved pilot profile and version boundaries."""

import sqlalchemy as sa
from alembic import op

revision = "fca609190001"
down_revision = "fba609190001"
branch_labels = None
depends_on = None


def _statements(script: str):
    """Split DDL for asyncpg, which accepts one prepared statement at a time."""
    start = 0
    index = 0
    in_dollar_quote = False
    while index < len(script):
        if script.startswith("$$", index):
            in_dollar_quote = not in_dollar_quote
            index += 2
            continue
        if script[index] == ";" and not in_dollar_quote:
            statement = script[start:index].strip()
            if statement:
                yield statement
            start = index + 1
        index += 1
    statement = script[start:].strip()
    if statement:
        yield statement


def upgrade():
    op.add_column(
        "technicians",
        sa.Column("record_version", sa.BigInteger(), server_default="1", nullable=False),
    )
    op.create_check_constraint(
        op.f("ck_technicians_positive_record_version"),
        "technicians",
        "record_version > 0",
    )
    for statement in _statements(
        r"""
        CREATE OR REPLACE FUNCTION hub_mark_technician_version(p_id uuid)
        RETURNS boolean LANGUAGE plpgsql AS $$
        DECLARE inserted integer;
        BEGIN
          CREATE TEMP TABLE IF NOT EXISTS hub_technician_version_bumps (
            technician_id uuid PRIMARY KEY
          ) ON COMMIT DELETE ROWS;
          EXECUTE 'INSERT INTO pg_temp.hub_technician_version_bumps '
                  'VALUES ($1) ON CONFLICT DO NOTHING' USING p_id;
          GET DIAGNOSTICS inserted = ROW_COUNT;
          RETURN inserted = 1;
        END $$;

        CREATE OR REPLACE FUNCTION hub_guard_technician()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE profile_changed boolean;
        BEGIN
          IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'PILOT_TECHNICIAN_DELETE_DISABLED' USING ERRCODE = 'check_violation';
          END IF;
          IF TG_OP = 'INSERT' THEN
            IF NEW.photo_url IS NOT NULL OR NEW.driver_license_id IS NOT NULL
               OR NEW.ssn_last4 IS NOT NULL THEN
              RAISE EXCEPTION 'PILOT_PROFILE_DATA_COLLECTION_DISABLED'
                USING ERRCODE = 'check_violation';
            END IF;
            NEW.record_version := 1;
            RETURN NEW;
          END IF;
          IF (NEW.photo_url IS DISTINCT FROM OLD.photo_url AND NEW.photo_url IS NOT NULL)
             OR (NEW.driver_license_id IS DISTINCT FROM OLD.driver_license_id
                 AND NEW.driver_license_id IS NOT NULL)
             OR (NEW.ssn_last4 IS DISTINCT FROM OLD.ssn_last4 AND NEW.ssn_last4 IS NOT NULL) THEN
            RAISE EXCEPTION 'PILOT_PROFILE_DATA_COLLECTION_DISABLED'
              USING ERRCODE = 'check_violation';
          END IF;
          profile_changed := ROW(NEW.first_name, NEW.last_name, NEW.status,
                                  NEW.accounting_timezone, NEW.photo_url,
                                  NEW.driver_license_id, NEW.ssn_last4)
                             IS DISTINCT FROM
                             ROW(OLD.first_name, OLD.last_name, OLD.status,
                                 OLD.accounting_timezone, OLD.photo_url,
                                 OLD.driver_license_id, OLD.ssn_last4);
          IF profile_changed THEN
            IF hub_mark_technician_version(OLD.id) THEN
              NEW.record_version := OLD.record_version + 1;
            ELSE
              NEW.record_version := OLD.record_version;
            END IF;
          ELSIF NEW.record_version IS DISTINCT FROM OLD.record_version THEN
            IF pg_trigger_depth() <= 1 OR NEW.record_version <> OLD.record_version + 1 THEN
              RAISE EXCEPTION 'TECHNICIAN_RECORD_VERSION_DATABASE_OWNED'
                USING ERRCODE = 'check_violation';
            END IF;
          ELSE
            NEW.record_version := OLD.record_version;
          END IF;
          RETURN NEW;
        END $$;

        CREATE TRIGGER trg_technicians_pilot_guard
          BEFORE INSERT OR UPDATE OR DELETE ON technicians
          FOR EACH ROW EXECUTE FUNCTION hub_guard_technician();

        CREATE OR REPLACE FUNCTION hub_bump_technician_once(p_id uuid)
        RETURNS void LANGUAGE plpgsql AS $$
        BEGIN
          IF p_id IS NOT NULL AND hub_mark_technician_version(p_id) THEN
            UPDATE technicians SET record_version = record_version + 1 WHERE id = p_id;
          END IF;
        END $$;

        CREATE OR REPLACE FUNCTION hub_version_from_assignment()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP <> 'INSERT' AND OLD.is_active THEN
            PERFORM hub_bump_technician_once(OLD.technician_id);
          END IF;
          IF TG_OP <> 'DELETE' AND NEW.is_active THEN
            PERFORM hub_bump_technician_once(NEW.technician_id);
          END IF;
          IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER trg_calendar_assignment_technician_version
          AFTER INSERT OR UPDATE OR DELETE ON calendar_assignments
          FOR EACH ROW EXECUTE FUNCTION hub_version_from_assignment();

        CREATE OR REPLACE FUNCTION hub_version_from_telegram_binding()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'UPDATE' AND ROW(NEW.private_status, NEW.telegram_user_id,
              NEW.group_status, NEW.telegram_group_chat_id, NEW.bot_id,
              NEW.private_generation, NEW.group_generation, NEW.group_private_generation,
              NEW.private_availability, NEW.group_availability)
            IS NOT DISTINCT FROM ROW(OLD.private_status, OLD.telegram_user_id,
              OLD.group_status, OLD.telegram_group_chat_id, OLD.bot_id,
              OLD.private_generation, OLD.group_generation, OLD.group_private_generation,
              OLD.private_availability, OLD.group_availability) THEN
            RETURN NEW;
          END IF;
          IF TG_OP <> 'INSERT' THEN PERFORM hub_bump_technician_once(OLD.technician_id); END IF;
          IF TG_OP <> 'DELETE' THEN PERFORM hub_bump_technician_once(NEW.technician_id); END IF;
          IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER trg_telegram_binding_technician_version
          AFTER INSERT OR UPDATE OR DELETE ON telegram_bindings
          FOR EACH ROW EXECUTE FUNCTION hub_version_from_telegram_binding();

        CREATE OR REPLACE FUNCTION hub_version_from_schedule_setting()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'UPDATE' AND NEW.enabled IS NOT DISTINCT FROM OLD.enabled
          THEN RETURN NEW; END IF;
          IF TG_OP <> 'INSERT' THEN PERFORM hub_bump_technician_once(OLD.technician_id); END IF;
          IF TG_OP <> 'DELETE' THEN PERFORM hub_bump_technician_once(NEW.technician_id); END IF;
          IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER trg_schedule_setting_technician_version
          AFTER INSERT OR UPDATE OR DELETE ON schedule_delivery_settings
          FOR EACH ROW EXECUTE FUNCTION hub_version_from_schedule_setting();

        CREATE OR REPLACE FUNCTION hub_version_from_calendar()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE technician uuid;
        BEGIN
          IF ROW(NEW.source, NEW.provider_connection_id, NEW.provider_calendar_id,
                 NEW.availability, NEW.timezone, NEW.excluded_at)
             IS NOT DISTINCT FROM
             ROW(OLD.source, OLD.provider_connection_id, OLD.provider_calendar_id,
                 OLD.availability, OLD.timezone, OLD.excluded_at) THEN RETURN NEW; END IF;
          FOR technician IN SELECT technician_id FROM calendar_assignments
            WHERE calendar_id = NEW.id AND is_active
          LOOP PERFORM hub_bump_technician_once(technician); END LOOP;
          RETURN NEW;
        END $$;
        CREATE TRIGGER trg_calendar_technician_version
          AFTER UPDATE ON calendars FOR EACH ROW EXECUTE FUNCTION hub_version_from_calendar();

        CREATE OR REPLACE FUNCTION hub_version_from_calendar_connection()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE technician uuid;
        BEGIN
          IF ROW(NEW.account_key, NEW.is_current, NEW.status, NEW.generation, NEW.granted_scopes)
             IS NOT DISTINCT FROM
             ROW(OLD.account_key, OLD.is_current, OLD.status, OLD.generation, OLD.granted_scopes)
          THEN RETURN NEW; END IF;
          FOR technician IN
            SELECT DISTINCT a.technician_id FROM calendar_assignments a
            JOIN calendars c ON c.id = a.calendar_id
            WHERE a.is_active AND c.provider_connection_id IN (OLD.id, NEW.id)
          LOOP PERFORM hub_bump_technician_once(technician); END LOOP;
          RETURN NEW;
        END $$;
        CREATE TRIGGER trg_calendar_connection_technician_version
          AFTER UPDATE ON calendar_connections
          FOR EACH ROW EXECUTE FUNCTION hub_version_from_calendar_connection();
        """
    ):
        op.execute(statement)


def downgrade():
    for table, trigger in (
        ("calendar_connections", "trg_calendar_connection_technician_version"),
        ("calendars", "trg_calendar_technician_version"),
        ("schedule_delivery_settings", "trg_schedule_setting_technician_version"),
        ("telegram_bindings", "trg_telegram_binding_technician_version"),
        ("calendar_assignments", "trg_calendar_assignment_technician_version"),
        ("technicians", "trg_technicians_pilot_guard"),
    ):
        op.execute(f"DROP TRIGGER IF EXISTS {trigger} ON {table}")
    for function in (
        "hub_version_from_calendar_connection()",
        "hub_version_from_calendar()",
        "hub_version_from_schedule_setting()",
        "hub_version_from_telegram_binding()",
        "hub_version_from_assignment()",
        "hub_bump_technician_once(uuid)",
        "hub_guard_technician()",
        "hub_mark_technician_version(uuid)",
    ):
        op.execute(f"DROP FUNCTION IF EXISTS {function}")
    op.drop_constraint(op.f("ck_technicians_positive_record_version"), "technicians")
    op.drop_column("technicians", "record_version")
