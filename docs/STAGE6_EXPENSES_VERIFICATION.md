# Stage 6 expenses verification

Started at `e16a3634ac086a59c40911055c02e2651c4b5332` on
`codex/stage5-work-reports-quality-audit`, with a clean tree. Implemented on
`codex/stage6-expenses`. No push. Legacy reference was read-only
`C:/Users/rasha/OneDrive/Documents/ChatGPT/ez_telega_bot`; the older
`C:/HVAC_TECH_CODEX` was not used.

## Scope and parity

[Legacy inventory](LEGACY_EXPENSE_INVENTORY.md) records source paths, all 21 requested
behavior areas and PRESERVE/IMPROVE/DEFER/REMOVE decisions. Latest legacy fields are
required free-text expense type, nonnegative Decimal amount (zero is accepted),
optional note, and server-owned technician-local submission date. There is no
receipt field/category enum in the current legacy expense schema. Google Forms,
per-technician URL mappings, Sheet intake and Discord are absent dependencies.

[Product behavior](EXPENSES.md) documents the shared capability, money bounds,
explicit timezone setup, browser receipt, distinct same-value expenses, immutable
revision 1, current-revision selector, manager totals and retained security limits.
No Contracts, Receipt/Service Contract, Daily/Weekly Accounting, payout, GPS,
Moto Watchdog, approval/payment/reimbursement workflow or Stage 7 implementation.

## Independent implementation review

Reviewed wrong-technician writes, transferable bearer replay, financial duplicates,
float/rounding, timestamp attribution, immutable history, physical technician deletion,
receipt scope, audit/log leakage and cross-technician browser state.

No unresolved CRITICAL or HIGH implementation finding. A real browser probe found
that a second expense link in the same tab changed only its fragment and retained the
first receipt. The fix observes fragment changes, clears prior capability state,
and ignores responses associated with a previous token. A dedicated UI regression
and the browser two-identical-expense workflow verify the fix.

The first full backend run had one old exact welcome-message assertion expecting
only Submit Report; the new advertised Expenses entry is intentional and the
assertion was updated. All other 1,113 tests passed in that run. A timed-out browser
probe left a synthetic binding in the disposable DB; repeated runs now use unique
fictional actor IDs. No normal development record was used as a test fixture.

No manager correction API exists. Revision/identity UPDATE and DELETE are blocked by
DB triggers; advancing future correction pointers requires an explicit future
migration. Direct SQL probes cover negative/nonfinite money, empty/markup type,
oversized note, duplicate/gapped/future revisions, orphan records, invalid zone/date,
partial sessions, wrong expense/session owner and technician deletion.

## Verification evidence

All logs and screenshots are local ignored artifacts, not repository secrets.
All required engineering gates are complete. Dedicated live-provider acceptance and release-policy obligations remain open as recorded below.

The migration validator intentionally retains synthetic protected Work Report history.
Before reusing that disposable database for browser tests, the guarded cleanup action
clears those fixtures; otherwise the Google reset helper correctly hits the retention
FK. The complete browser rerun includes this test-environment handoff cleanup.

| Gate                                  | Result / evidence                                                                                                                                                                                                                                |
| ------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Full PostgreSQL backend               | 1,118 passed, 2 Windows POSIX-only skips, 3 upstream warnings in 648.87 seconds; `.local/stage6-backend-final.log` and XML                                                                                                                       |
| Expense tests                         | 87 expense tests passed in final full-suite XML (83 passed in initial focused run)                                                                                                                                                               |
| Financial/concurrency/history         | Passed: 20 identical concurrent submits, changed retry, second genuine same-value expense, inactive/rebind/delete races, bounded current list versus unbounded today total and immutable history, plus latest-only synthetic revision-2 selector |
| Frontend                              | 120 passed, 9 files; `.local/stage6-frontend-final.log`                                                                                                                                                                                          |
| Development Playwright                | 27 passed (3.9 minutes); `.local/stage6-development-browser-verified.log`                                                                                                                                                                        |
| Production-image Playwright           | 27 passed (3.2 minutes); `.local/stage6-production-browser.log`                                                                                                                                                                                  |
| Native production build / TS / ESLint | Passed; `.local/stage6-build-final.log`, `stage6-typecheck-final.log`, `stage6-eslint-final.log`                                                                                                                                                 |
| Ruff / format                         | Passed: 136 Python files; full Prettier check passed                                                                                                                                                                                             |
| Contracts                             | OpenAPI matches application; OpenAPI and TypeScript regeneration is byte-identical                                                                                                                                                               |
| Migrations                            | Fresh → head; populated historical stages → head; populated audited Stage 5 → Stage 6; protected populated rollback; empty Stage 6 downgrade/re-upgrade; one head; zero drift all passed in `.local/stage6-migrations.log`                       |
| Docker                                | API/Web final builds, normal development upgrade and isolated production startup/health passed; isolated web uses port 3009 (existing CLI stack on 3007 left untouched)                                                                          |
| Worker entrypoints                    | Both disabled workers exit without initializing a provider, in containers with no network; 2 Linux real-terminal password tests pass                                                                                                             |
| Mutation tests                        | 14/14 detected; exact source bytes restored; DB plugin restores constraints/triggers; `.local/stage6-mutations.json`                                                                                                                             |
| Secret scan                           | 256 Git-visible files, zero findings; synthetic expense capability positive control detected                                                                                                                                                     |
| Privacy scan / screenshot review      | 70 artifacts/bundles and 2 container logs, zero findings; 375px development and production forms plus read-only manager detail visually reviewed                                                                                                 |
| Diff check                            | Passed, including final documentation                                                                                                                                                                                                            |

## Mutation inventory

1. Bypass expiry.
2. Accept client technician identity field.
3. Remove binding generation validation.
4. Admit negative monetary values.
5. Convert Decimal through float (FloatOperation trap proves detection).
6. Bypass used-session receipt handling.
7. Fuzzy-deduplicate two genuine same-value expenses.
8. Log financial payload.
9. Return capability in success response.
10. Accept manager request without technician capability.
11. Remove no-store.
12. Remove no-referrer.
13. Disable revision immutability.
14. Allow technician deletion to cascade through expense history.

Receipt-validator bypass is not applicable: no receipt input/storage exists. Unknown
URL/file fields are rejected. Mutations were temporary test probes, never built or
deployed; positive-control artifacts are sanitized before the final privacy scan.

## Development data and operational boundary

Normal `technician-hub_postgres_data` was not reset, removed or recreated. Only the
API/web services were replaced after additive migration. PostgreSQL/API health and
web login HTTP 200 were verified. Normal API Google and Telegram modes remain
`disabled`, schedule delivery remains false. Before/after opaque row fingerprints
confirm existing technicians, managers, work reports/revisions, calendars and
Telegram bindings were preserved exactly; no row contents were exported. No manager
account was seeded, altered, or used by automated tests.

Running API image service/router/migration SHA-256 values match the reviewed files;
no `.local` or `.env` is baked into the image.

The normal DB is at `f6e609180001` with zero schema drift. Existing technician
accounting timezones remain NULL pending explicit manager configuration. Destructive
suites use only `technician_hub_test`: backend/mutations on loopback 5437, migration
and browser tests on isolated Stage 6 Compose loopback 5446. Stage 6 temporary containers
were stopped after all gates; no volumes were deleted. The pre-existing CLI test stack
and normal development stack remain running. No real Google/Telegram,
technician/customer provider interactions or live acceptance were performed.

## Remaining release gates

No debt closed or renumbered. TD-030 includes Expense dedicated TEST mobile/browser/
Telegram acceptance and transferable bearer approval. TD-031 includes expense/form
retention, immutable-note archival/anonymization and backup policy. No upload policy
is claimed. TD-013 also covers explicit timezone configuration edits.

31 entries: 10 RESOLVED, 21 OPEN (0 CRITICAL, 2 HIGH, 16 MEDIUM, 3 LOW).
Pilot blockers: TD-010/011/012/013/014/017/018/022/023/025/026/027/028/029/030/031.
Production additionally: TD-016/019/020. TD-015/024 remain later scale. TD-014 remains
overdue. Feature implementation and fake-provider verification are not pilot or
production approval. Deferred correction/void UI, receipt storage and full accounting
are scope boundaries, not newly claimed completed features.

## Completion

Final branch: `codex/stage6-expenses`. Commit message: `feat: add technician expenses`.
The commit containing this report includes the implementation, additive migration,
contracts, tests and documentation; ignored local evidence is retained outside Git.
Nothing was pushed. Existing manager CLI files/tests are byte-unchanged from the
Stage 5 audited commit. Normal volume and opaque row fingerprints were checked again
after all automated verification and match the pre-upgrade baseline.
