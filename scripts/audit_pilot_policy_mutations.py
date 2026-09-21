"""Run compact pilot-policy mutations and restore sources and test schema."""

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = str(ROOT / ".venv/Scripts/python.exe")
PYTEST = (PYTHON, "-m", "pytest", "-q", "-p", "no:cacheprovider")
DATABASE_URL = "postgresql+asyncpg://hub:hub_test_only@127.0.0.1:5437/technician_hub_test"


@dataclass(frozen=True)
class Mutation:
    name: str
    path: str
    old: str
    new: str
    tests: tuple[str, ...]
    reload_migration: bool = False


MUTATIONS = (
    Mutation(
        "bypass_permanent_delete",
        "apps/api/migrations/versions/fda609200001_audit_pilot_policy_boundaries.py",
        "          IF TG_OP = 'DELETE' THEN\n            RAISE EXCEPTION "
        "'PILOT_TECHNICIAN_DELETE_DISABLED' USING ERRCODE = 'check_violation';\n"
        "          END IF;",
        "          IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;",
        (
            "apps/api/tests/test_pilot_policies.py::test_profile_version_is_database_owned_and_delete_is_disabled",
        ),
        True,
    ),
    Mutation(
        "allow_new_ssn_value",
        "apps/api/migrations/versions/fda609200001_audit_pilot_policy_boundaries.py",
        "             OR (NEW.ssn_last4 IS DISTINCT FROM OLD.ssn_last4 "
        "AND NEW.ssn_last4 IS NOT NULL) THEN",
        "             OR (false AND NEW.ssn_last4 IS DISTINCT FROM OLD.ssn_last4 "
        "AND NEW.ssn_last4 IS NOT NULL) THEN",
        (
            "apps/api/tests/test_pilot_policy_quality_audit.py::test_legacy_pilot_profile_values_are_preserved_but_cannot_be_replaced",
        ),
        True,
    ),
    Mutation(
        "disable_telegram_admission",
        "apps/api/hub/telegram/updates.py",
        "            for key, limit, seconds in budgets:",
        "            for key, limit, seconds in []:",
        (
            "apps/api/tests/test_telegram_worker.py::test_application_admission_limits_sender_burst_without_counting_duplicates",
        ),
    ),
    Mutation(
        "disable_google_manager_admission",
        "apps/api/hub/google_calendar/service.py",
        "        limit=settings.google_oauth_manager_limit,",
        "        limit=settings.google_oauth_manager_limit + 1000,",
        (
            "apps/api/tests/test_google_calendar.py::test_oauth_start_admission_is_per_manager_and_database_backed",
        ),
    ),
    Mutation(
        "rate_limit_automatic_worker_request",
        "apps/api/hub/schedule_delivery/service.py",
        "async def create_dispatch(request, technician_id, body=None, *, automatic=False):\n"
        "    config = request.app.state.settings",
        "async def create_dispatch(request, technician_id, body=None, *, automatic=False):\n"
        "    if automatic:\n"
        "        raise HTTPException(429, 'manager admission must not limit workers')\n"
        "    config = request.app.state.settings",
        (
            "apps/api/tests/test_schedule_delivery_audit.py::test_manual_auto_and_resend_serialization",
        ),
    ),
    Mutation(
        "cleanup_deletes_audit_history",
        "apps/api/hub/ops/service.py",
        "    if apply:\n        if form_ids:",
        "    if apply:\n"
        '        await db.execute(text("DELETE FROM audit_events"))\n'
        "        if form_ids:",
        (
            "apps/api/tests/test_pilot_policy_quality_audit.py::test_cleanup_never_deletes_business_revisions_or_audit_history",
        ),
    ),
    Mutation(
        "record_version_fails_to_bump",
        "apps/api/migrations/versions/fda609200001_audit_pilot_policy_boundaries.py",
        "            IF hub_mark_technician_version(OLD.id) THEN",
        "            IF false THEN",
        (
            "apps/api/tests/test_pilot_policy_quality_audit.py::test_record_version_profile_once_rollback_and_concurrent_serialization",
        ),
        True,
    ),
    Mutation(
        "record_version_bumps_twice",
        "apps/api/migrations/versions/fda609200001_audit_pilot_policy_boundaries.py",
        "            IF hub_mark_technician_version(OLD.id) THEN",
        "            IF true THEN",
        (
            "apps/api/tests/test_pilot_policy_quality_audit.py::test_record_version_profile_once_rollback_and_concurrent_serialization",
        ),
        True,
    ),
    Mutation(
        "rollback_preserves_version_bump",
        "apps/api/tests/test_pilot_policy_quality_audit.py",
        "        await transaction.rollback()",
        "        await transaction.commit()",
        (
            "apps/api/tests/test_pilot_policy_quality_audit.py::test_record_version_profile_once_rollback_and_concurrent_serialization",
        ),
    ),
)


def command(
    args: tuple[str, ...], *, cwd: Path, environment: dict[str, str]
) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=240,
        check=False,
    )


def reload_migration(environment: dict[str, str]) -> None:
    migration_env = {**environment, "DATABASE_URL": DATABASE_URL}
    for operation in (
        (PYTHON, "-m", "alembic", "downgrade", "fca609190001"),
        (PYTHON, "-m", "alembic", "upgrade", "head"),
    ):
        completed = command(operation, cwd=ROOT / "apps/api", environment=migration_env)
        if completed.returncode:
            raise RuntimeError(completed.stdout + completed.stderr)


def main() -> None:
    paths = {ROOT / mutation.path for mutation in MUTATIONS}
    originals = {path: path.read_bytes() for path in paths}
    for mutation in MUTATIONS:
        original_text = originals[ROOT / mutation.path].decode("utf-8").replace("\r\n", "\n")
        count = original_text.count(mutation.old)
        if count < 1:
            raise RuntimeError(f"mutation preflight failed for {mutation.name}: found {count}")
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    results = []
    try:
        for mutation in MUTATIONS:
            path = ROOT / mutation.path
            original = originals[path]
            original_text = original.decode("utf-8").replace("\r\n", "\n")
            path.write_text(
                original_text.replace(mutation.old, mutation.new, 1),
                encoding="utf-8",
                newline="",
            )
            if mutation.reload_migration:
                reload_migration(environment)
            completed = command((*PYTEST, *mutation.tests), cwd=ROOT, environment=environment)
            results.append(
                {
                    "name": mutation.name,
                    "detected": completed.returncode != 0,
                    "returncode": completed.returncode,
                    "tail": (completed.stdout + completed.stderr)[-700:],
                }
            )
            path.write_bytes(original)
            if mutation.reload_migration:
                reload_migration(environment)
    finally:
        for path, original in originals.items():
            path.write_bytes(original)
        reload_migration(environment)
    restored = all(path.read_bytes() == original for path, original in originals.items())
    report = {
        "detected": sum(item["detected"] for item in results),
        "total": len(results),
        "restored": restored,
        "source_hashes": {
            str(path.relative_to(ROOT)): hashlib.sha256(data).hexdigest()
            for path, data in originals.items()
        },
        "results": results,
    }
    output = ROOT / ".local/pilot-policy-mutations.json"
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("detected", "total", "restored")}))
    if report["detected"] != report["total"] or not restored:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
