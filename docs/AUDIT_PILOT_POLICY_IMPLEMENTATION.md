# Independent pilot-policy implementation audit

Audit date: 2026-09-20

Audited branch baseline: `codex/pilot-policy-implementation` at `cf9d1ef`

Audit branch: `codex/pilot-policy-implementation-quality-audit`

## Disposition

**PILOT READY: NO.** The approved application policy controls now pass the independent local audit. Four selected-deployment operational gates (TD-012, TD-017, TD-025, TD-029) and five live TEST-provider acceptance gates (TD-022, TD-027, TD-028, TD-030, TD-033) remain open. No real Google or Telegram endpoint or account was contacted.

The audit found one High, two Medium, and one Low implementation defect. All were corrected and covered by regression or mutation checks. No known implementation blocker remains within TD-010, TD-011, TD-013, TD-018, TD-023, TD-026, or the controlled TEST-pilot part of TD-031.

## Findings and fixes

| ID | Severity | Finding | Correction and evidence |
| --- | --- | --- | --- |
| AP-01 | HIGH | Telegram admission counters committed before application processing. A crash after admission could charge a retry again; at a tight boundary the retry could become `RATE_LIMITED`, advance the durable offset, and lose an already-accepted action. | Each `(bot_id, update_id)` now serializes under a PostgreSQL advisory guard. Admission and an `ADMITTED` processed-update reservation commit together. A retry resumes that reservation without consuming another admission unit, and the final business outcome replaces it in the business transaction. Crash/retry and one-unit boundary regressions pass. |
| AP-02 | MEDIUM | Callback updates were not written to `telegram_processed_updates`, allowing callback replay and breaking a durable dedupe/offset invariant. Concurrent duplicates could also consume more than one admission unit. | Callback outcomes now finalize the durable reservation. Four concurrent deliveries produce one action and three `DUPLICATE` results. Callback replay invokes the action once. |
| AP-03 | MEDIUM | The first `record_version` migration bumped for display-only assignment labels and absent-equivalent Telegram/schedule rows. It also did not explicitly reject raw primary-key replacement. Those behaviors exceeded or escaped the approved effective-state boundary. | Additive migration `fda609200001` makes technician identity database-owned, ignores assignment label-only writes, treats a default disconnected Telegram row as absent, and treats a disabled schedule row as absent. Effective changes still bump once per affected technician and transaction. Direct SQL, concurrent commit, rollback, exact-once, and API-current-version tests pass. |
| AP-04 | LOW | Seven weekly-XLSX tests depended on fixture creation using the wall clock. The full gate crossed UTC midnight after the fixed report week and excluded otherwise empty technicians. | The affected fixtures now set an explicit in-week `created_at`. This only removes clock dependence from tests; export behavior is unchanged. |

## Policy invariants

### TD-010 - permanent technician deletion

The manager UI exposes deactivation rather than permanent deletion. The normal API returns 409 for DELETE, and PostgreSQL rejects a direct DELETE. Deactivation remains supported. Work Reports, Expenses, revisions, audit events, and other historical business data remain readable. The mutation that removed the database delete guard was detected.

### TD-011 - DL/SSN collection boundary

Manager create/update request schemas and the UI expose neither Driver License ID nor SSN last four. Extra API fields are rejected. PostgreSQL rejects any new non-null value, including a replacement for a legacy value. Existing legacy values are not erased automatically and remain omitted from manager response contracts. The generated OpenAPI and TypeScript contracts contain no removed write fields. The API-allowance mutation was detected.

### TD-018 - initials-only avatars

The technician transport schemas contain no external image URL. The manager UI has no URL input, upload path, or technician `<img>` fallback; the avatar component renders generated initials. PostgreSQL rejects new non-null `photo_url` values. The Web CSP permits `img-src 'self'`, which is compatible with the actual initials-only UI and framework assets.

### TD-023 - Telegram admission and retention

Effective defaults and boundary checks are:

- 30 actions per 60 seconds per sender;
- 10 actions per 10 seconds per sender;
- 300 actions per 60 seconds globally per bot;
- seven-day processed-update retention;
- cleanup only when the processed update is older than the retention boundary and its `update_id` is below the same bot worker's durable `next_update_id`.

Admission uses database-backed buckets. Duplicate delivery consumes no additional unit. An accepted update has a durable `ADMITTED` reservation before business work; retries resume it, so rate limiting cannot discard already-accepted work. A finalized or rate-limited update is durably deduplicated. Callback updates follow the same durable boundary. The disable-admission mutation was detected.

### TD-026 - Google manager admission

Effective defaults and boundary checks are:

- OAuth start: 5 per 15 minutes per manager and 20 per hour globally;
- manual Calendar scan/reconnect: 6 per 10 minutes per manager and 30 per hour globally;
- cleared OAuth-attempt metadata retention: seven days;
- existing state/PKCE TTL: 10 minutes, with existing single-use handling unchanged.

The limits wrap manager-initiated entry points only. Schedule, mirror, and provider workers retain their existing retry/backoff behavior and do not pass through manager admission. The disable-Google-limit and accidental-worker-limit mutations were detected.

### TD-031 - pilot retention and backup rotation

`cleanup_expired` does not delete or anonymize Work Reports, Expenses, either revision history, or audit events. It retains existing bounded cleanup for transient form snapshots, encrypted dispatch payloads, cleared OAuth attempts, expired sessions/invitations/rate buckets, and offset-safe Telegram metadata. The business-history deletion mutation was detected.

A synthetic execution of `backup-postgres.ps1` proved that the 30-day rotation deletes only complete, script-owned `technician-hub-YYYYMMDD-HHMMSS.dump` and matching `.sha256` artifacts older than the boundary. Arbitrary operator files, partial names, lookalikes, and newer artifacts were retained. Production retention, legal holds, anonymization, off-host storage, and final business/legal policy remain open.

## Exact `record_version` semantics

`technicians.record_version` starts at 1 and is owned by PostgreSQL. Direct writes to the version and direct changes to the technician primary key are rejected. A sanctioned update returns the current database value through the API.

A version bump occurs when effective state changes in any of these boundaries:

- protected technician profile: first name, last name, active/inactive status, accounting timezone, and changes that clear preserved legacy `photo_url`, Driver License ID, or SSN-last-four values;
- active assignment identity: technician, calendar, or active state;
- an assigned calendar's source, provider connection/calendar identity, availability, timezone, or exclusion state;
- the referenced current Google connection's current identity, status, generation, or granted scopes;
- private/work-group Telegram binding identity, status, generations, or availability once the binding differs from the default disconnected/unknown state;
- schedule-delivery enabled state.

Display labels, Telegram display metadata, disabled schedule-row presence, default disconnected Telegram-row presence, historical revisions, audits, queues, form sessions, mirror progress, and unrelated records do not bump the version.

The transaction-local helper records each affected technician once. Multiple relevant statements in one transaction therefore produce one increment. PostgreSQL row locking serializes concurrent transactions; two relevant committed transactions produce two monotonic increments without loss or regression. A rolled-back transaction rolls back both its row change and version increment. Moving an effective dependency between technicians marks each affected technician once.

## Generated transport contracts

OpenAPI and TypeScript contracts were regenerated twice. Both outputs were byte-identical and `git diff -- packages/contracts` is empty:

- OpenAPI SHA-1: `2a5be54fe2d26d428a5fe67a40f17ab66877fd21`
- TypeScript schema SHA-1: `fedb584f3c8ab4656a01a509a5384391006bbe4e`

The generated diff contains no Contracts/Receipt product surface and no GPS work.

## Verification

- Focused PostgreSQL/API audit sets: 23 passed, then 17 passed after the mutation restoration cycle; the eight initially failing full-suite cases passed as an exact rerun after their assertion/fixture corrections.
- Compact mutation set: 9 of 9 detected; every mutated source and migration was restored byte-for-byte.
- Final backend regression: 1,514 passed, 2 skipped, 3 dependency deprecation warnings.
- Frontend: typecheck passed; 11 test files and 148 tests passed; production build passed.
- Python: repository-wide Ruff lint passed; all 11 changed Python files passed Ruff format check.
- Secret scan: 339 Git-visible files, 0 findings.
- Migration lifecycle/drift validator: passed; single head `fda609200001`; fresh, historical, populated, downgrade/re-upgrade, and zero-drift paths passed.
- Docker: API and Web images built; both containers and the normal PostgreSQL container are healthy; `/api/health` reports `ok` and database `connected`.

## Normal database preservation

Before the first audit test, the normal database fingerprint was captured. All tests and mutations used only `technician_hub_test` on the disposable `test-db` service. After the final image rollout and additive migration, every table count and opaque digest matched the baseline exactly. The retained state remains one manager, one manager session, three calendars, zero technicians, and five audit events. The exact retained volume is still `technician-hub_postgres_data`. Its Compose identity and mount remained unchanged. The disposable test database was stopped after validation; the normal DB/API/Web remain healthy.

## Remaining blockers

Local operational blockers remain:

- TD-012: install and evidence the selected TEST deployment's TLS proxy, exact origins/trusted proxy boundary, and managed-secret delivery;
- TD-017: install the alert route, scheduled health/queue monitoring, and deployment request/connection budgets;
- TD-025: rehearse deployed synthetic credential recovery and then complete provider-dependent revoke/reconnect acceptance;
- TD-029: install schedule-worker supervision, claim/backlog alerting, key custody, and capacity ownership in the selected environment.

Live TEST blockers remain and were not exercised:

- TD-022: dedicated TEST Telegram bot/private chat/group acceptance;
- TD-027: dedicated TEST Google OAuth/Calendar acceptance;
- TD-028: combined TEST schedule delivery acceptance;
- TD-030: Work Report/Expense mobile Telegram and HTTPS acceptance;
- TD-033: dedicated TEST Spreadsheet mirror acceptance.

Pilot readiness becomes **YES** only after all four deployment controls are installed and evidenced, then the five live rows are executed in `PILOT_LIVE_ACCEPTANCE_PLAN.md` with fictional data and reviewed sanitized evidence.