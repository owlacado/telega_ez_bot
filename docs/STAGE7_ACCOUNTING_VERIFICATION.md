# Stage 7 accounting verification

Starting branch `codex/stage6-expenses-quality-audit`, audited HEAD
`55ac012547d883624de69c4474d29c097b236483`; clean tree and healthy normal PostgreSQL/API/Web.
Implementation branch: `codex/stage7-accounting`. No reset, volume deletion, push or history rewrite.

## Scope and evidence

The legacy inventory and golden fixture preceded accounting production code.
[Inventory](LEGACY_ACCOUNTING_INVENTORY.md) records 36 rules, source evidence and
fingerprints. [Parity](ACCOUNTING_PARITY.md) identifies arithmetic preserved and the
explicitly requested operational-date normalization. No invented monetary formula,
financial settings, persisted totals, export renderer, Google mirror, Telegram Daily
delivery, Contracts, GPS, correction endpoint or Stage 8 work was added.

`hub/accounting/domain.py` owns all sums and projections. Service reads exactly the
current FK revision, not history; API/current overview use one PostgreSQL read-only
repeatable-read snapshot. Future correction and concurrent insertion probes show the
old coherent snapshot during the request and new values after refresh. Writes finish
within the five-second test deadline without business-row locks or deadlock.

No migration or new index: existing technician indexes plus unique current-revision
keys cover the measured access path. Large WorkReport EXPLAIN uses
`ix_work_reports_technician_id` and `uq_work_report_revision` with one indexed lookup
per parent; 1,000 current rows execute in 1.383 ms at the SQL plan level. Expense
index definitions include the corresponding technician index, unique revision key
and existing expense-date index. The small eight-parent expense follow-up plan
appropriately chooses sequential scans (0.125 ms). No forced planner setting was used.

## Accounting test / benchmark results

Final focused suite: **49 passed** in 66.46 seconds, isolated PostgreSQL.
Includes empty/day/week/category cases, golden daily and weekly values, all payment
outcomes, all review platforms, both closers, maintenance, two identical expenses,
zero expenses, latest report/expense revisions, repeated cents and maximum valid
amounts, DATE/DST/year/leap boundaries, inactive history, missing/changed timezone,
strict selectors, invalid UUID/ranges, authorization, no-store/privacy/no-read-audit,
corrupt pointers, deliberately bypassed database zero-outcome checks (transactionally restored), unexpected-error privacy, consistent concurrent insert/correction, and complete >100 Today.

Three serial samples per size and endpoint on local PostgreSQL, with N reports and
N expenses, each with two revisions. Includes ORM/domain materialization, excludes
HTTP/render time. Four service statements (isolation setup + context/time + two
current-fact reads); manager authentication adds fixed overhead. Concurrent full-suite
load is present, so these are practical measurements, not production capacity promises.

| Rows in each category | Projection | Statements | Median ms | Worst ms |
| --------------------: | ---------- | ---------: | --------: | -------: |
|                    10 | daily      |          4 |     20.87 |    21.30 |
|                    10 | weekly     |          4 |     16.22 |    16.66 |
|                   100 | daily      |          4 |     13.16 |    24.42 |
|                   100 | weekly     |          4 |     17.53 |    18.99 |
|                  1000 | daily      |          4 |     19.31 |    30.32 |
|                  1000 | weekly     |          4 |     51.61 |   125.43 |

No All-Tech financial overview was added, hence no new per-tech dashboard loop and
no applicable 10/50 All-Tech aggregation benchmark. Lifetime-parent/fleet scale is
retained under existing TD-015.

## Mutation evidence

**16/16 detected**, each source restored byte-for-byte:
all WorkReport history; all Expense history; server Today; Sunday-start week;
omitted Sunday; float money; identical expense collapse; nonzero Estimate/Cancel;
merged buckets; omitted Facebook; separate drifting weekly formula; frontend
recalculation; bounded recent-list Today; missing-zone UTC fallback; content logging;
removed manager authorization. Positive logging-control evidence is synthetic and
sanitized in its retained artifact. An initially weak zero-outcome test was corrected
to use a valid Decimal input before asserting the actual outcome guard.

## Self-review and fixes

No new CRITICAL/HIGH issue remains. Self-review tightened selector parsing to reject
numeric epoch/timestamp forms and require YYYY-MM-DD. Browser verification corrected
Windows-encoded test literals, improved accounting panel padding/wrapping, and waits
for the existing 180ms responsive sidebar transition before measuring mobile overflow.
Production-image accessibility also exposed an existing job-count badge at 3.33:1 contrast; its text color was darkened without weakening the audit.
The browser flow verifies known Today totals, Daily facts, all seven Weekly dates,
previous week, revision 2 replacement exactly once and browser Asia/Tokyo versus
technician America/Los_Angeles. Plain comments/notes never become HTML.

## Debt / limits

31 debt entries remain: 10 resolved, 21 open (0 Critical, 2 High, 16 Medium, 3 Low).
No ID added or closed. Pilot blockers: TD-010/011/012/013/014/017/018/022/023/025/026/
027/028/029/030/031. Production additionally TD-016/019/020. TD-015/024 are later scale.
No inaccessible older workbook formula, custom legacy catalog/import, future
correction/void policy, deployment capacity or live-provider acceptance is claimed.

## Final gates

- Full Stage 0?7 PostgreSQL regression: **1,251 passed, 2 Windows skips**, 3 upstream python-telegram-bot deprecation warnings; 1,032.50 seconds. The final selector hardening and additional corruption/error probes were subsequently verified by the **49-test focused suite**.
- Both skipped real-terminal manager CLI tests: **2 passed** in the Linux API image against a separate temporary database.
- Frontend: **133 passed / 10 files**. Strict TypeScript, ESLint, Ruff (145 files), Ruff format, Prettier and git diff checks passed.
- Development Playwright: **28 passed** (4.6 minutes), including accounting, mobile form/manager flows, accessibility, stale state, and prior integration regressions.
- Native production build passed; Docker API/Web images built; isolated PostgreSQL/API/Web startup healthy.
- Migration validation ran full existing upgrade/populated rollback-refusal/round-trip gates and reported zero drift, one unchanged head `f6e609180002`. No Stage 7 migration.
- OpenAPI and generated TypeScript regeneration are byte-identical; running schema matches the saved contract.
- Source secret scan: 275 Git-visible files, zero findings. Initial final-artifact/static-bundle/container privacy scan: 81 files and two container logs, zero findings. Final scan after acceptance: **87 files and two container logs, zero findings**.
- Production-image Playwright: **28 passed** (3.5 minutes) after recreating the isolated fake API. All accessibility, accounting and prior integration flows passed.

A repeated production browser run must recreate the isolated fake API process: fake OAuth/event-access state lives in memory. Reusing the API between complete suites retained an already-granted scope and invalidated the old test's initial-state assumption. This was corrected through test-environment isolation, not an application authorization change. Tests never used real Google/Telegram providers.

## Retained local evidence

`.local/stage7-backend.log/xml`, `stage7-focused-final.log/xml`,
`stage7-mutations.json` and per-mutation logs, `stage7-frontend-final.log`,
`stage7-development-browser-complete.log`, final production browser log,
`stage7-native-build.log`, Docker build logs, `stage7-migrations.log`,
`stage7-contract-determinism.log`, `stage7-expense-explain.log`, privacy/secret
scan output, and opaque before/after development fingerprints. Browser screenshots
under `apps/web/test-results/{development,production}/accounting-*/` show the
synthetic desktop and 375px mobile accounting view. Screenshots were visually
inspected; they contain synthetic data only.

## Final local rollout and preservation

Verified images now run on normal development API/Web. Health returns
`{"status":"ok","database":"connected"}`; Web login returns HTTP 200; schema drift
remains zero. Google/Telegram modes remain disabled. The existing
`technician-hub_postgres_data` volume is preserved. Before/after opaque fingerprints
match for technicians, managers, calendars, Telegram bindings, WorkReports/revisions
and Expenses/revisions; no record contents were exported. All 16 inventoried legacy
source fingerprints also remain unchanged. Temporary Stage 7 stacks are stopped;
no volumes were deleted. Existing CLI provisioning and normal test services are
left intact.

Committed locally under the requested message `feat: add canonical daily and weekly
accounting`; no push. No new CRITICAL/HIGH issue remains. Existing pilot/production
blockers remain open as listed above; completing Stage 7 is not deployment approval.
