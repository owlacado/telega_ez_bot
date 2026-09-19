# Independent Stage 8 weekly XLSX security, parity, and reliability audit

Baseline: `1962a6f497f9ec247af7758378edddb431b5da3d` on
`codex/stage8-weekly-xlsx`. Audit branch:
`codex/stage8-weekly-xlsx-quality-audit`. The normal retained database was
fingerprinted before destructive work; every mutation, concurrency, authorization,
and browser setup uses `technician_hub_test` only.

## Outcome and findings

No CRITICAL or HIGH finding was identified.

### MED-01 — XML-prohibited Unicode could create an unreadable workbook — fixed

The central text normalizer removed C0/DEL controls but did not remove lone UTF-16
surrogates or U+FFFE/U+FFFF. An independent red probe showed that OpenPyXL saved a
worksheet containing those values, but `load_workbook` then failed with an XML parse
error. U+FFFE/U+FFFF can be represented as ordinary Python/PostgreSQL Unicode and can
therefore reach canonical text even though lone surrogates normally fail a UTF-8
storage boundary.

The localized fix extends the one safe-text regular expression to remove those
XML-prohibited values. The audit regression exercises all prohibited C0 characters,
DEL, both surrogate endpoints, U+FFFE, and U+FFFF across technician, job, location,
Expense type, and Expense note surfaces. Cyrillic, emoji, accents, combining marks,
RTL text, zero-width characters, tabs, newlines, and punctuation still round-trip.

### LOW-01 — Maximum long-text display is approximate — tracked as TD-032

The full 2,000-character location and 4,000-character Expense note remain in their
cells, wrap, reopen, and do not overlap later days or technician bands. Row height is
capped at 180 points to prevent pathological geometry. Excel cannot display all 4,000
characters at once within that row, and OpenPyXL cannot request AutoFit. TD-032 records
the later-scale presentation-policy decision; no canonical data is truncated.

## Architecture and source of truth

The independent pre-edit map is retained locally at
`.local/stage8-audit-architecture-map.md`.

- `hub.accounting.service.calculate` and `calculate_all_weekly` are the only database
  boundary and return canonical `WeeklyAccounting`.
- `WeeklyAccountingXlsxModel.from_accounting` copies domain facts and precomputed
  totals into frozen presentation dataclasses with no ORM object.
- `hub.accounting.xlsx` imports no SQLAlchemy, WorkReport, Expense, or repository code.
  It contains no financial aggregation or float arithmetic.
- Individual and All Tech both invoke the same title, block, cell writer, expense,
  summary, and style helpers. All Tech only changes block origins.
- Rendering executes zero database statements after presentation-model construction.
- Both endpoints finish an in-memory `BytesIO` workbook before creating the successful
  response. No export or temporary file is persisted.
- The frontend calls the authenticated server endpoint with the exact backend-selected
  Monday. It contains no workbook library or financial arithmetic.
- Production uses the project-managed `openpyxl==3.1.5` pin in both `pyproject.toml`
  and `requirements.lock`; the endpoint does not depend on an audit-only package.

## Independent legacy visual recheck

The read-only authority was
`C:\Users\rasha\OneDrive\Documents\ChatGPT\ez_telega_bot`. The audit independently
inspected `accounting/xlsx.py`, `layout.py`, `weekly_style.py`, `calculation.py`,
`web_views.py`, `web_urls.py`, `accounting/tests/test_xlsx.py`, and
`docs/LEGACY_WEEKLY_LAYOUT.md`, plus repository-wide workbook/template/fixture searches.

No tracked `.xlsx`, `.xls`, `.xlsm`, or `.ods` weekly reference exists. The maintained
Python renderer, centralized style definitions, tests, and layout document remain the
best visual authority. They confirm one A:L block, seven Monday-Sunday sections, blue
and yellow header roles, neutral job amount cells, expenses/summaries at the right,
shared Individual/All Tech geometry, and ten technicians per horizontal band. This
audit does not claim pixel-perfect parity with an unavailable workbook.

## Canonical value and style parity

An independent golden week contains all eight payment buckets, all three review
platforms with totals greater than 100, both closer values, maintenance, and two
Expenses. Individual and All Tech cells match canonical gross, expense total, report
count, Expense count, payment totals, review totals, closer counts, and maintenance
exactly. `TOTAL` remains supplied gross. Expenses remain separate. No Net, Profit,
Payout, Margin, Take Home, or Technician Pay label exists.

Representative titles, week metadata, weekday headers, column headers, job cells,
amounts, Expenses, Reviews, payments, TOTAL, fonts, fills, borders, alignments, wrapping,
number formats, column widths, and equivalent row heights match between Individual and
block one of All Tech. No alternate renderer or duplicate style set was found.

Latest-revision database tests retain WorkReport revision 2 (150 ZELLE) and Expense
revision 2 (25), with no revision-1 values. Two identical legitimate Expenses remain
two rows. Empty, Expense-only, and Estimate/Cancel-only weeks retain seven sections and
canonical zero/gross semantics.

## Spreadsheet security

The audit places formula/DDE/CSV-style payloads in every external text surface,
including `HYPERLINK`, `WEBSERVICE`, `IMPORTXML`, `CMD`, ordinary formulas, and `=`,
`+`, `-`, and `@` prefixes. It also tests HTTP/HTTPS, file, JavaScript, mail, UNC, and
Windows paths. Every value reloads as `data_type == "s"`; no cell has a hyperlink.

ZIP/XML inspection finds no formula cells, external link directory, external
relationship, remote image, OLE object, DDE reference, binary payload, VBA project,
macro relationship, or XLSM content type. Worksheet names are fixed `.xlsx` names.
The archive contains no drive letter, local path, temporary path, or machine identity.

Filename probes cover traversal, both slash types, quotes, CR/LF, semicolon, emoji,
Cyrillic-only names, and 1,000-character names. The header receives a bounded ASCII
component only. Non-ASCII-only names intentionally fall back to `technician`; raw user
text never enters `Content-Disposition`.

Workbook properties use neutral `Technician Hub` metadata and a deterministic week
timestamp. No username, host, repository path, database URL, or credential appears.
There are no hidden sheets, rows, columns, or merged ranges.

## Exact money and geometry

Numeric reload tests cover 0.00, 0.01, 0.10, 1.10, 193.01, 1793.16,
9999999999.99, 99999999999900.00, and a deliberately corrupted negative
presentation value. The renderer preserves each value, does not take an absolute
value, and applies `$#,##0.00`. Production code contains no `float`, JavaScript
`Number`, `parseFloat`, `toFixed`, or `Math.round` conversion. The 24-character money
column is sufficient for the supported audited range.

Independent layout probes pass at 1/10/11/20/21/30/31/50 technicians. An optional
100-technician workbook also reopens with every unique block. A mixed stress workbook
with 500 reports on one day, 500 Expenses, a 2,000-character location, and a
4,000-character note retains every row and places Tuesday and the summary after their
calculated boundaries. Fifty-technician workbooks have plausible 129-column and
612-row bounds with no unused thousands of styled rows or columns.

## Technician inclusion, order, and names

All Tech includes currently active technicians created by the requested week end,
including empty weeks, and inactive technicians with canonical facts in that week.
It excludes inactive empty technicians and currently active technicians created after
the week end. Current status is authoritative because no status-history projection is
stored; a technician currently inactive with no week facts cannot be inferred as active
in an older week. Current profile display names are used because no historical name
snapshot exists.

Ordering is Python `display_name.casefold()` followed by UUID. `Alice` and `alice`
therefore tie under the name key and use UUID; `Álice` remains a separate accented key.
No database collation controls the result. Mixed New York, Chicago, Denver, Los Angeles,
and Phoenix technicians retain the same requested Monday-Sunday business dates supplied
by canonical `WeeklyAccounting`; the renderer performs no timezone conversion.

## Transactions, concurrency, and queries

All Tech begins with `SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY`.
One deterministic two-technician test commits concurrent WorkReport and Expense rows
while the fleet snapshot is open. Both writers finish within five seconds, the first
workbook contains the coherent old totals for both technicians, and a later transaction
contains both new totals. No `FOR UPDATE` or writer lock exists.

All Tech uses four SQL statements at 1, 10, 30, and 50 technicians. There is no
per-technician query loop. Individual calculation completes its canonical snapshot
before model conversion; rendering performs zero database statements.

A cancelled HTTP response can stop awaiting the threadpool result, while the bounded
in-memory OpenPyXL function may finish in its worker thread. It holds no database
session, external connection, temporary file, or persistent export. Repeated large
manager requests remain part of the existing TD-015/TD-017 deployment capacity and
admission obligations.

## Authorization, privacy, and provider independence

Independent tests cover both routes for anonymous, technician-style bearer, expired
manager, inactive manager, and valid manager access. Only the valid manager succeeds.
Historical Individual XLSX remains available after technician deactivation when the
week contains facts. Success and failure responses remain `no-store`; successful MIME
is `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`. Forced renderer
failure returns a sanitized non-200 response and no partial workbook.

The renderer does not call Google, Telegram, Calendar, Sheets, or any network provider.
The global test guards reject live Google/Telegram operations. No public/static export,
media artifact, database audit mutation, or temporary workbook is created. Operational
logs contain only identifiers and aggregate operational metadata.

## Frontend and browser evidence

Frontend tests verify exact selected-week URLs, loading/double-click behavior, safe
errors, invalid/empty response rejection, and navigation from technician A to B while
A's request is pending. The completed A download remains bound to A; the next control
uses B's UUID and current selected week.

The strengthened Playwright flow downloads and parses a historical Individual workbook,
then current Individual and All Tech workbooks. It checks filename, sheet, technician,
week range, gross, expenses, CASH, Google reviews, TOTAL, representative styles, zero
formulas/hyperlinks/external links, and three separately ordered technician blocks.

## Performance and memory observations

These are local observations, not production capacity promises:

| Workbook                              |   Generation |          Size | Peak traced allocation |
| ------------------------------------- | -----------: | ------------: | ---------------------: |
| Individual ordinary                   |    104.68 ms |   9,718 bytes |            not sampled |
| Individual 100 reports / 100 Expenses |    181.26 ms |  15,611 bytes |            not sampled |
| All Tech 10                           |    848.96 ms |  35,143 bytes |            not sampled |
| All Tech 20                           |  1,784.13 ms |  63,875 bytes |            not sampled |
| All Tech 30                           |  2,547.53 ms |  92,515 bytes |       13,446,711 bytes |
| All Tech 31                           |  2,671.90 ms |  97,066 bytes |            not sampled |
| All Tech 50                           |  4,191.32 ms | 149,947 bytes |       22,873,735 bytes |
| All Tech 100 under tracing            | 34,120.88 ms | 296,354 bytes |       45,929,115 bytes |

Thirty-to-fifty-to-one-hundred memory and file-size growth is approximately linear.
The 100-tech timing includes `tracemalloc` overhead and should not be compared directly
with the untraced 50-tech time. The in-memory design remains acceptable for audited
local sizes but does not close TD-015.

## Mutation evidence

The audit mutation harness detected 21/21 deliberate faults and restored every source
hash: row-based gross recomputation, expense subtraction, old WorkReport revision, old
Expense revision, missing Facebook, merged Zelle/Venmo, `=` formula, `+` formula,
unsafe filename, style divergence, missing Sunday, duplicate-Expense truncation,
browser/local week, removed manager authorization, 10-tech cap, business-content log,
automatic hyperlink, 30-tech cap, broken repeatable-read isolation, renderer database
coupling, and hidden Excel business formula. Machine-readable evidence is retained at
`.local/stage8-audit-mutations.json`.

## Fixes and debt

Production changes are limited to the XML-prohibited Unicode sanitizer. Audit tests,
stronger frontend/browser inspection, documentation, and TD-032 accompany it. Stage 7
accounting arithmetic and snapshot semantics are unchanged. No existing debt closes;
pilot blockers remain unchanged and production still adds TD-016/019/020.

## Final quality gates

- Full PostgreSQL backend: 1,371 passed, 2 Windows TTY skips, 3 dependency warnings;
  the two skipped real-TTY parameter cases passed in the fresh Linux API image.
- Focused original plus independent XLSX suites: 87 passed. The independent mutation
  harness detected 21/21 changes.
- Frontend: 143 tests passed; strict TypeScript, ESLint, and the native Next production
  build passed. Focused accounting tests passed 22/22.
- Playwright: 28/28 passed against development servers and 28/28 passed against the
  fresh production images. Each run parsed the Individual historical/current and All
  Tech downloads rather than accepting HTTP status alone.
- Ruff passed and reported all 151 Python files formatted. Prettier passed for every
  changed frontend and documentation file. `git diff --check` passed.
- OpenAPI matched the running application schema. Re-exporting OpenAPI and regenerating
  TypeScript contracts twice retained identical SHA-256 hashes.
- Alembic validation passed at sole head `f6e609180002`: fresh and populated paths,
  preservation, downgrade refusals, round trips, and zero schema drift.
- Docker Compose configuration passed. Fresh no-cache API and web builds passed; the
  fresh services returned HTTP 200, and the isolated production stack became healthy.
- Secret scanning covered 286 Git-visible files with zero findings. Privacy scanning
  covered 29 artifacts, three XLSX downloads, and two production-container logs with
  zero findings.
- The normal database remained on `technician-hub_postgres_data`; manager, technician,
  calendar, report, revision, binding, and Expense fingerprints matched the pre-audit
  baseline exactly after all gates.
