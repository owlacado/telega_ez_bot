# Weekly accounting XLSX exports

## Source of truth

Weekly XLSX files are presentation artifacts over the audited PostgreSQL accounting
projection:

`PostgreSQL current revisions → WeeklyAccounting → WeeklyAccountingXlsxModel → XLSX`

`WeeklyAccountingXlsxModel` is frozen, contains no ORM objects, and copies already
calculated daily facts and weekly totals. The renderer has no database dependency and
does not sum reports, expenses, reviews, payments, closer activity, or maintenance.
It writes the supplied canonical totals as static cell values. There are no Excel
business formulas.

## Downloads

- Individual: `GET /api/technicians/{technician_id}/accounting/weekly.xlsx?week_start=YYYY-MM-DD`
- All Tech: `GET /api/accounting/weekly/all.xlsx?week_start=YYYY-MM-DD`

Both require a valid manager session and an explicit Monday. Responses are generated
in memory, use the official XLSX MIME type, carry `Cache-Control: no-store`, and have
ASCII-only attachment filenames. No export is persisted or cached.

The Weekly Accounting UI sends the exact `week_start` returned by the backend. The
browser timezone and locale do not select or alter the exported week. Download errors
remain visible and safe; both buttons are disabled while a request is active.

## Individual layout

An Individual workbook contains one `Weekly Report` worksheet and one technician
block starting at A1. The title includes the technician, accounting timezone, `WEEK`,
and the Monday-Sunday date range.

The block retains the authoritative 12-column weekly structure:

| Columns     | Content                                                                                                                  |
| ----------- | ------------------------------------------------------------------------------------------------------------------------ |
| A:I         | Seven Monday-Sunday job sections: sequence, title/location, amount, payment, closer, three review platforms, maintenance |
| J:L         | Expense note, type, and amount                                                                                           |
| K:L summary | Expenses, reviews, eight payment buckets, report/expense/maintenance/closer counts, gross `TOTAL`, date range            |

Every day has a blue day header, yellow column header, and at least 15 job rows, even
when empty. More rows expand the day rather than truncating it. Expense summary rows
move below an expanded expense list. Normal job amounts retain neutral styling.

`TOTAL` is audited gross WorkReport revenue. Expenses are displayed separately and
are never subtracted. No Net, Profit, Payout, Margin, Take Home, or Technician Pay
concept exists in the workbook.

## All Tech layout

All Tech uses one `All Tech Weekly Report` worksheet and the exact same technician
block renderer. Each block uses 12 columns followed by one spacer. Ten technicians
form a horizontal band; the 11th and 21st start new vertical bands. Band height is
the maximum rendered block height in that band, so long text or 100-row blocks cannot
overlap the next band. There is no ten-technician cap.

The export includes:

- active technicians that existed by the requested week end, including an empty week;
- inactive technicians when current canonical reports or expenses exist in the week.

Inactive empty technicians and active technicians created after the historical week
are excluded. Ordering is display-name `casefold()` followed by UUID, which remains
stable even for duplicate names.

Technician names are current profile values because Technician Hub does not store a
historical display-name snapshot. An inactive technician with week facts therefore
appears under the current name. A technician now inactive with no facts is excluded
even if they may have been active during that historical week; status history is not
available to infer otherwise.

The All Tech service uses four statements regardless of technician count: read-only
repeatable-read setup, technician context plus the database clock, all current report
revisions, and all current expense revisions. Every technician's canonical
`WeeklyAccounting` is built within that one MVCC snapshot.

## Safety

All strings pass through one spreadsheet-safe writer. It removes XML-invalid control
characters, lone UTF-16 surrogates, and U+FFFE/U+FFFF; preserves legitimate Unicode,
combining characters, RTL text, zero-width characters, punctuation, emoji, tabs, and
line breaks; and forces the OOXML string data type. Text beginning with `=`, `+`, `-`,
or `@` therefore remains literal after workbook reload. Arbitrary URLs, file/UNC
paths, and mail or script-like URI text are not converted to hyperlinks.

Worksheet names are fixed safe product names. Filename components are Unicode-
normalized to bounded ASCII letters, numbers, underscores, and hyphens. Slashes,
path traversal, quotes, CR/LF, and header metacharacters cannot enter
`Content-Disposition`.

Generated `.xlsx` files contain no formulas, macros, external workbook links, remote
images, DDE, or external relationships. Workbook creation failures are completed
before the HTTP success response is built, so partial corrupt content is not returned
as a successful download. Operational logs contain only export type, technician UUID
where applicable, week, technician count, duration, byte size, and outcome.

## Exact money and long text

Canonical `Decimal` values are written directly as numeric XLSX cells with
`$#,##0.00`. Round-trip tests cover `0.01`, `1.10`, `193.01`, `1793.16`,
`9999999999.99`, and `99999999999900.00`. The 24-character amount column displays
large totals without a narrow-column `######` condition.

Job title/location and expense type/note cells wrap. Row height grows to a bounded
readable height, while the full text remains in the cell. A 100-report/100-expense
workbook reopens with every row present and with canonical totals unchanged.

The row-height estimate is deliberately capped at 180 points. It prevents one
maliciously long value from creating pathological geometry, but a 4,000-character
note is not fully visible in the initial Excel view even though the complete value is
retained. This later-scale presentation limitation is tracked as TD-032.

## Current limitations and future renderer contract

No exact legacy workbook file exists in the authoritative tree, so pixel-perfect
parity with an external historical workbook is not claimed. The current legacy
Python renderer, style tokens, layout documentation, and regression tests are the
available visual authority. Excel-version-specific print rendering remains outside
automated OpenPyXL validation.

Google Sheets is not implemented in Stage 8. A future Google renderer must consume
the same frozen `WeeklyAccountingXlsxModel` or an equivalently presentation-only
model, write raw precomputed canonical values, preserve literal-text protection, and
must not become another accounting engine.

## Local scalability observations

| Workbook                              |  Generation |         Size | Peak traced Python allocation |
| ------------------------------------- | ----------: | -----------: | ----------------------------: |
| Individual ordinary week              |   222.23 ms |  9,735 bytes |                 850,502 bytes |
| Individual 100 reports / 100 expenses |   435.53 ms | 16,430 bytes |               1,301,824 bytes |
| All Tech 10 technicians               | 1,932.25 ms | 35,544 bytes |                   not sampled |
| All Tech 20 technicians               | 3,857.61 ms | 64,726 bytes |                   not sampled |
| All Tech 30 technicians               | 6,055.68 ms | 93,819 bytes |              13,482,984 bytes |

The same layout tests cover 1, 10, 11, 20, 21, and 30 technicians. Timings are
single local development observations and deliberately are not hard production gates.
