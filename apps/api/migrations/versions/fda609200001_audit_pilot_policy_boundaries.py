"""Correct the narrow pilot record-version boundary."""

from alembic import op

revision = "fda609200001"
down_revision = "fca609190001"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        r"""
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
          IF NEW.id IS DISTINCT FROM OLD.id THEN
            RAISE EXCEPTION 'TECHNICIAN_ID_DATABASE_OWNED'
              USING ERRCODE = 'check_violation';
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
        END $$
        """
    )
    op.execute(
        r"""
        CREATE OR REPLACE FUNCTION hub_version_from_assignment()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'UPDATE' AND
             ROW(NEW.technician_id, NEW.calendar_id, NEW.is_active)
             IS NOT DISTINCT FROM
             ROW(OLD.technician_id, OLD.calendar_id, OLD.is_active)
          THEN RETURN NEW; END IF;
          IF TG_OP <> 'INSERT' AND OLD.is_active THEN
            PERFORM hub_bump_technician_once(OLD.technician_id);
          END IF;
          IF TG_OP <> 'DELETE' AND NEW.is_active THEN
            PERFORM hub_bump_technician_once(NEW.technician_id);
          END IF;
          IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
          RETURN NEW;
        END $$
        """
    )
    op.execute(
        r"""
        CREATE OR REPLACE FUNCTION hub_version_from_telegram_binding()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE old_effective boolean;
        DECLARE new_effective boolean;
        BEGIN
          old_effective := false;
          new_effective := false;
          IF TG_OP <> 'INSERT' THEN
            old_effective := ROW(OLD.private_status, OLD.telegram_user_id, OLD.group_status,
                OLD.telegram_group_chat_id, OLD.bot_id, OLD.private_generation,
                OLD.group_generation, OLD.group_private_generation,
                OLD.private_availability, OLD.group_availability)
            IS DISTINCT FROM
            ROW('NOT_CONNECTED', NULL::bigint, 'NOT_CONNECTED', NULL::bigint,
                NULL::bigint, 0, 0, NULL::integer, 'UNKNOWN', 'UNKNOWN');
          END IF;
          IF TG_OP <> 'DELETE' THEN
            new_effective := ROW(NEW.private_status, NEW.telegram_user_id, NEW.group_status,
                NEW.telegram_group_chat_id, NEW.bot_id, NEW.private_generation,
                NEW.group_generation, NEW.group_private_generation,
                NEW.private_availability, NEW.group_availability)
            IS DISTINCT FROM
            ROW('NOT_CONNECTED', NULL::bigint, 'NOT_CONNECTED', NULL::bigint,
                NULL::bigint, 0, 0, NULL::integer, 'UNKNOWN', 'UNKNOWN');
          END IF;
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
          IF old_effective THEN PERFORM hub_bump_technician_once(OLD.technician_id); END IF;
          IF new_effective THEN PERFORM hub_bump_technician_once(NEW.technician_id); END IF;
          IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
          RETURN NEW;
        END $$
        """
    )
    op.execute(
        r"""
        CREATE OR REPLACE FUNCTION hub_version_from_schedule_setting()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'INSERT' AND NOT NEW.enabled THEN RETURN NEW; END IF;
          IF TG_OP = 'DELETE' AND NOT OLD.enabled THEN RETURN OLD; END IF;
          IF TG_OP = 'UPDATE' AND NEW.enabled IS NOT DISTINCT FROM OLD.enabled
          THEN RETURN NEW; END IF;
          IF TG_OP <> 'INSERT' THEN PERFORM hub_bump_technician_once(OLD.technician_id); END IF;
          IF TG_OP <> 'DELETE' THEN PERFORM hub_bump_technician_once(NEW.technician_id); END IF;
          IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
          RETURN NEW;
        END $$
        """
    )


def downgrade():
    op.execute(
        r"""
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
        END $$
        """
    )
    op.execute(
        r"""
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
        END $$
        """
    )
    op.execute(
        r"""
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
        END $$
        """
    )
    op.execute(
        r"""
        CREATE OR REPLACE FUNCTION hub_version_from_schedule_setting()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP = 'UPDATE' AND NEW.enabled IS NOT DISTINCT FROM OLD.enabled
          THEN RETURN NEW; END IF;
          IF TG_OP <> 'INSERT' THEN PERFORM hub_bump_technician_once(OLD.technician_id); END IF;
          IF TG_OP <> 'DELETE' THEN PERFORM hub_bump_technician_once(NEW.technician_id); END IF;
          IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
          RETURN NEW;
        END $$
        """
    )
