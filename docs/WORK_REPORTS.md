# Work Reports — Stage 5

> Approved pilot update: successful submissions now enqueue Work Group activity on the existing
> Telegram outbox. Browser receipt still confirms persistence independently of delivery. The stage
> text below records the earlier boundary; its no-Telegram-notification statements are superseded.
> See WORKFLOW_PARITY_AUDIT.md and PILOT_LIVE_ACCEPTANCE_PLAN.md for current delivery/recovery rules.
> Corrections remain deferred; Calendar report write-back is intentionally not restored.

The private Telegram `/report` command (also recognizes `Submit Report`) issues a
short-lived mobile form. PostgreSQL is canonical. No Google Form, Sheets mapping,
Discord, Calendar write, accounting formula, expense, contract or GPS is involved.
See [legacy evidence](LEGACY_WORK_REPORT_INVENTORY.md).

## Trust and lifecycle

The worker's verified provider update identifies the actor: private chat ID must
equal user ID, non-bot/non-anonymous actor, active technician, connected and
available private binding for the verified bot. It calls the shared domain service;
there is no public issue/update-injection endpoint. Group entry is deferred.
Unknown actors get the existing safe connection-link response. The home/status/help
text advertises `/report — Submit Report`; existing callback namespaces are unchanged.

`TechnicianFormSession` stores a SHA-256 hash of a random 32-byte URL-safe capability,
purpose WORK_REPORT, technician UUID, issuing Telegram user/bot and private binding
generation, timestamps, status, bounded job choices and selected snapshot. Default
TTL is 900 seconds; `WORK_REPORT_SESSION_SECONDS` permits 600–900 on API and worker.
At most five open forms per technician are retained on new issuance; older ones
are revoked. Two legitimate forms can coexist and race without duplicate reports.

The raw credential is returned only to the private command response. The link uses
`/technician/work-report#<capability>`: fragment, not path/query. The browser sends
it in Authorization, never in business fields. No localStorage, analytics, external
assets or token-list API is added. The fragment supports refresh; users must treat
the link like a password. This is a **bearer capability strategy**, not a Telegram
Mini App initData implementation: it cannot independently identify the person who
receives a deliberately shared/stolen valid link. Issuance is actor-verified; browser
identity is the credential. Do not claim Telegram identity proof on every browser
request. Generation changes/disconnect/inactivation reject old credentials.
HTTPS, trusted origins and credential handling acceptance remain pilot gates.

Only three exact form POST paths bypass manager-cookie authentication; each enforces
capability authorization, trusted Origin, X-Hub-Request, a 32 KiB streamed body limit
and strict business fields. Duplicate JSON keys are rejected. Manager cookies cannot
submit alone; form credentials cannot read manager lists. All API responses are
no-store/no-referrer. Logs/audits exclude credential/hash, payload, notes/address and
provider content. Audit actor_kind is TECHNICIAN; actor_id remains null because the
existing column references managers. Target session/report resolves technician UUID.

## Jobs and snapshot policy

Opening a new picker invokes the **same Stage 3 read_schedule** service, filters,
scope/availability checks, recurrence projection, 08:00–22:00 window, numbering and
calendar wall-clock semantics. There is no second filter. No valid jobs displays
“No scheduled jobs found for today.” Browser choices are opaque random UUIDs; no
raw Google identity is exposed. No manual/unlisted event entry exists.

Choices persist only bounded historical facts: internal calendar UUID, event ID,
recurring parent/original start, occurrence hash, operational date, start/end wall
time, sequence, cleaned title and location. No description/full Google payload.
Selection checks the current assignment, freezes one choice and cannot switch to
another job in the same form. After selection, no Google read is required to submit.
An outage, event edit, reassignment or midnight does not rewrite the frozen job/date.
Active status, binding generation/identity and session validity are still checked
under locks. A new assignment before selection requires a new form.

## Business values

There is no separate invented report-type/status field. The evidenced payment /
outcome categories are CASH, ZELLE, CHECK, CREDIT_CARD, VENMO, SUPER, ESTIMATE, CANCEL.
CREDIT_CARD is displayed as **Credit Card / Cash App**; historical CASH_APP aliases
normalize to it. Case/whitespace normalization is explicit. ESTIMATE and CANCEL
force `0.00` on the backend and via a PostgreSQL check. The outcome category remains
meaningful even with zero amount; no invented NONE category replaces it.

Money is a nonnegative decimal string, Python Decimal, PostgreSQL NUMERIC(12,2),
maximum 9,999,999,999.99. Reject floats, exponent syntax, nonfinite/negative values,
extra decimal places and oversized amounts. No silent rounding of third decimals.
Reviews are explicit integer **counts** for GOOGLE, GROUPON, FACEBOOK, each 0–100;
no bonuses or booleans. Closer is MYSELF or CALL_CENTER, not another technician.
Maintenance-plan-provided is an explicit boolean. Comments are optional, stripped,
limited to 4000 characters, control/bidi characters normalized, rendered as text.

## Transactions, history, and recovery

Lock order is technician → binding → form session. Lifecycle operations use the
same technician row boundary. One transaction inserts WorkReport, immutable
revision 1, marks the session SUBMITTED, stores canonical-payload hash and audits.
The response is constructed before commit and returned after successful commit.

One report identity per technician + calendar + event occurrence is database-unique.
Recurring instances use parent+original-start when present, otherwise instance event
ID. Calendar scope is included to avoid collisions between provider calendars.
The report references its exact current revision through a deferred composite FK.
Future accounting must join that pointer, never sum all revisions. Stage 5 triggers
reject report/revision update or delete. Future corrections need an explicit audited
revision workflow and corresponding migration, not bypassing these safeguards.

Same session and normalized payload returns the same receipt (including after TTL
when still active/current). Different values return FORM_ALREADY_SUBMITTED. A second
session for the same job returns already-reported, never revision 2. Lost-response
retry retains the exact client payload. A precommit failure rolls back everything;
postcommit response loss is recovered by replay/reopening the submitted form.

Confirmation is the browser's **Report submitted successfully** receipt. Optional
Telegram report confirmations are deliberately not queued in Stage 5; therefore
there is no confirmation provider call/acceptance ambiguity or confirmation retry
queue to couple to money persistence. The command link itself is an existing
best-effort command response: if lost, send `/report` again. Never replay an uncertain
Telegram send automatically. A future report notification must use the audited
durable outbox pattern, not synchronous send-inside-transaction code.

## Retention and manager UI

Manager detail shows latest 20 reports, manual refresh, read-only business facts and
revision. API limit is 1–100. Identity-keyed state prevents technician A showing under
B. No net/profit/payout/expenses or misleading full accounting dashboard is shown.
Permanent technician deletion is blocked once reports exist; deactivate instead.
RESTRICT FKs and immutable history protect direct SQL too. Historical name at
submission is retained, not license/SSN/Telegram profile data. Calendar reference
also cannot be destroyed with history. Google exclusions preserve the calendar row.

The additive migration follows d4e509170002. Empty downgrade is supported; populated
report downgrade refuses before dropping data. Development manager account/volume
must never be reset. Anonymization/legal retention, backup retention and automated
expired-form snapshot purge require policy before pilot (TECH_DEBT TD-031).

## Safe local verification runbook

1. Check branch/status and `docker compose ps`. Never delete
   `technician-hub_postgres_data` or run `down -v`.
2. Use `docker compose --profile test up -d --wait test-db` and the existing venv.
3. Run `python -m pytest apps/api/tests/test_work_reports.py apps/api/tests/test_work_report_concurrency.py -q`
   against the guarded local technician_hub_test database. Both providers are fakes.
4. Run `npm run test:e2e -w apps/web -- work-reports.spec.ts`. The existing stdin-only
   guarded harness creates fictional identity/assignment and a trusted fake command;
   no web simulation route exists. The test checks mobile input, stored report,
   refresh receipt and manager read-only visibility. Synthetic screenshots are local.
5. Run complete regression/migration/contract/lint/build checks as documented in
   STAGE5_WORK_REPORT_VERIFICATION.md. Do not run independent suites concurrently
   on the same test database.

## Later dedicated TEST-provider acceptance (NOT performed automatically)

Use a separately approved HTTPS test deployment, TEST Telegram bot, fictional
technician, owner's test Telegram user and dedicated Google test account/calendar.
Never use real customers/technicians/groups. Approve TLS/origins and protect external
credential keys first. Follow existing onboarding and event-read scope runbooks.

Create clearly fake timed jobs including recurring instances, canceled/fake titles
and an all-day event. Link only the fictional technician and assign the test calendar.
In the private bot type `/report`; inspect the mobile form, select a valid job and
submit a small synthetic cash amount. Reopen/retry and verify one report/revision.
Try ESTIMATE/CANCEL, each review count, closer and maintenance. Check manager detail.
Open/select then remove network/provider availability; submission should still
commit while the form remains valid. Reassign after selection and verify original
job; disconnect/rebind/deactivate and verify rejection. Do not expect Calendar writes
or Telegram post-submission broadcast. Record sanitized results, then deactivate
the fictional technician; do not bypass business-history retention for cleanup.

Stop on identity, leakage, money, duplicate or retained-history discrepancies. Real
acceptance and retention policy remain explicit gates; this runbook grants no live
provider execution authority.

## Independent audit follow-up

[The independent Stage 5 audit](AUDIT_STAGE5_WORK_REPORTS.md) verifies and records
the final gates. Form issuance/expiry uses PostgreSQL wall-clock time after lock
acquisition. Recurring occurrence original-start instants normalize to UTC before
hashing, including legacy cached forms. Migration e5f509180003 rekeys derived
identities only and refuses collisions without deleting or merging history.
Stop older application writers during upgrade; populated downgrade is refused.
Migration e5f509180002 also enforces contiguous revisions and complete submitted
session markers. Historical financial snapshots remain unchanged.

Leaving ESTIMATE/CANCEL for a paid method clears the forced zero and requires a
fresh entered amount. Concurrent component effect opens share their in-flight
request to avoid colliding with the calendar reader's busy guard. A genuine read
failure still exposes explicit retry. Bearer transferability and expired-form
retention remain the documented TD-030/031 deployment obligations.
