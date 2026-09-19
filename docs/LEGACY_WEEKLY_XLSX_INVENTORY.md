# Legacy weekly XLSX inventory

The authoritative read-only reference is
`C:\Users\rasha\OneDrive\Documents\ChatGPT\ez_telega_bot`. This inventory was
created before Stage 8 implementation changes. No Google API, spreadsheet, or other
provider was contacted.

## Evidence inspected

| Artifact                                  | Evidence                                                                                       | Classification |
| ----------------------------------------- | ---------------------------------------------------------------------------------------------- | -------------- |
| `accounting/xlsx.py`                      | OpenPyXL renderer, workbook metadata, dimensions, styles, and download bytes                   | PRESERVE       |
| `accounting/layout.py`                    | Technician block geometry, weekday rows, summary positions, and 10-technician bands            | PRESERVE       |
| `accounting/weekly_style.py`              | Central Arial/Calibri styles, blue/yellow fills, borders, currency format, widths, and heights | PRESERVE       |
| `accounting/calculation.py`               | Canonical weekly presentation inputs and deterministic ordering                                | PRESERVE       |
| `accounting/web_views.py` / `web_urls.py` | Authenticated Individual and All Tech download behavior and filenames                          | NORMALIZE      |
| `accounting/tests/test_xlsx.py`           | Workbook reopen, style, literal-text, layout, and download regressions                         | PRESERVE       |
| `docs/LEGACY_WEEKLY_LAYOUT.md`            | Corrected 12-column weekly geometry and scalable band layout                                   | PRESERVE       |
| Tracked workbook/template search          | No `.xlsx`, `.xls`, `.xlsm`, or `.ods` reference workbook exists                               | UNKNOWN        |

There is no exact workbook file that can establish pixel-perfect visual parity.
The current legacy Python renderer and its regression tests are therefore the best
available authoritative visual evidence. Stage 8 preserves their documented roles
and geometry while adapting them to Technician Hub's audited accounting contract.

## Individual technician layout

- One worksheet named `Weekly Report`.
- Technician title at the upper left, approximately 20-point bold Arial.
- `WEEK` and an `MM/DD/YYYY - MM/DD/YYYY` Monday-Sunday range at the upper right.
- A 12-column A:L technician block. The historical A:K copy path was corrected to
  A:L so Facebook reviews no longer displace expense/summary values.
- Seven fixed weekday sections in Monday-Sunday order. Each legacy section has a
  blue weekday row, yellow job-column header row, and at least 15 bordered job rows.
- Job columns are number, address, amount, payment, closer, Groupon, Google,
  Facebook, maintenance, one reserved column, and the expense/summary area.
- Normal job amounts use a neutral bold currency style; payment-dependent fills are
  not used.
- Expenses occupy the right-side area. The reference stores type and amount but has
  no application receipt field. Stage 8 improves this area by also presenting the
  canonical Stage 6 note as wrapped plain text.
- Reviews and payment amounts use canonical precomputed values. `TOTAL` is gross
  WorkReport revenue. Expenses are shown separately and are not subtracted.
- Empty weekdays retain their titled section and empty styled rows.

## Style and geometry

- Legacy blue `#7D98D3`; header yellow `#FFFF00`; white text on blue sections.
- Thin black grid borders; centered/wrapped column headers; vertically centered data.
- Currency number format `$#,##0.00`.
- Column widths: `6, 31, 13, 20, 20, 12, 12, 13, 26, 3, 25, 24`.
- Title, weekday, column-header, and ordinary data row heights are approximately
  `30`, `19.5`, `33.75`, and `18` points. Long text increases row height.
- Landscape printing, narrow margins, fit-to-width, visible grid lines, and 85%
  Individual / 55% All Tech zoom.
- No merged cells are required by the reference renderer.

## All Tech layout and ordering

- One worksheet named `All Tech Weekly Report`.
- The exact same technician-block renderer is placed repeatedly.
- Each technician uses 12 columns plus one spacer column.
- Ten technicians form one horizontal band. Technician 11 starts the next vertical
  band; 21 starts the third. Further bands continue without a fixed maximum.
- The legacy system has configured display order. Technician Hub has no equivalent
  persisted accounting order, so Stage 8 normalizes this to case-folded display name
  followed by UUID as a deterministic tie-breaker.
- Stage 8 includes each active technician that existed by the requested week end,
  even for an empty week, plus inactive technicians that have canonical facts in the
  requested historical week. This preserves operational visibility and retained
  financial history without placing future technicians into older empty exports.

## Safety and historical limitations

- The authoritative renderer writes strings explicitly as OOXML text and numeric/date
  values as typed cells. This prevents `=`, `+`, `-`, and `@` business text from
  becoming formulas.
- Generated files contain no macros, external workbook links, remote images, DDE, or
  automatic hyperlinks.
- The legacy fixed block allowed 15 jobs per day and 34 weekly expenses and rejected
  larger input. Stage 8 must support 100 reports and 100 expenses, so it preserves the
  minimum visual rhythm but improves the block to expand vertically without truncation.
- The reference has no exact workbook artifact and cannot prove rendering differences
  among Excel versions. Exact pixel parity is therefore UNKNOWN and is not claimed.
- Google Sheets mirrors, synchronization, and provider behavior are DEFERRED and are
  outside Stage 8.

## Classification summary

- **PRESERVE:** Monday-Sunday structure, 12-column block, shared Individual/All Tech
  rendering, blue/yellow roles, borders, widths, currency format, neutral job amounts,
  canonical summaries, gross `TOTAL`, and 10-technician bands.
- **IMPROVE:** unbounded report/expense rows, explicit expense notes, complete eight
  canonical payment buckets, activity counts, safe text/control-character handling,
  and coherent all-technician database snapshots.
- **NORMALIZE:** Technician Hub routes, manager-session authorization, safe ASCII
  filenames, deterministic name/UUID order, and in-memory response generation.
- **DEFER:** Google Sheets and any mirror/synchronization worker.
- **UNKNOWN:** pixel-perfect workbook parity and behavior of inaccessible historical
  workbooks outside the tracked legacy tree.
