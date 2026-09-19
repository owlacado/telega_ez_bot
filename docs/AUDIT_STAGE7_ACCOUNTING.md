# Independent Stage 7 accounting integrity audit

Audit branch: `codex/stage7-accounting-quality-audit`
Audited Stage 7 commit: `41b5e2268c79a97e8335d8ab1e9d1b21de20cc9f`
Authoritative read-only legacy tree: `C:\Users\rasha\OneDrive\Documents\ChatGPT\ez_telega_bot`

## Outcome and findings

No Critical or High finding was identified. One Medium product defect was found and
fixed: repeated `date` or `week_start` query parameters were silently resolved to
the last value by FastAPI. Accounting selectors now reject duplicates with a safe
422 response. One Low test-reliability defect was also fixed: a benchmark required
PostgreSQL to choose an index for tiny relations, even though a sequential scan can
legitimately be cheaper. Index selection is now required only for its largest fixture,
and the independent 10,000-row probe requires both current-revision indexes. No
accounting formula, database schema, migration, or index changed.

The audit independently confirmed the Stage 7 calculations, current-revision
selection, stored-date behavior, timezone/week boundaries, repeatable-read snapshot,
exact Decimal transport, manager authorization, privacy controls, and frontend
source of truth. All 20 required deliberate mutations were detected.

## Architecture

- `hub/accounting/router.py` exposes Daily, Weekly, and Current projections. Strict
  query models reject unknown or malformed selectors; the router requires a Monday
  for explicit weekly selection and now rejects duplicate selectors.
- `hub/accounting/service.py` makes `SET TRANSACTION ISOLATION LEVEL REPEATABLE READ
READ ONLY` the first statement of a fresh service session. It reads technician
  context plus PostgreSQL `transaction_timestamp()`, then reads current reports and
  expenses in the same MVCC snapshot.
- Each fact query begins at its canonical parent, filters by technician, and uses a
  lateral lookup on `(parent id, current_revision_number)`. A broken current pointer
  produces an integrity failure instead of disappearing. Date predicates use the
  current revision's stored `operational_date` or `expense_date`.
- `hub/accounting/domain.py` converts rows into frozen facts with strict Decimal
  money. One aggregate function initializes every payment, review, and closer key.
  Daily selects by stored date; Weekly builds exactly seven Daily objects and applies
  the same aggregate to their facts. No derived total is persisted or cached.
- `apps/web/src/components/accounting.tsx` calls only the canonical accounting APIs.
  It displays money strings and server counts/dates without arithmetic. `useResource`
  keys state by URL/version, aborts old requests, and hides stale data on error.

The pre-change map is retained locally as
`.local/stage7-accounting-audit-architecture-map.md`.

## Independent legacy verification

The legacy implementation was reread from source rather than inferred from Stage 7
documentation. The relevant source fingerprints match the inventory recorded in
`LEGACY_ACCOUNTING_INVENTORY.md`.

- `expenses/daily_report.py:40-98` selects current canonical reports and active
  expenses. Daily `closed_total` is `sum(WorkReport.amount_closed)`. Expense total is
  a separate sum. Reviews, closer ownership, jobs, and true maintenance flags are
  counts; none changes money.
- `accounting/calculation.py:179-311` initializes six paid buckets: ZELLE, CHECK,
  CREDIT_CARD, VENMO, SUPER, and CASH. It adds each report amount to exactly one
  bucket, separately adds every expense, and defines `gross_total` as the sum of the
  six paid buckets. There is no SUPER percentage, bonus, subtraction, commission,
  fee, payout, or call-center adjustment.
- ESTIMATE and CANCEL are zero-amount report outcomes in the legacy domain. Their
  rows, reviews, closer, and maintenance facts remain, while the legacy weekly sheet
  leaves their payment display blank. Hub normalizes this to explicit zero buckets.
- Legacy migrations map CASH_APP into CREDIT_CARD. Hub stores only CREDIT_CARD and
  does not expose a second CASH_APP accounting bucket.
- `accounting/layout.py:102-117` writes expenses at L37, reviews at L39-L41, paid
  buckets at L43-L48, and `TOTAL = gross_total` at L49. Expenses are not subtracted.
- `accounting/provider.py:493-499` sends computed values with `valueInputOption=RAW`.
  The XLSX renderer also writes computed values. Searches for SUM/SUMIF/SUMIFS,
  COUNTIF/COUNTIFS, percentages, multipliers, subtractions, review values, and
  call-center adjustments found no formula-only accounting logic. No tracked `.gs`,
  `.xlsx`, `.xlsm`, `.xls`, or `.ods` reference template exists.

This proves the latest available legacy `TOTAL` is reported gross. It does not claim
knowledge of an inaccessible older external workbook. Net, Profit, Payout, Take Home,
Technician Pay, and Margin remain unproven concepts and are absent from the product.

## Golden-vector independence and reconstruction

The golden fixture is static and predates production accounting code. Its SHA-256 is
`fe63e310648391effa3dd582fbc1f771b6ae7c5d2bf4ca9f085fd70a16ed0789`.
The audit adds a test-owned Decimal oracle that reads only literal fixture inputs and
does not call `domain.aggregate`, `build_daily`, `build_weekly`, or the service. It
also pins every input row, including legacy CASH_APP normalization, report/expense
revision 2, identical expenses, and zero expense.

| Day            |  Gross | Expenses | Reports / expenses | Reviews G / Gr / F | Maintenance | Myself / Call center | Nonzero buckets                                   |
| -------------- | -----: | -------: | -----------------: | -----------------: | ----------: | -------------------: | ------------------------------------------------- |
| Mon 2026-09-14 | 193.01 |    85.82 |              2 / 2 |          3 / 1 / 2 |           1 |                1 / 1 | CASH 100.01; CREDIT_CARD 93.00                    |
| Tue 2026-09-15 | 500.05 |     0.00 |              2 / 0 |          1 / 2 / 0 |           1 |                1 / 1 | ZELLE 200.02; CHECK 300.03                        |
| Wed 2026-09-16 |   0.00 |     0.00 |              0 / 0 |          0 / 0 / 0 |           0 |                0 / 0 | none                                              |
| Thu 2026-09-17 | 900.09 |     0.00 |              2 / 0 |          0 / 0 / 3 |           0 |                1 / 1 | VENMO 500.05; SUPER 400.04                        |
| Fri 2026-09-18 |   0.00 |     0.00 |              2 / 0 |          1 / 0 / 1 |           0 |                1 / 1 | ESTIMATE 0.00; CANCEL 0.00                        |
| Sat 2026-09-19 |   0.00 |    40.00 |              0 / 3 |          0 / 0 / 0 |           0 |                0 / 0 | two distinct 20.00 expenses plus one 0.00 expense |
| Sun 2026-09-20 | 200.01 |    25.00 |              3 / 1 |          2 / 0 / 1 |           1 |                2 / 1 | CASH 150.01; CREDIT_CARD 50.00                    |

Monday is reconstructed from CASH 100.01 plus CREDIT_CARD 93.00; expenses 47.23 plus
38.59; two current reports; Google 3, Groupon 1, Facebook 2; one maintenance flag;
and one report per closer. The weekly literal result is gross 1793.16, expenses
150.82, 11 reports, six expenses, three maintenance flags, reviews 7/3/7, closers
6/5, and buckets CASH 250.02, ZELLE 200.02, CHECK 300.03, CREDIT_CARD 143.00,
VENMO 500.05, SUPER 400.04, ESTIMATE 0.00, CANCEL 0.00. Every weekly metric equals
the sum of the seven independently reconstructed days, so compensating day errors
cannot hide behind the final total.

## Financial and revision invariants

- A dedicated correction probe changes revision 1 CASH 100.00 / Google 1 /
  maintenance true / MYSELF / Monday into revision 2 CREDIT_CARD 125.00 / Google 0 /
  Facebook 1 / maintenance false / CALL_CENTER / Tuesday. Monday contributes zero;
  Tuesday contains only the complete revision 2 facts. Expense 40.00 to 25.00 yields
  one expense and 25.00.
- Two distinct identical 20.00 expenses count twice; a 0.00 expense remains one fact.
  Expense-only days work without reports. No fuzzy deduplication exists.
- Every report contributes to exactly one of eight fixed buckets. Gross equals their
  sum. ESTIMATE/CANCEL positive corruption fails closed even when the database guard
  is bypassed in a rolled-back test. Review aggregates may exceed the per-report 100
  limit; 100 plus 100 returns 200.
- Decimal is used in Python, NUMERIC in PostgreSQL, exact strings in JSON, and display
  strings in React. The audit found no `float`, `Number`, `parseFloat`, `toFixed`, or
  `Math.round` in the accounting path. Repeated 0.01 values sum exactly to 0.10,
  1.00, and 100.00.
- Ten thousand individually valid maximum facts aggregate to
  `99999999999900.00`; its cents exceed JavaScript's safe integer. Pydantic accepts
  and serializes the aggregate exactly, and the UI renders it unchanged.
- Domain projections are frozen. No shared mutable result, derived-total table, or
  derived-total column exists.

## Dates, timezones, and weeks

WorkReports use stored `operational_date`; Expenses use stored `expense_date`.
Neither historical date is recomputed from submission time or a changed technician
timezone. Explicit history remains available for inactive technicians and technicians
without an accounting timezone. Implicit Today and Current Week require the current
technician accounting timezone and never fall back to UTC.

At `2026-09-21T06:30Z`, New York is Monday 2026-09-21 while Los Angeles is Sunday
2026-09-20; their week starts are therefore 2026-09-21 and 2026-09-14. The browser
timezone cannot change either result. Monday-only API tests cover all seven weekdays.
Month and year crossing, leap day, spring/fall DST, date minimum/maximum navigation,
and exactly seven ordered Monday-Sunday Daily objects are covered.

## Transaction consistency and write behavior

Tests execute `SHOW transaction_isolation` and `SHOW transaction_read_only` inside
the actual service transaction and observe `repeatable read` and `on`. PostgreSQL
rejects an attempted technician update in that transaction with SQLSTATE `25006`.

Deterministic interleavings commit a new report/expense or a new current revision
after the accounting snapshot starts. The response returns the complete old snapshot;
the next request returns the complete new snapshot. Rows and totals never mix.
Concurrent writer completion is bounded by the test deadline. Accounting SQL has no
`FOR UPDATE`, so it takes no business-row locks that block normal submissions.

## Query architecture, performance, and indexes

Daily, Weekly, and Current use four service statements: isolation setup, technician
context/database clock, current reports, and current expenses. Query count remains
four for 10, 100, 1,000, and 10,000 current records and for one current report plus
one current expense each retaining 1,000 historical revisions.

The expanded synthetic benchmark inserted 10,000 current reports and 10,000 current
expenses, each with one historical revision. Weekly calculation materialized only
the 20,000 current facts, returned exact 100.00 gross and 100.00 expenses, and took
506.24 ms locally. This is evidence of reasonable bounded behavior, not a production
capacity promise or precise peak-memory profile.

EXPLAIN uses `ix_work_reports_technician_id` followed by
`uq_work_report_revision`; the expense path has the corresponding technician and
unique revision indexes. Historical revisions are not fetched into Python. The
parent scan remains linear in lifetime canonical identities under existing TD-015.
No additional index showed an evidence-based benefit, so no migration was added.
The small-cardinality benchmark still records every EXPLAIN plan but no longer
mistakes PostgreSQL's legitimate sequential-scan choice for a product regression.

## API, authorization, and privacy

Daily and Weekly accept strict `YYYY-MM-DD`; Weekly accepts Monday only. Invalid,
empty, timestamp-like, timezone-like, unknown, duplicate, oversized, and
unrepresentable selectors return structured validation errors. Malformed technician
UUID is 422 and unknown UUID is 404. Inactive technician history remains manager
readable; a deleted technician cannot coexist with retained facts because RESTRICT
foreign keys preserve financial history.

Anonymous, logged-out, inactive-manager, and technician bearer/form capabilities
cannot access accounting APIs. Valid managers can. Success, validation, auth, setup,
integrity, and unexpected 500 responses receive `Cache-Control: no-store` and the
application security headers.

Synthetic canaries in report comments, title/location, expense type/note, test
artifacts, API logs, and container logs remain absent. Unexpected errors return a
generic body and a redacted operation/result log. Daily/Weekly GET does not add
durable audit events.

## Frontend verification

Daily, Weekly, and technician detail consume backend projections directly. The UI
does no financial, review, closer, maintenance, date, timezone, or week arithmetic.
It renders all eight buckets distinctly, including intentional 0.00 outcomes; all
three review platforms; a non-monetary maintenance label; and non-monetary closer
counts. Weekly renders exactly seven server-ordered dates from Monday through Sunday.

Unit tests cover exact large-money strings, server Today versus browser timezone,
zero values, empty and detailed facts, text escaping, stale technician/date/week
responses, failure hiding, and retry. Playwright uses a browser timezone different
from the technician timezone and verifies current, Daily, Weekly, previous/current
week navigation, revision replacement, accessibility, desktop, and mobile behavior.
No all-technician accounting dashboard was introduced.

## Mutation evidence

The independent harness detected **20/20** mutations and restored every source file
byte-for-byte:

1. all WorkReport revisions;
2. all Expense revisions;
3. server timezone for Today;
4. browser timezone for Today;
5. Sunday-start week;
6. omitted Sunday;
7. Decimal through float;
8. fuzzy duplicate-expense collapse;
9. nonzero ESTIMATE;
10. merged payment buckets;
11. omitted Facebook;
12. old plus new review revisions;
13. separate drifting Weekly formula;
14. frontend Gross arithmetic;
15. invented frontend Net arithmetic/label;
16. bounded recent-list Current;
17. missing-timezone UTC fallback;
18. removed repeatable read;
19. removed manager authorization; and
20. business-content logging.

Machine-readable evidence is retained at `.local/stage7-audit-mutations.json`.

## Fixes and technical debt

The only product fix rejects duplicate Daily/Weekly selectors. Audit tests and UI
tests were expanded, and the small-fixture planner assertion was corrected; no
business formula changed. No migration or index was added. No new debt ID was
justified and no existing item was closed. TD-015 remains open for deployment-scale
lifetime/fleet capacity despite the 10,000-per-category result; TD-013 remains open
for profile optimistic editing; TD-030/031 and the existing privacy, retention,
backup, credential, and deployment obligations remain unchanged.

XLSX/Google Sheets mirrors were not implemented. Stage 8 was not started.

## Final verification

- Focused accounting suite: 76 passed, including independent oracle, revisions,
  Decimal extremes, invalid selectors, 10,000-per-category scale, both index plans,
  1,000-history retention, read-only enforcement, and timezone boundaries.
- Full backend suite against the final tree: 1,284 passed, two POSIX-TTY cases
  skipped on Windows, and three dependency warnings in 25:15. The two skipped cases
  passed in 5.04 seconds inside Linux with a real pseudo-terminal.
- Frontend unit suite: 136 passed. TypeScript, ESLint, Prettier, Ruff, Ruff format,
  and the native Next.js production build passed.
- Development Playwright: 28/28 passed in 6.6 minutes. Fresh production-image
  Playwright: 28/28 passed in 4.6 minutes. Desktop and mobile accounting screenshots
  were visually inspected for readability, clipping, and overflow.
- Fresh API and web Docker images built successfully. The isolated production stack
  became healthy; `/login` and `/api/health` returned HTTP 200 and the latter reported
  a connected database. Temporary audit stacks were stopped without `-v`.
- Alembic fresh, historical, populated, downgrade/refusal, and round-trip checks
  passed with zero drift. The unchanged single head is `f6e609180002`.
- OpenAPI generation and TypeScript contract generation were byte-identical to the
  tracked artifacts; `docker compose config --quiet` passed.
- Mutation score: 20/20. Secret scan: 277 Git-visible text files, zero findings.
  Privacy scan: 95 generated artifacts and two production container logs, zero
  findings.
- The normal development stack remained healthy. Before/after opaque fingerprints
  prove existing technician, manager, work-report, calendar, binding, expense, and
  revision rows were unchanged. The `technician-hub_postgres_data` volume remains.
- No live Telegram, Google, calendar, spreadsheet, or other provider was contacted;
  no real business record was used. The authoritative legacy tree was read only.
