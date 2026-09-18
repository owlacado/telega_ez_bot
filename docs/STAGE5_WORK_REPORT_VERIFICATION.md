# Stage 5 Work Report verification

Verification date: 2026-09-18. Target repository: `C:\HVAC_TECHNICIAN_HUB`.
This is local/fake-provider implementation evidence, not pilot/production approval.

## Baseline and scope

- Starting branch: `codex/stage4-schedule-delivery-quality-audit`.
- Starting HEAD: `a0f19b5684b2781268d908ca1f613f0c1bfb4da4`; working tree clean.
- Stage 5 branch: `codex/stage5-work-reports`.
- Commit subject: `feat: add technician work reports`. The final commit identifier
  is reported in the delivery message; a document cannot contain its own commit hash.
- Legacy source was inspected read-only at
  `C:\Users\rasha\OneDrive\Documents\ChatGPT\ez_telega_bot`.
  `C:\HVAC_TECH_CODEX` was not inspected or used as a business-rule source.
- No real Google/Telegram/customer data was contacted. No push. Expenses,
  Contracts, Accounting and GPS were not started; existing placeholders remain.

Important environment discrepancy: before normal-stack restart or Stage 5 migration,
read-only checks found **zero managers and zero technicians** in the actual normal
`technician_hub` database used by its API. The database mounts the existing
`technician-hub_postgres_data` volume at `/var/lib/postgresql`. Thus there was no
existing manager record available to demonstrate preservation. No replacement
manager was created and no development volume was deleted. Populated migration
fixtures separately prove preservation of fictional manager and technician records.

After the passing isolated suites, the normal API/web were recreated on the final
images (database container and named volume were not recreated). The additive
migration reached `e5f509180001`; manager/technician/report counts remain 0/0/0.
Alembic reports no drift, database-backed health is OK, and the web login returns
HTTP 200. Both providers remain disabled. No manager was deleted or recreated.

## Domain and parity evidence

[LEGACY_WORK_REPORT_INVENTORY.md](LEGACY_WORK_REPORT_INVENTORY.md) records the
32-item source-backed PRESERVE / IMPROVE / DEFER / REMOVE matrix, including exact
legacy files, removed building number, card alias, reviews, closer and maintenance.
The actual current legacy code is already relational; Google Forms/Sheets identity
mapping and Discord are not dependencies to reproduce. Calendar write-back,
downstream Sheets accounting, corrections and full group report broadcasts are
explicitly deferred. Form success is preserved; Telegram post-submit notification
is optional and not implemented.

[WORK_REPORTS.md](WORK_REPORTS.md) documents all Stage 5 behavior and the safe local
and later dedicated TEST-provider runbooks. No live acceptance was executed.

WorkReport has one technician/calendar/occurrence identity and exact current
revision pointer. WorkReportRevision stores immutable Decimal money, canonical
payment/outcome, MYSELF/CALL_CENTER, three integer review counts, maintenance,
bounded notes and minimal frozen job facts. Report/session/revision completion is
one transaction. Database checks, unique keys, deferred current-revision FK,
RESTRICT history references and immutable triggers backstop domain checks.

There is no invented report-type enum: ESTIMATE and CANCEL are zero-amount payment
outcomes. Forced zero is centralized for API/UI metadata and independently checked
by PostgreSQL. CASH_APP normalizes to CREDIT_CARD. Money is a currency string at
the boundary and Decimal/NUMERIC(12,2) internally, never binary float.

## Security and recovery review

The selected design is an actor-verified private issuance plus opaque bearer form
capability, **not Telegram Mini App initData authentication**. A deliberately shared
or stolen live link transfers the capability; this is documented rather than
represented as independent browser-actor proof. Accepting that threat model,
HTTPS/origin deployment and real TEST-client acceptance remain TD-030/TD-012 gates.

- Issuance checks private user == chat, non-bot/non-anonymous actor, active technician,
  connected/available binding and verified bot. Group entry is deferred.
- Random 256-bit capability, SHA-256 storage, purpose and generation/user/bot binding,
  configurable 600-900 second TTL, at most five OPEN forms on issuance.
- Three exact form POST routes only; trusted Origin and custom header, 32 KiB
  streamed limit, duplicate JSON/unknown business-field rejection. Manager and
  technician credentials cannot substitute for one another.
- Fragment credential never enters a request URL. No localStorage, third-party
  form scripts or token-list endpoint. No-store/no-referrer API responses.
- Existing Stage 3 job projection supplies numbering/timezone/filtering; no second
  filter. Opaque choice IDs, server-only technician/calendar/occurrence identity.
- Reassignment before selection is rejected. A selected snapshot survives provider
  failure, event changes, assignment removal and midnight within session validity.
  Rebind/disconnect/inactive state still rejects old credentials.
- Technician -> binding -> session lock order serializes lifecycle and submission.
  Same normalized payload replays one receipt, including a lost response; changed
  payload conflicts. A second form for the same job cannot create revision 2.
- Submitted receipts may be reopened after TTL while the binding remains current;
  no fresh submission becomes possible. Abandoned snapshot purge is explicitly
  deferred under TD-031, not claimed complete.
- Provider confirmation cannot roll back money: no post-submit provider call or
  notification queue exists in this stage. The browser receipt is authoritative.
- Business history blocks technician deletion; deactivate instead. Historical facts
  survive manager reads after deactivation. No money/revision mutation endpoint.
- Audit references contain action/target/actor kind, not full payload, address,
  token/hash or notes. Technician audit actor_id is null because that pre-existing
  FK points to managers; session/report target resolves the actual owner.

## Separate self-audit pass

The implementing agent performed a separate adversarial review; this was not an
external or delegated audit. Review covered attribution, duplicate money, decimal
precision, zero outcomes, review/closer corruption, immutable history, capability
replay, PII leakage, deletion races, confirmation coupling and date/time boundaries.

Issues fixed during implementation/review:

1. Removed an incorrect use of technician UUID in the manager-only audit actor FK.
2. Added assignment validation before snapshot selection and bounded existing-report
   lookup to picker occurrences rather than scanning complete history.
3. Added exact duplicate-JSON/body/extra-field bounds and explicit string money in
   generated request contracts.
4. Fixed shared sibling React keys between profile and reports; panel state still
   resets on technician changes, with distinct keys.
5. Removed duplicate job-number display; preserved literal HTML-like notes and
   safe mobile layout, exact retry payload and synchronous double-tap lock.
6. Updated two pre-existing Telegram test expectations for the new command/settings
   argument. Fixed fake-provider grant persistence assumptions and Next route-announcer
   ambiguity in the new browser test, without weakening business assertions.
7. Strengthened direct SQL uniqueness tests with a valid associated revision, and
   added actual 23:58 -> 00:03 calendar-local and submission-winning-delete cases.

No unresolved Stage 5 CRITICAL/HIGH implementation finding remains in this review.
The pre-existing HIGH TD-010/011 obligations remain OPEN, not silently closed.

## Mutation experiments

All twelve deliberately broken variants were detected (each selected test exited
1). Source and test-database constraints were restored before the clean regression
run. No mutation implementation is included in the commit.

| Deliberate defect                                     | Detecting test                                                  |
| ----------------------------------------------------- | --------------------------------------------------------------- |
| Trust browser technician_id                           | payload_spoof_and_bounds[extra0]                                |
| Trust browser event_id                                | payload_spoof_and_bounds[extra2]                                |
| Ignore expiry                                         | invalidated_form_fails_closed[expire]                           |
| Accept changed submitted payload                      | full_flow_snapshot_privacy_receipt_manager_retention            |
| Remove forced-zero normalization                      | exact_legacy_payment_and_money[ESTIMATE]                        |
| Use float money                                       | exact_legacy_payment_and_money[CASH]                            |
| Drop PostgreSQL canonical unique constraint           | database_checks_reject_direct_writes[duplicate_identity]        |
| Disable immutable revision trigger                    | direct_sql_immutable_history_and_retention[UPDATE revision]     |
| Ignore user/generation rebind                         | invalidated_form_fails_closed[rebind]                           |
| Change technician history FK to CASCADE               | business_history_foreign_key_is_restrict                        |
| Insert failing confirmation inside submit transaction | rollback_before_commit_recoverable_and_no_confirmation_coupling |
| Log full submitted payload                            | full_flow_snapshot_privacy_receipt_manager_retention            |

Database variants ran against guarded disposable PostgreSQL, never development
data. The confirmation mutation inserts a forbidden coupling to prove detection;
it does not imply an actual report-confirmation queue exists.

## Release gate results

| Gate                                      | Result                                                                                                                         |
| ----------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------ |
| Full backend, real PostgreSQL             | **912 passed**, 565.71 s; 3 existing PTB retry_after deprecation warnings                                                      |
| Focused Work Reports + concurrency        | **74 passed**, 49.03 s: 58 report/domain/security tests + 16 concurrency/direct-integrity tests                                |
| Frontend complete suite                   | **107 passed**, 8 files; includes mobile form and manager report components                                                    |
| Development Playwright                    | **22 passed**, 3.6 min; no duplicate-key warnings after fix                                                                    |
| Production-image Playwright               | **22 passed**, 2.9 min on freshly started final images                                                                         |
| Native production Next build              | Passed, including generated page/type validation                                                                               |
| Strict TypeScript / ESLint / Prettier     | Passed                                                                                                                         |
| Ruff / Python format                      | Passed (151 Python files checked)                                                                                              |
| OpenAPI + TypeScript contract determinism | Regeneration is byte-for-byte identical; application schema snapshot matches                                                   |
| Alembic fresh/populated/round-trip/drift  | Passed; one head e5f509180001; Stage 0-4 preservation plus Stage 5 protected populated rollback and empty downgrade/re-upgrade |
| Compose config / API and Web image builds | Passed                                                                                                                         |
| Isolated production-image startup         | Healthy, loopback ports 3006/5443, tmpfs PostgreSQL, only fake providers                                                       |
| Disabled worker startup                   | Telegram and schedule workers exit without initializing any provider                                                           |
| Mutation experiments                      | 12/12 detected; restored source/constraints                                                                                    |
| Secret scan                               | 233 Git-visible files, zero findings; includes new literal Work Report capability rule                                         |
| git diff --check                          | Passed                                                                                                                         |

Backend regression coverage includes Stage 0 identity/auth, Telegram onboarding and
security, Stage 2 Google catalog, Stage 3 event projection, Stage 4 delivery/audit,
Stage 5 reports, concurrency and privacy/redaction. No suites shared a test database
concurrently: backend used loopback 5443 while development Playwright used 5437.

The expanded browser flow submits a paid report with synchronous double-click,
opens a stable receipt on reload, reads every fact in the manager modal, then opens
another job, selects ESTIMATE, removes assignment and disconnects the fake Google
connection after selection. It sends a malicious nonzero amount, lets the server
commit, deliberately loses the response, and retries the unchanged form payload.
The result is exactly two reports, with ESTIMATE persisted as 0.00. Backend tests
also inject a provider outage, check CANCEL=0, race 20 identical submissions, race
two distinct forms, exercise both lifecycle lock orders, and cross actual local
midnight while retaining the selected operational date.

Mobile (375 px) and manager screenshots were rendered and visually reviewed.
They show no horizontal overflow, readable inputs, literal HTML-like notes, and
complete read-only facts. Screenshots contain only fictional data and remain
ignored local test artifacts, not committed assets.

Commands used: `python -m pytest apps/api/tests -q`, the two focused Stage 5 test
files, `npm test`, `npm run test:e2e -w apps/web` with native dev servers and the
isolated production base URL, `npm run build`, `typecheck`, `lint`, `format:check`,
`ruff check .`, `ruff format --check .`, `scripts/validate_migrations.py`,
`scripts/check_contracts.py`, `python -m hub.export_contracts`,
`npm run contracts:generate`, `docker compose config --quiet`, image builds,
isolated `up -d --wait`, disabled worker runs, `scripts/scan_secrets.py` and
`git diff --check`. Use the existing local venv and guarded test DB settings.

## Retained gates

TD-030 adds dedicated Work Report TEST acceptance and bearer-link threat review;
TD-031 adds business/form-history retention, anonymization and backup/purge policy.
No previous debt item was resolved: **31 total, 10 RESOLVED, 21 OPEN**; open severity
is 0 CRITICAL, 2 HIGH, 16 MEDIUM, 3 LOW.

Pilot blockers: TD-010/011/012/013/014/017/018/022/023/025/026/027/028/029/030/031.
Production additionally requires TD-016/019/020. TD-015/024 remain later-scale items.
Local green tests do not authorize pilot rollout or real provider use.
