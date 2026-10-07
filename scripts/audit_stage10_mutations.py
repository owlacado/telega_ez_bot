"""Run Stage 10 mutation probes and restore every source file byte-for-byte."""

# ruff: noqa: E501

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTEST = [str(ROOT / ".venv/Scripts/python.exe"), "-m", "pytest", "-q", "-p", "no:cacheprovider"]
PILOT = "apps/api/tests/test_pilot_readiness.py"


@dataclass(frozen=True)
class Mutation:
    name: str
    path: str
    old: str
    new: str
    command: tuple[str, ...]
    occurrence: int = 0


def pytest(*tests: str) -> tuple[str, ...]:
    return (*PYTEST, *tests)


MUTATIONS = (
    Mutation(
        "ready_without_accounting_timezone",
        "apps/api/hub/technicians/service.py",
        'status="READY" if technician.accounting_timezone else "NEEDS_ACTION"',
        'status="READY" if True else "NEEDS_ACTION"',
        pytest(f"{PILOT}::test_canonical_readiness_combinations"),
    ),
    Mutation(
        "ready_without_private_telegram",
        "apps/api/hub/technicians/service.py",
        '            if integrations.telegram_private == "CONNECTED"\n            else "NEEDS_ACTION",',
        '            if True\n            else "NEEDS_ACTION",',
        pytest(f"{PILOT}::test_canonical_readiness_combinations"),
    ),
    Mutation(
        "frontend_recomputes_readiness",
        "apps/web/src/app/(workspace)/page.tsx",
        ".filter((item) => !item.technician.pilot_readiness.ready);",
        ".filter((item) => !item.technician.accounting_timezone);",
        (
            r"C:\Program Files\nodejs\npm.cmd",
            "run",
            "test",
            "-w",
            "apps/web",
            "--",
            "components.test.tsx",
            "-t",
            "renders backend readiness consistently",
        ),
    ),
    Mutation(
        "production_allows_fake_provider",
        "apps/api/hub/core/config.py",
        '        if self.telegram_mode == "fake" or self.google_mode == "fake":',
        "        if False:",
        pytest(f"{PILOT}::test_production_configuration_fails_closed"),
    ),
    Mutation(
        "preflight_prints_database_secret",
        "apps/api/hub/ops/cli.py",
        '    except Exception:\n        checks.append(("BLOCK", "database", "unreachable or schema unavailable"))',
        '    except Exception:\n        print(settings.database_url)\n        checks.append(("BLOCK", "database", "unreachable or schema unavailable"))',
        pytest(f"{PILOT}::test_preflight_database_failure_is_sanitized"),
    ),
    Mutation(
        "zero_manager_passes_preflight",
        "apps/api/hub/ops/cli.py",
        '                    "PASS" if managers else "BLOCK",',
        '                    "PASS",',
        pytest(f"{PILOT}::test_preflight_blocks_zero_manager_and_schema_mismatch"),
    ),
    Mutation(
        "migration_mismatch_passes_preflight",
        "apps/api/hub/ops/service.py",
        '        state="PASS" if matches else "BLOCK",',
        '        state="PASS",',
        pytest(f"{PILOT}::test_preflight_blocks_zero_manager_and_schema_mismatch"),
    ),
    Mutation(
        "restore_fingerprint_loses_work_reports",
        "apps/api/hub/ops/cli.py",
        '    "work_reports",',
        "",
        pytest(f"{PILOT}::test_fingerprint_inventory_covers_restore_critical_data"),
    ),
    Mutation(
        "restore_fingerprint_loses_expenses",
        "apps/api/hub/ops/cli.py",
        '    "technician_expenses",',
        "",
        pytest(f"{PILOT}::test_fingerprint_inventory_covers_restore_critical_data"),
    ),
    Mutation(
        "restore_fingerprint_loses_durable_queue",
        "apps/api/hub/ops/cli.py",
        '    "accounting_mirror_refreshes",',
        "",
        pytest(f"{PILOT}::test_fingerprint_inventory_covers_restore_critical_data"),
    ),
    Mutation(
        "cleanup_deletes_business_revisions",
        "apps/api/hub/ops/service.py",
        "    if apply:\n        if form_ids:",
        '    if apply:\n        await db.execute(text("DELETE FROM work_report_revisions"))\n        if form_ids:',
        pytest(f"{PILOT}::test_cleanup_is_bounded_idempotent_and_preserves_business"),
    ),
    Mutation(
        "cleanup_targets_fresh_sessions",
        "apps/api/hub/ops/service.py",
        "                TechnicianFormSession.expires_at <= stamp,",
        "                TechnicianFormSession.expires_at >= stamp,",
        pytest(f"{PILOT}::test_cleanup_is_bounded_idempotent_and_preserves_business"),
    ),
    Mutation(
        "stale_worker_reported_running",
        "apps/api/hub/ops/service.py",
        '    if not fresh:\n        return ComponentHealth(state="STALE", message="Worker heartbeat is stale.")',
        '    if False:\n        return ComponentHealth(state="STALE", message="Worker heartbeat is stale.")',
        pytest(f"{PILOT}::test_stale_enabled_worker_is_not_reported_running"),
    ),
    Mutation(
        "db_down_health_says_healthy",
        "apps/api/hub/main.py",
        '        await db.execute(text("SELECT 1"))',
        "        pass",
        pytest(f"{PILOT}::test_public_health_fails_closed_when_database_is_down"),
    ),
    Mutation(
        "wildcard_origin_accepted",
        "apps/api/hub/core/config.py",
        '                or parsed.hostname == "*"',
        "                or False",
        pytest(f"{PILOT}::test_production_configuration_fails_closed"),
    ),
    Mutation(
        "production_debug_accepted",
        "apps/api/hub/core/config.py",
        '        if self.debug and self.app_env not in {"development", "test"}:',
        "        if False:",
        pytest(f"{PILOT}::test_production_configuration_fails_closed"),
    ),
    Mutation(
        "container_recreation_loses_canonical_volume",
        "compose.yaml",
        "      - postgres_data:/var/lib/postgresql",
        "      - /var/lib/postgresql",
        pytest(
            f"{PILOT}::test_normal_compose_retains_canonical_named_volume_and_safe_backup_drill"
        ),
    ),
    Mutation(
        "automatic_retry_after_ambiguous_send",
        "apps/api/hub/schedule_delivery/service.py",
        '            elif any(d.status == "AMBIGUOUS" for d in previous):',
        "            elif False:",
        pytest("apps/api/tests/test_schedule_delivery.py::test_provider_outcomes"),
    ),
    Mutation(
        "production_sample_database_password_accepted",
        "apps/api/hub/core/config.py",
        '        if self.app_env not in {"development", "test"} and database.password in {',
        "        if False and database.password in {",
        pytest(f"{PILOT}::test_production_configuration_fails_closed"),
    ),
    Mutation(
        "remote_http_production_origin_accepted",
        "apps/api/hub/core/config.py",
        '            if parsed.scheme == "http" and (',
        "            if False and (",
        pytest(f"{PILOT}::test_origin_edge_cases_fail_closed"),
    ),
    Mutation(
        "preflight_prints_encryption_key",
        "apps/api/hub/ops/cli.py",
        '    if settings.google_mode == "real":\n        checks.append(',
        '    if settings.google_mode == "real":\n        print(settings.google_calendar_credential_encryption_key.get_secret_value())\n        checks.append(',
        pytest(f"{PILOT}::test_preflight_never_prints_provider_or_encryption_secrets"),
    ),
    Mutation(
        "disabled_worker_reports_error",
        "apps/api/hub/ops/service.py",
        '    if disabled:\n        return ComponentHealth(state="DISABLED", message="Feature is intentionally disabled.")',
        '    if False:\n        return ComponentHealth(state="DISABLED", message="Feature is intentionally disabled.")',
        pytest(f"{PILOT}::test_worker_state_classification_is_truthful"),
    ),
    Mutation(
        "operations_health_becomes_anonymous",
        "apps/api/hub/auth/middleware.py",
        'PUBLIC_PATHS = {"/api/health", "/api/auth/login"}',
        'PUBLIC_PATHS = {"/api/health", "/api/auth/login", "/api/operations/health"}',
        pytest(f"{PILOT}::test_operations_health_is_manager_only_and_truthful"),
    ),
    Mutation(
        "backup_failure_keeps_published_artifacts",
        "scripts/backup-postgres.ps1",
        "    if (-not $published) {",
        "    if ($false) {",
        pytest(f"{PILOT}::test_backup_publishes_only_complete_unique_dump_manifest_pairs"),
    ),
    Mutation(
        "cleanup_dry_run_mutates",
        "apps/api/hub/ops/service.py",
        "    if apply:\n        if form_ids:",
        "    if True:\n        if form_ids:",
        pytest(f"{PILOT}::test_cleanup_is_bounded_idempotent_and_preserves_business"),
    ),
    Mutation(
        "mirror_lag_claimed_financial_corruption",
        "apps/api/hub/ops/service.py",
        '        status = "WARN"',
        '        status = "BLOCK"',
        pytest(
            f"{PILOT}::test_optional_mirror_lag_is_operational_warning_not_financial_corruption"
        ),
    ),
    Mutation(
        "wrong_credential_key_is_tolerated",
        "scripts/verify_backup_restore.py",
        '                raise RuntimeError("A wrong credential key unexpectedly decrypted restored data.")',
        "                pass  # mutation: tolerate wrong-key decryption",
        pytest(f"{PILOT}::test_restore_drill_covers_all_durable_queues_audit_and_wrong_key"),
    ),
    Mutation(
        "canonical_business_data_written_to_api_filesystem",
        "compose.yaml",
        "  api:\n    build:",
        '  api:\n    volumes: ["./data:/app/data"]\n    build:',
        pytest(
            f"{PILOT}::test_normal_containers_do_not_store_canonical_business_data_on_app_filesystems"
        ),
    ),
    Mutation(
        "production_test_encryption_key_accepted",
        "apps/api/hub/core/config.py",
        "            if self.app_env not in {",
        "            if False and self.app_env not in {",
        pytest(f"{PILOT}::test_production_rejects_documented_test_encryption_keys"),
    ),
    Mutation(
        "worker_freshness_threshold_ignores_database_clock",
        "apps/api/hub/ops/service.py",
        "        heartbeat and stamp - heartbeat <= timedelta(seconds=FRESH_SECONDS)",
        "        heartbeat and stamp - heartbeat <= timedelta(seconds=0)",
        pytest(f"{PILOT}::test_worker_freshness_threshold_uses_database_clock"),
    ),
)


def replace_occurrence(text: str, old: str, new: str, occurrence: int) -> str:
    positions: list[int] = []
    start = 0
    while True:
        found = text.find(old, start)
        if found < 0:
            break
        positions.append(found)
        start = found + len(old)
    if occurrence >= len(positions):
        raise RuntimeError(f"mutation pattern missing: wanted {occurrence}, found {len(positions)}")
    found = positions[occurrence]
    return text[:found] + new + text[found + len(old) :]


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    paths = {ROOT / mutation.path for mutation in MUTATIONS}
    originals = {path: path.read_bytes() for path in paths}
    for mutation in MUTATIONS:
        count = originals[ROOT / mutation.path].decode("utf-8").count(mutation.old)
        if count <= mutation.occurrence:
            raise RuntimeError(f"mutation preflight failed for {mutation.name}: found {count}")
    results = []
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    environment["PATH"] = r"C:\Program Files\nodejs;" + environment.get("PATH", "")
    try:
        for mutation in MUTATIONS:
            path = ROOT / mutation.path
            original = originals[path]
            mutated = replace_occurrence(
                original.decode("utf-8"), mutation.old, mutation.new, mutation.occurrence
            )
            path.write_text(mutated, encoding="utf-8", newline="")
            completed = subprocess.run(
                mutation.command,
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=240,
                check=False,
            )
            results.append(
                {
                    "name": mutation.name,
                    "detected": completed.returncode != 0,
                    "returncode": completed.returncode,
                    "tail": (completed.stdout + completed.stderr)[-500:],
                }
            )
            path.write_bytes(original)
    finally:
        for path, original in originals.items():
            path.write_bytes(original)
    restored = all(path.read_bytes() == original for path, original in originals.items())
    report = {
        "detected": sum(item["detected"] for item in results),
        "total": len(results),
        "restored": restored,
        "source_hashes": {
            str(path.relative_to(ROOT)): digest(data) for path, data in originals.items()
        },
        "results": results,
    }
    output = ROOT / ".local" / "stage10-mutations.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("detected", "total", "restored")}))
    if report["detected"] != report["total"] or not restored:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
