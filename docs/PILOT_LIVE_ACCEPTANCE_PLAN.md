# Minimal live acceptance plan for one fictional technician

This is the smallest live-provider sequence that can close TD-022, TD-027, TD-028, TD-030, and
TD-033 for a controlled internal TEST pilot. It must run only after the policy and deployment gates
in `PILOT_POLICY_DECISIONS.md` and `PILOT_RUNBOOK.md` are approved. No step may use customer data,
an operational technician, an existing customer chat, calendar, or spreadsheet.

## Exact TEST resources to create

1. One dedicated Telegram bot created only for this exercise, with its expected numeric identity,
   username, and token stored in the deployment secret store or mounted token file.
2. One operator-controlled Telegram account acting as the fictional technician, with a dedicated
   private chat with that bot.
3. One dedicated TEST Telegram group containing only the fictional technician account, the bot, and
   the minimum operator accounts needed for the exercise.
4. One dedicated Google Cloud TEST project with an OAuth web client, exact HTTPS callback URI,
   narrow Calendar and Sheets scopes, and the dedicated account listed as a test user.
5. One dedicated Google account containing no personal or customer information.
6. One dedicated TEST calendar with fictional jobs covering ordinary, empty, private, recurring,
   cancelled, paginated, and daylight-saving-time cases.
7. Two dedicated TEST spreadsheets: one Individual target and a different All Tech target. The
   application deliberately prevents two targets from sharing a spreadsheet.
8. One fictional Technician Hub technician with an explicit IANA accounting timezone, blank license
   ID and SSN last four, no external photo, one calendar assignment, and fictional Work Report and
   Expense values.
9. One isolated HTTPS TEST deployment using the reviewed release commit, retained database volume,
   private backup location, managed secrets, and configured monitoring route.

Record only resource labels. Never record bot tokens, OAuth secrets/codes, refresh/access tokens,
encryption keys, chat IDs, spreadsheet IDs, or credential-bearing screenshots.

## Entry gate

- Record release commit, Alembic head, operators, reviewer, UTC start, approved policy choices, and
  stop conditions.
- Verify clean build, exact HTTPS origin/callback, private backup plus manifest, isolated restore
  evidence, `preflight` with no BLOCK, and `queues --require-pass` with enabled workers RUNNING.
- Confirm the normal database fingerprint, manager, calendars, and named volume before creating the
  fictional technician.

## Exact live acceptance order

1. **Private Telegram onboarding — TD-022.** Issue one invitation, open it in the TEST mobile
   client, verify exact bot identity and single use, connect the private chat, and send one bounded
   test message. Reuse/replay must fail without changing the binding.
2. **TEST group onboarding — TD-022/TD-023.** Add the bot and fictional technician to the TEST group,
   connect through the intended actor, verify minimum send permissions, remove the technician or
   bot, confirm availability fails closed, then restore membership and revalidate. Record public-bot
   abuse observations without sending traffic from uncontrolled accounts.
3. **Google OAuth and Calendar discovery — TD-027.** Connect the dedicated Google account through
   the exact HTTPS callback; verify consent scopes, primary identity, refresh across an application
   restart, primary/shared/hidden calendar visibility, exclusion, rescan, revocation failure, and a
   clean reconnect.
4. **Calendar event reads — TD-027/TD-030.** Read only the fictional TEST calendar and verify empty
   day, pagination, recurring instance/exception, cancellation, private-field handling, provider
   timezone, and daylight-saving boundaries. Confirm no event content appears in logs.
5. **Mobile forms — TD-030.** From the TEST private chat, open and submit one Work Report and one
   Expense on the supported mobile Telegram client. Verify HTTPS, purpose/technician/generation,
   one-time submission, safe receipt retry, explicit timezone, midnight boundary, and the documented
   transferable-bearer limitation. Confirm canonical daily and weekly accounting.
6. **Schedule delivery — TD-028/TD-029.** Preview and send one fictional schedule to the verified
   TEST group; verify destination, escaping, Telegram length behavior, acknowledgement, duplicate and
   late callback handling, no private fallback for new official daily/manual dispatches, and removed-membership
   failure. Exercise an ambiguity with a controlled TEST failure only if it can be induced without
   risking another destination; confirm ordinary retry is unavailable and record the manager choice.
7. **Individual Google Sheet — TD-033.** Configure the Individual TEST spreadsheet, sync one week,
   and verify RAW values, owned range, formatting, deterministic tab identity, retry, manual resync,
   provider rate handling, revocation, and reconnect.
8. **All Tech Google Sheet — TD-033.** Configure the different All Tech spreadsheet, sync the same
   week, and verify deterministic technician/day ordering, values, formatting, retry, and that the
   two targets cannot overwrite one another.
9. **Parity and recovery.** Compare UI daily/weekly results, canonical accounting JSON, XLSX, and
   both Sheets projections. Restart API/Web/workers once, verify current heartbeats and empty or
   reviewed queues, and confirm the fictional records remain canonical.
10. **Close and clean up.** Record sanitized PASS/FAIL for each acceptance row, reviewer, client
    versions, UTC times, release commit, and evidence location. Disconnect integrations and revoke
    TEST grants/token when ending the exercise. Delete external TEST resources only with explicit
    operator intent; retain application business/audit evidence under the approved policy.

Stop immediately for wrong identity, wrong destination, customer data exposure, duplicate financial
records, database integrity failure, credential leakage, or an unexplained ambiguous send. Keep the
corresponding debt open after any failure. Mirror delay or a temporary rate limit is a degraded state
to investigate and reconcile; it is not by itself canonical financial corruption.

## Acceptance record

| Step | Blocking debt | Result  | UTC time | Release | TEST labels | Client versions | Sanitized evidence | Reviewer |
| ---- | ------------- | ------- | -------- | ------- | ----------- | --------------- | ------------------ | -------- |
| 1–2  | TD-022/023    | PENDING |          |         |             |                 |                    |          |
| 3–4  | TD-027        | PENDING |          |         |             |                 |                    |          |
| 5    | TD-030        | PENDING |          |         |             |                 |                    |          |
| 6    | TD-028/029    | PENDING |          |         |             |                 |                    |          |
| 7–8  | TD-033        | PENDING |          |         |             |                 |                    |          |

Only reviewed PASS evidence can change `Live completed` in
`TEST_PROVIDER_ACCEPTANCE_MATRIX.md`. Local fake-provider reruns never substitute for this plan.

## Required additions for the approved pilot workflow release

Use matching API/Telegram worker/frontend with migration `fea610060001` or its successor. The normal
database is not a test fixture. Apply approved deployment/backup procedures before live activation.
The prior order remains: private onboarding -> group -> Google read setup -> forms/activity ->
schedule/ACK -> Sheets -> parity/recovery. Calendar remains read-only; do not grant write scope or
expect a report description update. Menu contains /report, /expenses and /daily; no /tomorrow.

At step 5, test one report and one expense with fictional values. Verify browser success, one stored
record/revision and one activity intent on receipt replay. Verify the exact TEST work group receives
the matching saved technician/date/operational facts, literal formatting, no internal IDs/tokens and
no private fallback. In the technician page open Saved submissions, then each record; verify saved
name, timestamp and revision even after renaming the fictional profile. Compare Accounting as before.

Observe Recent Telegram activity for SENT, FAILED, CANCELLED or UNKNOWN. A known unavailable group
must not prevent the financial save. Lost membership, revoked bot rights and replacement must not
send queued facts to a different destination. Transient lookup failures must not disclose facts to
an unverified group. Use automated fake injection for uncertainty when a live failure cannot be
safely induced. UNKNOWN is an operator review, never permission to reset/replay or submit a second
expense. Repair setup and document manual follow-up; replacement does not backfill old messages.

At step 6, acknowledge the current exact schedule twice and verify one stored ACK. Send a changed
schedule or explicit resend for the same technician/work date; old button must fail immediately,
even before the new send completes. Acknowledge the new delivered message. Verify a different actor
cannot ACK and known UNAVAILABLE/REVALIDATION_REQUIRED effective binding rejects ACK. Restore through
normal revalidation. Preserve previous receipt/ACK history; ACK means seeing the exact schedule only.
Record the release/client versions and sanitized evidence, without tokens or destination identifiers.

All live matrix rows remain pending until this is executed and reviewed. This document does not
constitute provider execution or deployment approval by itself.


### Daily to next-schedule acceptance (2026-10-08)

Use only the dedicated TEST bot, private chat, Work Group and assigned TEST Google calendar.
With `SCHEDULE_DELIVERY_ENABLED=true` and the configured payload key, keep
`SCHEDULE_TIMED_AUTO_ENABLED=false`; pilot mode also hard-blocks timed creation.

1. In the bound private chat run `/daily`. Compare totals and business date/timezone with manager
   Daily Accounting. Confirm the separate schedule result says queued until actual delivery.
2. Verify the official schedule appears only in the bound Work Group. ACK as the technician twice;
   confirm one persisted receipt. A different group member must not ACK.
3. Open technician **Send next schedule**. Review date, job count/content and Saturday's
   Sunday-empty explanation; explicitly Send. For changed content, the new same-date dispatch
   supersedes the old one and its old ACK must fail.
4. Exercise Saturday with eligible Sunday jobs, no Sunday jobs, and only cancelled/fake/ineligible
   jobs. After an empty-Sunday decision, a newly added Sunday job requires an explicit manager send;
   no automatic calendar-change detection is provided.
5. With unavailable/revalidation-required group, `/daily` must still return accounting and a safe
   schedule failure message; no private schedule fallback. Restore/revalidate before retrying.
6. Observe clock-based scheduler time with no daily/manual trigger: no new official schedule.
   Confirm already queued schedules still drain normally. An ambiguous send requires manager review,
   never blind replay. Finish with provider-silent status/queue checks and retain TEST evidence.


### Existing Work Group member rejoin recovery (2026-10-08)

- **Removal detection: PASS (operator-reported live TEST evidence).** Removing the bound
  technician changed the same Work Group to UNAVAILABLE and blocked delivery.
- **Same-group rejoin recovery: PENDING live TEST.** Local fake-provider regressions prove
  recovery; no real provider was contacted for this change. Repeat removal/rejoin after deploying
  the fix. Re-add exactly the same linked Telegram account to exactly the same bound group while
  the bot remains present with send access. Wait for the worker's existing VERIFY_GROUP job to
  finish; expect Connected/AVAILABLE without a new invitation or generation.
- Recovery checks the bot identity, live bot permissions and technician membership outside a
  business transaction, then rechecks the pinned identities, private/group generations, current
  private relationship, active technician and uncancelled verification job under the technician
  lock. New lifecycle events cancel older verification proofs. Replacement/migration, mismatched
  identity or stale generations require repair; they are never automatically adopted.
- Cancelled activity is not replayed and uncertain sends are not retried by recovery. Verify a
  fresh manager test message or new TEST activity after recovery. Repeat a different-user/group
  attempt and bot-access loss to confirm fail-closed behavior. Transient read-only verification
  failures use the existing bounded outbox retry; exhausted failures require operator repair.
- A group already stuck before this release has no queued recovery job: repeat the controlled
  same-member leave/rejoin to trigger verification. This change does not sweep or rebind groups.


### Private schedule ACK and Daily group summary acceptance (2026-10-08)

Live status: PENDING. Apply migration `ffd610080001` and wait until Web and the combined Worker
(Telegram and Schedule processes) run this release before resuming TEST actions. Do not trigger
new daily/manual schedules during a mixed-version rolling rollout. Then:

1. Run `/daily` privately as the linked TEST technician. Compare the private full accounting with
   canonical manager Daily Accounting. In the Work Group verify only the short name/report-count/
   gross/expense completion event, including an explicit zero-day case. No payment/review/maintenance
   breakdown, identifiers or tokens may be shown. Replaying the same action must not duplicate it.
2. Verify the official group schedule has waiting status and **no button**. The linked private chat
   receives a separate dated job-count prompt with **Confirm schedule**. Daily and manager manual
   sends share this path; confirmed group delivery must precede its private prompt. For `/daily`,
   the schedule waits while its summary is QUEUED/PROCESSING; a terminal summary failure/UNKNOWN
   does not suppress the independent schedule or roll back private accounting.
3. Confirm privately. Expect one final success response, one canonical ACK timestamp in manager Web
   and one concise group confirmation event with date/name/UTC time. The adapter has no safe edit
   capability: the original waiting message is not rewritten; the confirmation event updates the
   activity feed. Repeated confirmation must not add events or alter the receipt time.
4. Send a changed/explicitly replaced schedule. Old private buttons must say the schedule was updated;
   the new dispatch requires its own ACK. Managers clicking historical group buttons cannot confirm.
5. Exercise unavailable/revalidation-required groups and rebound identities. No pending summary,
   prompt or confirmation may move to the new generation. Confirm private accounting survives group
   summary or schedule failure. Preserve failure receipts; do not resubmit accounting to retry sends.
6. UNKNOWN/AMBIGUOUS sends require operator review, never automatic replay. A private prompt whose
   receipt is uncertain cannot authorize ACK without a known message ID; the manager may explicitly
   resend the schedule with the existing duplicate-risk confirmation. Prior buttons become stale.

No real Google/Telegram calls were used to implement or test this change. Other live acceptance
blockers remain open; new local tests do not constitute provider acceptance.


### Full Daily and Calendar report mirror update (2026-10-08): PENDING

This replaces the short-summary expectation in the previous sequence. Wait for migration
`ffe610080001` and matching Web/Worker releases. Reconnect the same dedicated TEST Google account
using **Enable report write-back**; the assigned TEST calendar must grant writer/owner access.
Submit a fictional report. Verify one `[TECHNICIAN HUB REPORT]` block on the exact source event,
with manual description bytes outside it preserved. Check `report_calendar` queue health.
Run `/daily`: full canonical report must match in private and Work Group, including a zero day.
Check eight-job presentation, each native copy-address button, useful filtered details, private
full schedule + Confirm schedule, group no ACK controls, and one group confirmation event.
Repeat supersede, unavailable-group and replay checks. Do not count automated tests as live PASS.
