# Canonical accounting

`hub.accounting.domain` is the renderer-independent source of daily and weekly financial arithmetic. PostgreSQL latest WorkReportRevision and ExpenseRevision facts are the only inputs. No separate React, Telegram, XLSX or Sheets formula exists.

## Contract

DailyAccounting includes technician identity, configured accounting timezone, setup state, backend Today, calculation instant, business date, previous/next dates, current report/expense facts and AccountingTotals. Report facts preserve job time/title/location/comments, amount, payment, closer, all reviews, maintenance and revision. Expense facts preserve type, amount, note, date, submission timezone and revision.

WeeklyAccounting includes Monday/Sunday, previous/next week, exactly seven DailyAccounting projections and the same aggregation over exactly their facts. CurrentAccounting returns Today plus the containing week from one snapshot, or `setup_required: true` with null Today/daily/weekly when the timezone is absent. Empty populated projections contain truthful zero money/counts and empty rows.

Totals: reported gross, separate expense total, report/expense counts, maintenance count, eight payment amounts (Estimate/Cancel always zero), three review quantities and two closer counts. Gross is the legacy weekly TOTAL; **no subtraction, net, profit or payout**. Every monetary operation uses Decimal; API money is a two-place string. The frontend displays server totals without converting money to JavaScript numbers.

## Reads and consistency

Manager session authentication protects all endpoints. A technician form bearer grants no accounting access. Responses including errors are `Cache-Control: no-store`; no permanent read audit is written. Content is rendered literally and omitted from ordinary logs. No Google/Telegram access occurs.

- `GET /api/technicians/{id}/accounting/daily?date=YYYY-MM-DD`
- `GET /api/technicians/{id}/accounting/weekly?week_start=YYYY-MM-DD`
- `GET /api/technicians/{id}/accounting/current`

Daily/weekly omitted selectors use technician-local Today/current Monday. Explicit week_start must be Monday and allow seven representable dates; invalid dates/UUIDs or additional range/limit parameters are rejected. A missing timezone blocks implicit daily/weekly selection (409), but explicit history returns setup_required and stored facts. Current returns a setup-required projection. Missing technician is 404. Missing current revision or invalid financial facts fail conservatively with a generic 503 rather than choosing history.

Each request opens a fresh session and starts `REPEATABLE READ READ ONLY` before its first data read. Four service statements: isolation setup; technician identity/time; current reports; current expenses. Authentication adds fixed overhead. Current pointers are joined directly through indexed lateral lookups; no history sorting, history sums, row locks or N+1. All details and totals derive from that one MVCC snapshot. Concurrent submissions/corrections are visible on the next refresh. Future callers must supply a fresh session (no prior statement). No migration or new index is necessary at measured Stage 7 sizes; see verification for EXPLAIN evidence and fleet-scale limits.

## Dates

Reports use stored operational_date; expenses use stored expense_date and submission zone. Historical dates never follow profile edits. Today alone uses the current configured accounting timezone and database transaction timestamp, independent of browser/server/Google Calendar timezone. Weeks use date arithmetic, Monday through Sunday, not a 168-hour duration. Date navigation values come from the backend; extreme date edges disable unavailable navigation.

## Web and future renderers

The technician accounting quadrant has Overview / Daily report / Weekly report. Overview displays canonical Today and This Week; Daily exposes underlying facts; Weekly has seven collapsible days and summary. Date input, previous/current/next navigation and manual refresh re-fetch PostgreSQL. The zone is visible. Stale request cancellation and keyed technician/mode components prevent older responses appearing under a new technician/date. Refresh failures hide stale totals until a successful retry.

Future renderers must consume these projections and totals; they may format and paginate, never redefine arithmetic or date grouping. Revision 2 is supported by current-pointer selection without a correction endpoint. Configurable commissions/fees, exports/mirrors, Telegram delivery, corrections, Contracts, GPS and Stage 8 are outside this implementation.
