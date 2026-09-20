"""Run Stage 9 mutation probes and restore every source file byte-for-byte."""

# ruff: noqa: E501

import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTEST = [str(ROOT / ".venv/Scripts/python.exe"), "-m", "pytest", "-q"]
QUALITY = "apps/api/tests/test_accounting_mirrors_quality_audit.py"
CORE = "apps/api/tests/test_accounting_mirrors.py"


@dataclass(frozen=True)
class Mutation:
    name: str
    path: str
    old: str
    new: str
    test: str
    occurrence: int = 0


MUTATIONS = (
    Mutation(
        "google_cells_as_authority",
        "apps/api/hub/accounting_mirrors/provider.py",
        '"sheets.properties(sheetId,title,gridProperties)",',
        '"includeGridData=true&fields=sheets.properties(sheetId,title,gridProperties)",',
        f"{QUALITY}::test_google_is_metadata_only_and_never_accounting_authority",
    ),
    Mutation(
        "google_inside_work_report_transaction",
        "apps/api/hub/work_reports/service.py",
        '        await enqueue_for_business_change(db, tech.id, date.fromisoformat(job["operational_date"]))',
        '        google_provider = object()\n        await enqueue_for_business_change(db, tech.id, date.fromisoformat(job["operational_date"]))',
        f"{CORE}::test_business_services_only_enqueue_and_never_call_google",
    ),
    Mutation(
        "remove_durable_work_report_enqueue",
        "apps/api/hub/work_reports/service.py",
        '        await enqueue_for_business_change(db, tech.id, date.fromisoformat(job["operational_date"]))',
        "        pass",
        "apps/api/tests/test_work_reports.py::test_full_flow_snapshot_privacy_receipt_manager_retention",
    ),
    Mutation(
        "lose_new_generation_during_finalize",
        "apps/api/hub/accounting_mirrors/worker.py",
        '            if valid and refresh.requested_generation <= current.requested_generation\n            else "PENDING"',
        '            if valid\n            else "PENDING"',
        f"{CORE}::test_change_during_sync_remains_pending_then_converges",
    ),
    Mutation(
        "stale_lease_owner_finalizes",
        "apps/api/hub/accounting_mirrors/worker.py",
        "            or refresh.claim_token != current.claim_token",
        "            or False",
        f"{QUALITY}::test_stale_owner_cannot_finalize_and_current_owner_renews_with_db_clock",
        occurrence=2,
    ),
    Mutation(
        "workers_claim_same_job",
        "apps/api/hub/accounting_mirrors/worker.py",
        ".with_for_update(skip_locked=True, of=AccountingMirrorRefresh)",
        "",
        f"{QUALITY}::test_worker_safety_structure_is_explicit",
    ),
    Mutation(
        "blind_ambiguous_add_sheet_retry",
        "apps/api/hub/accounting_mirrors/worker.py",
        "    return next((item for item in metadata if item.title == title), None)",
        "    return None",
        f"{CORE}::test_ambiguous_tab_creation_reconciles_without_duplicate",
    ),
    Mutation(
        "ignore_stored_sheet_id",
        "apps/api/hub/accounting_mirrors/worker.py",
        "    if current.google_sheet_id is not None:",
        "    if False:",
        f"{QUALITY}::test_rename_is_retained_by_sheet_id_and_delete_recreates",
    ),
    Mutation(
        "clear_beyond_owned_rows",
        "apps/api/hub/accounting_mirrors/provider.py",
        '                                "endRowIndex": rows,',
        '                                "endRowIndex": rows + 1000,',
        f"{CORE}::test_http_provider_uses_raw_and_shared_style_roles",
    ),
    Mutation(
        "fail_to_clear_shrink_remainder",
        "apps/api/hub/accounting_mirrors/worker.py",
        "                max(current.owned_rows, payload.row_count),",
        "                payload.row_count,",
        f"{QUALITY}::test_worker_safety_structure_is_explicit",
    ),
    Mutation(
        "fail_to_clear_stale_all_tech_blocks",
        "apps/api/hub/accounting_mirrors/worker.py",
        "                max(current.owned_rows, payload.row_count),",
        "                min(current.owned_rows, payload.row_count),",
        f"{QUALITY}::test_worker_safety_structure_is_explicit",
    ),
    Mutation(
        "clear_outside_owned_sentinel",
        "apps/api/hub/accounting_mirrors/worker.py",
        "                max(current.owned_columns, payload.column_count),",
        "                max(current.owned_columns, payload.column_count) + 4,",
        f"{CORE}::test_all_tech_grid_and_sentinel_outside_owned_range",
    ),
    Mutation(
        "user_entered_instead_of_raw",
        "apps/api/hub/accounting_mirrors/provider.py",
        "?valueInputOption=RAW",
        "?valueInputOption=USER_ENTERED",
        f"{CORE}::test_http_provider_uses_raw_and_shared_style_roles",
    ),
    Mutation(
        "decimal_to_float",
        "apps/api/hub/accounting_mirrors/presentation.py",
        '    return f"${value:,.2f}"',
        '    return f"${float(value):,.2f}"',
        f"{CORE}::test_exact_money_never_uses_binary_float",
    ),
    Mutation(
        "formula_text_executable",
        "apps/api/hub/accounting_mirrors/provider.py",
        "?valueInputOption=RAW",
        "?valueInputOption=USER_ENTERED",
        f"{CORE}::test_formula_text_and_scale_payloads_remain_bounded {CORE}::test_http_provider_uses_raw_and_shared_style_roles",
    ),
    Mutation(
        "omit_facebook_reviews",
        "apps/api/hub/accounting_mirrors/presentation.py",
        "        pair(index, REVIEW_LABELS[code], count)",
        '        pair(index, "" if code == "FACEBOOK" else REVIEW_LABELS[code], count)',
        f"{CORE}::test_google_presentation_uses_canonical_totals_and_buckets",
    ),
    Mutation(
        "merge_payment_buckets",
        "apps/api/hub/accounting_mirrors/presentation.py",
        "        pair(index, PAYMENT_LABELS[code], money(amount), amount=True)",
        '        pair(index, "Cash", money(amount), amount=True)',
        f"{CORE}::test_google_presentation_uses_canonical_totals_and_buckets",
    ),
    Mutation(
        "sheets_scope_silently_granted",
        "apps/api/hub/google_calendar/provider.py",
        "                *([SHEETS_SCOPE] if sheets_access else []),",
        "                SHEETS_SCOPE,",
        "apps/api/tests/test_google_calendar.py::test_official_oauth_pkce_offline_scope_and_cipher",
    ),
    Mutation(
        "sheets_revocation_breaks_calendar_compatibility",
        "apps/api/hub/google_calendar/service.py",
        "    sheets_access = payload.request_sheets_access or bool(",
        "    sheets_access = True or payload.request_sheets_access or bool(",
        "apps/api/tests/test_google_calendar.py::test_explicit_sheets_scope_upgrade_preserves_calendar",
    ),
    Mutation(
        "old_target_finalizes_replacement",
        "apps/api/hub/accounting_mirrors/service.py",
        "            await db.execute(\n"
        "                delete(AccountingMirrorRefresh).where(\n"
        "                    AccountingMirrorRefresh.target_id == target.id\n"
        "                )\n"
        "            )",
        "            pass",
        f"{CORE}::test_target_replacement_and_connection_generation_block_stale_finalize",
    ),
    Mutation(
        "disabled_target_auto_refreshes",
        "apps/api/hub/accounting_mirrors/service.py",
        "                AccountingMirrorTarget.enabled.is_(True),",
        "                AccountingMirrorTarget.enabled.is_not(None),",
        f"{QUALITY}::test_no_target_and_disabled_target_create_no_automatic_work",
    ),
    Mutation(
        "raw_provider_error_leaks",
        "apps/api/hub/accounting_mirrors/worker.py",
        '    except Exception:\n        await finalize_failure(factory, current, "PROVIDER_TEMPORARY_ERROR", retryable=True)',
        "    except Exception as exc:\n        await finalize_failure(factory, current, str(exc), retryable=True)",
        f"{QUALITY}::test_error_canaries_are_redacted_from_state_and_logs",
    ),
    Mutation(
        "sync_endpoint_without_manager_auth",
        "apps/api/hub/auth/middleware.py",
        "        if request.url.path in PUBLIC_PATHS:",
        '        if request.url.path in PUBLIC_PATHS or "accounting/mirror" in request.url.path:',
        f"{QUALITY}::test_mirror_routes_reject_anonymous_expired_or_inactive_manager",
    ),
    Mutation(
        "csrf_origin_bypass",
        "apps/api/hub/auth/middleware.py",
        "        if mutation and not hmac.compare_digest(",
        "        if False and mutation and not hmac.compare_digest(",
        f"{QUALITY}::test_config_and_sync_require_exact_origin_and_csrf",
    ),
    Mutation(
        "provider_call_holds_database_session",
        "apps/api/hub/accounting_mirrors/worker.py",
        "    lease_stop = asyncio.Event()",
        "    # async with factory(): provider I/O would hold a DB session\n    lease_stop = asyncio.Event()",
        f"{QUALITY}::test_worker_safety_structure_is_explicit",
    ),
    Mutation(
        "fake_provider_allowed_in_production",
        "apps/api/hub/core/config.py",
        '        if self.telegram_mode == "fake" or self.google_mode == "fake":',
        "        if False:",
        "apps/api/tests/test_google_calendar_audit.py::test_fake_provider_startup_cannot_escape_isolated_test_environment",
    ),
    Mutation(
        "fingerprint_skips_failed_job",
        "apps/api/hub/accounting_mirrors/worker.py",
        '            current.claimed_from_status != "FAILED"',
        "            True",
        f"{QUALITY}::test_failed_attempt_cannot_fingerprint_skip_retry",
    ),
    Mutation(
        "layout_version_omitted_from_fingerprint",
        "apps/api/hub/accounting_mirrors/presentation.py",
        '                "layout": LAYOUT_VERSION,',
        '                "layout": "",',
        f"{QUALITY}::test_layout_name_order_locale_timezone_and_formula_text_change_fingerprint",
    ),
)


def replace_occurrence(text: str, old: str, new: str, occurrence: int) -> str:
    positions = []
    start = 0
    while True:
        found = text.find(old, start)
        if found < 0:
            break
        positions.append(found)
        start = found + len(old)
    if occurrence >= len(positions):
        raise RuntimeError(
            f"mutation pattern missing (wanted {occurrence}, found {len(positions)})"
        )
    found = positions[occurrence]
    return text[:found] + new + text[found + len(old) :]


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main():
    paths = {ROOT / mutation.path for mutation in MUTATIONS}
    originals = {path: path.read_bytes() for path in paths}
    missing = []
    for mutation in MUTATIONS:
        count = originals[ROOT / mutation.path].decode("utf-8").count(mutation.old)
        if count <= mutation.occurrence:
            missing.append(f"{mutation.name}: wanted {mutation.occurrence}, found {count}")
    if missing:
        raise RuntimeError("mutation preflight failed: " + "; ".join(missing))
    results = []
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    try:
        for mutation in MUTATIONS:
            path = ROOT / mutation.path
            original = originals[path]
            text = original.decode("utf-8")
            mutated = replace_occurrence(text, mutation.old, mutation.new, mutation.occurrence)
            path.write_text(mutated, encoding="utf-8", newline="")
            tests = mutation.test.split()
            completed = subprocess.run(
                [*PYTEST, *tests],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                timeout=180,
            )
            detected = completed.returncode != 0
            results.append(
                {
                    "name": mutation.name,
                    "detected": detected,
                    "returncode": completed.returncode,
                    "tail": (completed.stdout + completed.stderr)[-500:],
                }
            )
            path.write_bytes(original)
    finally:
        for path, original in originals.items():
            path.write_bytes(original)

    restored = all(path.read_bytes() == original for path, original in originals.items())
    result = {
        "detected": sum(item["detected"] for item in results),
        "total": len(results),
        "restored": restored,
        "source_hashes": {
            str(path.relative_to(ROOT)): digest(data) for path, data in originals.items()
        },
        "results": results,
    }
    output = ROOT / ".local/stage9-quality-audit-mutations.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("detected", "total", "restored")}))
    if result["detected"] != result["total"] or not restored:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
