# Legacy Google Sheets mirror inventory

The read-only legacy tree inspected for Stage 9 was
`C:\Users\rasha\OneDrive\Documents\ChatGPT\ez_telega_bot`. It is evidence of
familiar behavior, not authority for financial rules. Canonical rules remain the
audited PostgreSQL current revisions and `WeeklyAccounting` projection.

## PRESERVE

- Manager-supplied Individual and All Tech Spreadsheet identifiers.
- One Monday-Sunday tab named `YYYY-MM-DD - YYYY-MM-DD`.
- The familiar seven-day technician block with Expenses, Reviews, payment buckets,
  closer/activity counts, TOTAL, formatting, heights, and widths.
- Metadata lookup before tab creation, generated-content replacement, RAW values,
  and background refresh behavior.
- Evidence: `docs/GOOGLE_SHEETS_ACCOUNTING_EXPORT.md`, `accounting/google_ids.py`,
  `accounting/provider.py`, `accounting/mirror.py`, `tests/test_mirrors.py`, and
  `tests/test_parity.py`.

## IMPROVE

- Reuse audited Google OAuth, PKCE, encrypted credentials, and lifecycle generations
  instead of the legacy service-account path.
- Use a PostgreSQL generation queue, DB-clock leases, `SKIP LOCKED`, stale-owner
  protection, and worker heartbeat.
- Reconcile ambiguous `addSheet`; prefer stored numeric sheet IDs after renames.
- Clear the union of old/new app-owned extents while preserving outside sentinels.
- Serialize Decimal currency as exact text. Legacy converted Decimal to binary float.
- Reuse Stage 8 semantics, geometry, styles, and text normalization without
  recalculating totals in the Sheets path.

## REMOVE

- Any Sheet-cell authority over WorkReports, Expenses, identity, assignments, or totals.
- Drive browsing/file creation, arbitrary Sheet-content reads, business formulas,
  whole-spreadsheet clearing, and provider calls coupled to business commits.

## DEFER

- Spreadsheet creation, bulk historical backfill, arbitrary layout customization,
  manual-edit import, and real-provider acceptance.

## UNKNOWN

- No authoritative legacy workbook or pixel reference exists. Stage 9 targets
  semantic/style-role parity and documents provider-specific differences.
- Legacy behavior did not prove safe multi-consumer crash handling, exact large-money
  transport, or a policy for manual changes inside the generated range.
