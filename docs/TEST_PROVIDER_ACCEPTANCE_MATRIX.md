# Dedicated TEST provider acceptance matrix

Automated fake-provider evidence proves application rules and failure handling. It does not prove
provider configuration or client behavior. No live Google or Telegram call was made in Stage 10.

| Workflow                  | Fake automated | Dedicated TEST live required | Live completed | Evidence now                                                    | Blocking debt  |
| ------------------------- | -------------- | ---------------------------- | -------------- | --------------------------------------------------------------- | -------------- |
| Telegram onboarding       | Yes            | Yes                          | No             | API, PostgreSQL, fake worker, browser tests                     | TD-022         |
| Telegram group            | Yes            | Yes                          | No             | Actor/membership/permission and migration tests                 | TD-022, TD-023 |
| Schedule delivery         | Yes            | Yes                          | No             | Durable claims, fake send, recovery and ambiguity tests         | TD-028, TD-029 |
| Schedule acknowledgement  | Yes            | Yes                          | No             | Callback generation, late/duplicate acknowledgement tests       | TD-028         |
| Google Calendar discovery | Yes            | Yes                          | No             | Fake OAuth/CalendarList, scope and reconciliation tests         | TD-027         |
| Google event read         | Yes            | Yes                          | No             | Bounded fake event projection, recurrence/DST tests             | TD-027, TD-030 |
| Mobile Work Report        | Yes            | Yes                          | No             | Bearer-purpose, expiry, submission, receipt and browser tests   | TD-030         |
| Mobile Expense            | Yes            | Yes                          | No             | Bearer-purpose, timezone, submission, receipt and browser tests | TD-030         |
| Google Sheets Individual  | Yes            | Yes                          | No             | Deterministic payload, fake writes, retries, reconciliation     | TD-033         |
| Google Sheets All Tech    | Yes            | Yes                          | No             | Deterministic payload, fake writes, collisions and scale probes | TD-033         |

Live evidence must record a date, release commit, sanitized result, dedicated TEST identities, and
reviewer. Never record tokens, authorization codes, refresh credentials, private chat IDs, real
customer data, or screenshots containing them.

Execute the rows in the dependency-safe order in `PILOT_LIVE_ACCEPTANCE_PLAN.md`. Individual and All
Tech mirrors require different dedicated TEST spreadsheets. All `Live completed` values remain `No`
until reviewed evidence from that plan exists.
