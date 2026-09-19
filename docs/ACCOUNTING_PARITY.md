# Accounting parity

Authority: read-only `C:\Users\rasha\OneDrive\Documents\ChatGPT\ez_telega_bot`.
See [36-rule source inventory](LEGACY_ACCOUNTING_INVENTORY.md) for source locations and hashes.
No provider calls or production business data were used.

## Proven arithmetic

- Daily **Closed total**, weekly **TOTAL**, and Hub **Reported gross** mean the sum of current report amounts / paid payment buckets. Expenses are separate, not subtracted.
- CASH, ZELLE, CHECK, CREDIT_CARD, VENMO, SUPER are separate amount buckets. CASH_APP was normalized to CREDIT_CARD by legacy migrations and already by Hub input. Hub accounting accepts only the audited stored codes; future legacy imports must apply this mapping explicitly.
- ESTIMATE/CANCEL retain zero amounts, report rows, reviews, closer and maintenance facts. The legacy weekly blank payment display is normalized to a visible outcome label. No new estimate/cancel count metric.
- Google, Groupon and Facebook quantities are additive. Closer counts and maintenance-true counts come from the legacy Daily report. Neither changes money.
- Expense total adds every distinct current expense, including identical entries and zeros. Legacy ACTIVE filtering corresponds to all Hub canonical expenses because void/correction APIs are out of scope.
- No percentage, fee, review monetary value, commission, SUPER adjustment, Net, Profit or Payout is established by the latest implementation. These remain UNKNOWN / NEEDS PRODUCT CONFIRMATION if requested; none is implemented. No financial configuration table is justified.
- Latest generated sheet values are computed in Python: L37 expenses, L39–L41 reviews, L43–L48 paid buckets, L49 gross. No live-cell formula dependency. No reference workbook or Apps Script exists in the inspected tree. Unavailable older external workbook behavior is not claimed verified.

## Golden vectors prepared before implementation

`apps/api/tests/fixtures/accounting_legacy_week.json` records synthetic inputs and expected daily/weekly totals. The authoritative `_build_technician` helper was executed in isolation from its parsed source with synthetic objects, without Django/database/provider initialization. Its gross, expense and review outputs independently matched the fixture. Additive daily/closer expectations follow `expenses/daily_report.py`. The local reproduction script is retained in `.local/stage7_generate_golden.py`.

Monday 2026-09-14: CASH 100.01 + CREDIT_CARD 93.00 = **193.01**; expenses 47.23 + 38.59 = **85.82**; reviews Google 3 / Groupon 1 / Facebook 2; two reports, one maintenance, one of each closer.

Full Monday–Sunday week: gross **1793.16**, expenses **150.82**, 11 reports, six expenses, three maintenance flags, reviews **7 / 3 / 7**, closers **6 Myself / 5 Call center**. Buckets: CASH 250.02, ZELLE 200.02, CHECK 300.03, CREDIT_CARD 143.00, VENMO 500.05, SUPER 400.04, ESTIMATE/CANCEL 0.00. Wednesday empty; Friday only Estimate/Cancel; Saturday expenses only including two identical 20.00 entries and a zero; Sunday includes Cash App alias and selected revision 2. Previous report 100.00 → current 150.00 and expense 40.00 → 25.00 are not summed together.

Each of the seven daily totals is asserted independently against persisted fixture expectations; weekly metrics equal the seven daily metrics. Other tests cover empty week/report-only/expense-only, repeated cents, large legal inputs, timezone boundaries, year/month/leap/DST, current profile changes, corruption, authorization and concurrent writes.

## Intentional architectural / date differences

**Date parity is intentionally normalized, not identical.** Legacy groups WorkReports by current technician-zone submission timestamp. Stage 7 explicitly prefers Hub's stored job operational_date. Hub keeps that durable date even when submission is the next day or the technician timezone changes. The golden week aligns those dates for arithmetic comparison; a separate regression submits the following day and proves stored operational_date wins. Expense snapshot dates and zones never move.

Weekly Monday–Sunday arithmetic is unchanged. Explicit weekly selectors must be Monday (legacy normalized arbitrary selectors). Default Today/This Week use database time in the configured technician accounting zone. Missing zone returns setup required; explicit historical dates remain readable, including inactive technicians.

Legacy mutable canonical parent values become current immutable revision FK projections. The calculation reads those revisions once in a read-only repeatable-read snapshot and exposes exact decimal strings. No cached/persisted derived totals, financial rates, daily read audit rows or external dependencies. Renderer capacity limits (15 reports/day, 34 expenses/week), spreadsheet styling and provider float conversion are removed from the domain. No All-Tech overview is added because the current dashboard has no canonical financial summary needing it; no per-technician dashboard query loop was introduced.

This establishes arithmetic parity for the audited fixed Hub categories and explicit date normalization. It does not claim acceptance of inaccessible historical workbook formulas, custom legacy catalog extensions, future imports, void/correction product semantics, or future renderer/export formatting.
