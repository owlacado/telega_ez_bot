# Stage 8 weekly XLSX verification

Stage 8 began from audited Stage 7 commit
`8d24ab6b43fa94aa20e93574cba2ea63e24b9ced` on
`codex/stage8-weekly-xlsx`. The normal retained PostgreSQL volume and manager account
were fingerprinted before destructive testing; all destructive cases use the guarded
`technician_hub_test` database.

## Implemented contract

- Individual and All Tech manager downloads use an explicit Monday and canonical
  `WeeklyAccounting` projections.
- One frozen presentation model and one shared technician-block renderer serve both
  workbooks.
- All Tech uses one repeatable-read snapshot and four database statements at 30
  technicians; it includes active technicians that existed by week end and inactive
  technicians with week facts.
- Seven days, eight payment buckets, three review platforms, both closer counts,
  maintenance, expenses, and gross `TOTAL` are written as supplied values.
- Expense totals remain separate. No Net/Profit/Payout metric or XLSX accounting
  formula was introduced.

## Workbook validation

Automated reopen and ZIP/XML inspection verifies:

- correct fixed worksheet names and safe attachment filenames;
- representative values, fills, fonts, borders, alignments, dimensions, row heights,
  and `$#,##0.00` number formats;
- Individual and first All Tech block semantic/style equivalence;
- exact Decimal round trips through the largest audited weekly aggregate;
- literal hostile `=`, `+`, `-`, and `@` text for technician, job, location, expense
  type, and expense note;
- removal of XML-invalid controls while Unicode, Cyrillic, emoji, punctuation, and
  line breaks remain;
- no formulas, hyperlinks, external links, macros, remote relationships, or binary
  VBA payload;
- no truncation at 100 reports, 100 expenses, or 30 technicians;
- no collision between expanded blocks and later vertical bands.

## Security and privacy

Anonymous, technician-capability, expired/logged-out, and inactive-manager access is
rejected by the manager-session middleware. Historical inactive-technician facts
remain manager-readable. Validation, authentication, integrity, generation failure,
and success responses retain no-store/security headers. Sanitized unexpected-error
bodies and logs never include workbook text, addresses, notes, or filesystem paths.
Downloads do not create durable business audit events or persistent export files.

## Performance evidence

The focused benchmark recorded:

| Workbook                              |  Generation |         Size | Peak traced Python allocation |
| ------------------------------------- | ----------: | -----------: | ----------------------------: |
| Individual ordinary                   |   222.23 ms |  9,735 bytes |                 850,502 bytes |
| Individual 100 reports / 100 expenses |   435.53 ms | 16,430 bytes |               1,301,824 bytes |
| All Tech 10                           | 1,932.25 ms | 35,544 bytes |                   not sampled |
| All Tech 11                           | 2,303.46 ms | 40,272 bytes |                   not sampled |
| All Tech 20                           | 3,857.61 ms | 64,726 bytes |                   not sampled |
| All Tech 21                           | 4,337.01 ms | 68,954 bytes |                   not sampled |
| All Tech 30                           | 6,055.68 ms | 93,819 bytes |              13,482,984 bytes |

These are single local development observations rather than production capacity
promises. The focused suite completed 35 tests in 64.00 seconds; its eight warnings
only report pytest's xUnit2 `record_property` compatibility while the properties are
still present in the retained local XML evidence.

## Mutation evidence

The isolated mutation harness detected 16/16 required failures: renderer row summing,
expense subtraction, old report revision, old expense revision, missing Facebook,
merged Zelle/Venmo, `=` formula injection, `+` formula injection, unsafe filename,
Individual/All Tech style divergence, omitted Sunday, duplicate-expense truncation,
local/browser week selection, removed manager authorization, a ten-technician cap,
and business-content logging. Every source hash was restored. Machine-readable local
evidence is retained at `.local/stage8-mutations.json`.

## Required gates

Final results are recorded after completion of backend, frontend, Playwright
development/production-image, native build, Docker, contract, Alembic, schema-drift,
mutation, privacy, secret, formatting, and preservation checks.

## Final quality-gate results

- Full PostgreSQL backend: **1,319 passed, 2 Windows platform skips, 3 upstream
  deprecation warnings** in 989.98 seconds. The skipped real-TTY parameter cases then
  passed **2/2** inside the Linux API image.
- Stage 8 focused XLSX suite: **35 passed** in 64.00 seconds. This includes canonical
  parity, latest-only revisions, formula injection, exact money, 100/100 rows,
  1/10/11/20/21/30-technician geometry, authorization, query count, snapshot
  concurrency, response safety, and log privacy.
- Stage 7 accounting regression: **76 passed** unchanged.
- Frontend unit/component suite: **142 passed** across 10 files; strict TypeScript,
  ESLint, and the native Next production build passed.
- Playwright development stack: **28/28 passed** in 5.0 minutes.
- Playwright production images: **28/28 passed** in 3.7 minutes with isolated fake
  Google/Telegram modes and matching disposable encryption keys. Both downloaded XLSX
  files reopened with the expected names/totals and zero formulas/external links.
- Ruff lint and formatting passed across 150 Python files. `git diff --check` passed.
- OpenAPI generation was byte-identical on its second run and the generated-contract
  check passed.
- Alembic fresh upgrade, populated upgrade, historical upgrade, refusal, downgrade /
  upgrade round trip, and schema-drift checks passed at head `f6e609180002`.
- Fresh no-cache API and web Docker image builds, Compose configuration, disposable
  isolated startup, and health checks passed. The disposable stack was removed without
  `-v`.
- The Git-visible secret scan checked **284 files with zero findings**. The final
  runtime privacy scan checked **26 artifacts, 2 XLSX ZIP payloads, and 2 container
  logs with zero findings**.
- Normal retained data matched every pre-test opaque fingerprint. The manager row,
  three calendars, normal API/web health, and `technician-hub_postgres_data` volume
  remain intact.
- The final self-audit found **0 CRITICAL and 0 HIGH** product findings. The production
  harness initially exposed missing fake-provider/key alignment; the corrected
  disposable configuration then passed the complete suite and did not require a
  product-code change.
