# End-to-end workflow parity audit

## Approved full Daily / shared schedule / Calendar report mirror (2026-10-08)

This product approval supersedes the short group-summary and no-Calendar-write-back decisions
recorded in the historical sections below. Both Daily destinations use the same canonical `render_daily` text. The durable group
intent freezes that text for retries/replay; financial calculations are unchanged. Zero days
include the complete zero-valued breakdown. Group failure cannot undo the private accounting.

Group, private confirmation and manager preview use one normalized schedule snapshot. The
Google-only `legacy_presentation` adapter removes numeric prefixes and recognized phone spans
from presentation titles, separates phones/locations, and hides recognized dispatcher/history
lines and report sections. Source events are never changed by formatting. The private prompt
now contains the full schedule; group messages have copy-address buttons but no ACK controls.
Native `CopyTextButton` rows preserve each address, with job numbers to distinguish them.
Single-message size and Telegram's 256-character copy-text limit fail closed before enqueue;
message splitting remains deferred. Pending legacy v1 snapshots retain fingerprint compatibility.

Report persistence atomically creates a `report_calendar_mirrors` intent through PostgreSQL
triggers. No existing reports are backfilled. The existing Google mirror worker drains this
independent lane. It pins connection/calendar/event identity, reads the current canonical
revision, refetches the source, then conditionally PATCHes only `description` with `If-Match`.
Only `[TECHNICIAN HUB REPORT]` through `[/TECHNICIAN HUB REPORT]` is owned by Hub. Every character
outside recognized blocks is preserved; malformed markers block writing. Reconciliation reads
first after crashes, timeouts or ETag conflicts; duplicate complete managed blocks are collapsed.
No Telegram UserID or internal DB IDs are rendered. Nothing reads this block into accounting.

Explicit same-account OAuth reconnect via **Enable report write-back** requests Calendar event
write permission. Read-only/disconnected/excluded/wrong-account or conflicting source mappings
remain BLOCKED. Same-account credential rotation is allowed under the existing lifecycle lock;
account replacement never redirects a queued report. Operations exposes `report_calendar` queue
counts. BLOCKED attempts retry no sooner than five minutes; correcting access/source is required.
Google errors do not affect report persistence, accounting or Telegram activity delivery.

Migration `ffe610080001` is additive except for relaxing the sent-snapshot purge timing: the
encrypted schedule snapshot is retained until successful private prompt receipt, or the existing
seven-day expiry/cleanup bound. Prompt tokens, generation checks, exact/private/current ACK,
supersession, idempotency and pilot timed-auto OFF are unchanged. Historical report rows/revisions
remain immutable: this release adds no correction UI/API. A newer canonical revision is covered
by a controlled test-only pointer fixture; a future authorized correction workflow must also
invalidate its other existing projections. Destructive rollback with mirror receipts is refused.

Live Google/Telegram acceptance remains PENDING. After Web/Worker migration/rollout completes,
grant write-back permission to the same TEST Google account, submit a fictional TEST report,
verify the one managed block and untouched manual notes, then verify Daily parity, private/full
schedule, copy-address buttons and exact ACK on Telegram mobile. No real provider acceptance
result is inferred from fake-provider tests.

Local verification for this approval: the 1,184-case affected PostgreSQL regression run had
1,182 passes and two test-expectation failures (safe HTTP 500 on an injected rollback and the
new operations queue key). Those assertions were corrected; the final complete mirror,
presentation, private-ACK, pilot-ops and operator subset passed **149/149**, including a direct
group/private/manager-preview comparison. No unresolved test failures remain. Frontend **65/65**,
typecheck, changed-file ESLint and production build passed. Python Ruff/format, deterministic
OpenAPI/TypeScript regeneration, secret scan and whitespace checks passed. The guarded disposable
migration harness passed fresh/round-trip/populated preservation, destructive rollback refusal,
one head `ffe610080001` and zero drift. Real providers were blocked in automated tests. The normal
DB, manager, calendars and Docker volume were not accessed or modified; preservation is by
non-interaction, not a new checksum of business data.

References: [Telegram CopyTextButton](https://core.telegram.org/bots/api#copytextbutton),
[Calendar conditional updates](https://developers.google.com/workspace/calendar/api/guides/version-resources).


## Private schedule confirmation and short Daily group event (2026-10-08)

This approval supersedes the earlier group-summary deferral. `/daily` keeps the full canonical
Daily Accounting breakdown private and queues a two-line completion event with technician name,
report count, canonical gross and expenses. Zero days explicitly show zero counts/amounts. The
admitted-update request key uniquely owns the summary intent, including failed/uncertain outcomes.
Accounting, summary and schedule outcomes remain independent; the next-date resolver is unchanged.
The schedule claim waits for its Daily summary attempt to finish across workers; a terminal failed
or UNKNOWN summary does not suppress the schedule. Manual sends have no Daily-summary dependency.

New official dispatches show the full schedule plus waiting status in the Work Group, with no ACK
button. On a confirmed group send, the same transaction queues one private prompt for that exact
dispatch. Its button says **Confirm schedule**. ACK additionally matches the private chat/message;
current actor, bot, generations, group availability, expiry and supersession checks still apply.
Manager manual sends use the same service and delivery path. Timed pilot creation remains disabled.

The current provider adapter has no safe edit operation, so successful ACK atomically queues one
concise group confirmation event with target date, technician and canonical confirmation timestamp
(UTC). The original group message retains its waiting line; the later confirmation event is the
status update. Manager Web continues to display canonical `ack_status`/`acknowledged_at`. Unique
outbox references prevent duplicate intents; ambiguous sends/crashes remain UNKNOWN with no blind
resend. Newer dispatches invalidate old private buttons and old queued notices; earlier receipts
remain historical. Historical messages may retain their old buttons, but never grant managers ACK
rights. Historical dispatch receipts are not rewritten by the additive migration `ffd610080001`.

Callbacks attempt one final safe response, including rejected, expired, superseded and rate-limited
paths, without an interim Checking answer. Provider failure cannot roll back an ACK. These are local
implementation results; deployed/private-client behavior still needs controlled live TEST acceptance.

Local verification: affected backend regressions passed 651 tests (four unrelated accounting
query-budget cases deselected). After the final cross-worker ordering change, all 131 focused
private-ACK/Daily/schedule tests passed on final source. Existing manager schedule/Telegram UI
tests passed 35 tests. API contract snapshot, Ruff and secret scan passed. The guarded disposable
PostgreSQL migration harness passed fresh upgrade, round trips, fixture preservation, a single
`ffd610080001` head and zero drift. Populated new receipt rollback refusal is covered separately.
Providers were fakes; the normal database and retained Docker volume were not accessed.

## Daily workflow restoration (2026-10-08)

This approval supersedes the earlier `/daily` deferral below. `/daily` is now a private,
bound-technician command/menu entry: it renders canonical Daily Accounting totals for today
in the accounting timezone, then uses the shared calendar-timezone next-schedule resolver and
existing ScheduleDispatch pipeline. Accounting and schedule outcomes are reported separately;
schedule errors never roll back accounting. The private accounting receipt is attempted before
Google work, with a durable attempt checkpoint preventing blind resend after a crash/uncertain send.
The separate schedule receipt says queued, not delivered.
Manager **Send next schedule** opens the same backend preview with date, jobs and Sunday-empty
explanation, followed by explicit Send. No frontend business-date resolver was introduced.

Mon-Fri select the next day (Friday includes Saturday). Saturday selects Sunday only when the
canonical schedule filter finds eligible Sunday jobs; otherwise Monday. Sunday selects Monday.
No forward search occurs. New `TECHNICIAN_DAILY` and `MANAGER_MANUAL` dispatches are Work Group
only; unavailable/revalidation-required/rebound groups cancel delivery with no private fallback.
Historic dispatches retain their recorded legacy semantics. Exact/current ACK, superseding,
membership checks, immutable snapshots and ambiguous-send handling reuse the existing pipeline.
Daily request keys are tied to the durable admitted-update reservation so crash replay cannot
create a replacement schedule; a later Telegram ID epoch receives a distinct key.

`SCHEDULE_TIMED_AUTO_ENABLED` defaults false; pilot mode refuses timed creation even if set true.
The schedule worker still drains durable dispatches. `/tomorrow`, Calendar write-back and the
original legacy group Daily summary remain deferred/out of this approved private-summary scope.
Local verification: 25 daily workflow integration tests and 890 affected Telegram/Calendar/Schedule,
Work Report and canonical accounting regressions verified across the affected run and corrected
legacy-expectation rerun (three unchanged accounting query-budget benchmarks excluded). Also passed:
44 provider-silent operator/migration-resolver/logging checks, 41 frontend tests, typecheck, lint,
production build, deterministic generated contracts, migration upgrade/roundtrip checks and zero drift.
PostgreSQL was the isolated local test cluster; no normal DB/volume or real provider was used.
Live provider acceptance is still required; local fake-provider evidence does not close it.


## Approved pilot workflow completion (2026-10-06)

This section supersedes the historical gap dispositions below. Implementation starts from audit
commit `2d87ed738cd9909f0caca6b737ed98c577f66a66`. The following choices are now explicitly approved:
Work Report and Expense group publication are required; Calendar report write-back is intentionally
not restored; `/daily` and `/tomorrow` are deferred. Neither command is advertised or implemented.

| Workflow                    | Current approved result                                                                                                  | Classification                                  |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------- |
| Report -> PG -> Work Group  | Same-transaction durable activity intent; existing Telegram worker sends saved revision facts to the captured work group | IMPLEMENTED locally; live required              |
| Expense -> PG -> Work Group | Same path, with saved expense date/timezone/type/amount/note                                                             | IMPLEMENTED locally; live required              |
| Schedule ACK                | One exact dispatch, only while current/non-superseded and effective binding/destination available                        | IMPLEMENTED locally; live required              |
| Manager saved details       | Real technician page exposes read-only report/expense dialogs, saved name, revision and submission time                  | IMPLEMENTED locally                             |
| Calendar report write-back  | No event-write scope, mutation, or report projection restored                                                            | INTENTIONALLY REMOVED from approved pilot scope |
| `/daily`, `/tomorrow`       | No handlers or Menu entries                                                                                              | INTENTIONALLY DEFERRED                          |

### Delivery and recovery contract

`hub.telegram.activity.enqueue_activity` adds a WORK_REPORT/EXPENSE reference to the existing
`TelegramOutbox` inside the submission transaction. Unique report/expense references prevent extra
intents on receipt replay; a rollback removes both fact and intent. Worker provider I/O happens only
after commit. Provider failure cannot undo the report/expense. The outbox stores references and
captured group/user/generations, not copied form secrets or plaintext report bodies. Rendering reads
the immutable submitted revision and uses plain text, no parse mode, no IDs/tokens. Long notes and
context are visibly abbreviated to keep a single message below Telegram's length limit; complete
facts remain in the manager view. No multipart send or new worker/reliability system was added.

The existing worker checks active technician, exact bot/group/user and generations, group bot send
rights and technician membership, then re-reads binding/cancellation after membership I/O. Activity
never falls back to private chat and never follows a later group replacement. Missing/unavailable
group at submission records a CANCELLED intent without blocking persistence. Unverified membership
or definitive rejection stops the activity; confirmed rate rejection uses the existing bounded
retry (at most three attempts, allowed retry_after <=600 seconds). Unknown send results and claimed
work after a crash remain UNKNOWN and are not automatically resent. Exactly-once external delivery
is not claimed. Recent Telegram activity exposes Work report/Expense labels and delivery outcomes.

There is deliberately no new financial correction, activity-resend endpoint, historical backfill,
or private post-save notification. Browser receipt confirms persistence. FAILED/CANCELLED/UNKNOWN
require operator review: inspect the saved manager record and the TEST group, repair setup, and
record a manual communication decision if needed. Never resubmit the expense to recover a message,
reset UNKNOWN to QUEUED via SQL, or assume connecting a replacement group republishes history.

### Exact ACK semantics

Every newly accepted ScheduleDispatch supersedes prior dispatches for that technician/work date
within the same transaction and technician lock used by ACK. This happens at enqueue, including an
explicit resend; even a later failed/cancelled new dispatch does not reactivate an older button.
Coalesced duplicate enqueue creates no replacement. A different work date is independent. The
superseded timestamp is additive: SENT receipts and any earlier acknowledgement remain historical
facts. Old buttons are rejected, including previously acknowledged buttons after supersession.

ACK requires SENT, unexpired token, exact bot/actor/chat/message, active technician, current private
and applicable group generations and AVAILABLE effective binding/destination. UNAVAILABLE,
REVALIDATION_REQUIRED and other unavailable states are rejected. Concurrent duplicate valid ACKs
return idempotent success and record one acknowledgement/audit. ACK means only the technician
confirmed seeing that exact schedule, not job completion, payroll approval, or business acceptance.
The manager history displays supersession without erasing earlier receipt evidence.
Pilot readiness now requires an available work group for report/expense activity even with automatic
schedule delivery disabled; financial submission itself still does not depend on group availability.

### Migration, verification and remaining gaps

Additive migration `fea610060001` follows `fda609200001`: nullable outbox source/destination fields,
source uniqueness/FKs/kind constraints, and schedule superseded_at. Existing activity is not backfilled
or sent. Existing older same-date schedules are marked superseded deterministically by created_at
then UUID; where old timestamps tie, this matches existing history ordering, not an inferred send
chronology. Populated activity/supersession rollback is refused. Stop old writers/workers during
migration and deploy matching API/worker/frontend code; this pass applies migration only to an
isolated synthetic database, not the normal database or Render.

Verification for this change:

- Focused backend adversarial set: 27 passed, including populated migration, failure/replay,
  membership/rebinding, concurrent claim, supersession and concurrent ACK checks.
- One full backend gate completed: 1,564 passed, 5 failed, 2 skipped (3 dependency deprecation
  warnings). Four failures exposed the stale operational expected-schema constant; one exposed
  swallowing an unexpected onboarding send exception. Both causes were fixed: preflight expects
  `fea610060001`, and unexpected send exceptions retain the existing worker crash/recovery path.
- Final affected rerun: all 224 tests passed across pilot activity, operational/readiness and all
  Telegram test modules, including all five previously failing cases. The full suite was not run
  a second time after these two narrow corrections. The two full-run skips are existing POSIX TTY
  manager-CLI tests skipped on Windows; Docker/Linux TTY execution is not claimed.
- Frontend: 12 files / 150 tests passed, including the real technician route and saved attribution
  dialogs; TypeScript, ESLint and Next production build passed.
- Migration lifecycle/drift validator passed: single head `fea610060001`, historical preservation,
  populated rollback refusal and zero schema drift. Generated OpenAPI/TypeScript were regenerated
  twice with identical hashes; their only schema addition is nullable `superseded_at`.
- Ruff lint passed. Changed Python files passed format checks. Repository-wide formatting still
  reports eight pre-existing, unchanged files; unrelated formatting was not included in this patch.
- Secret scan: 353 Git-visible files, zero findings. `git diff --check` passed.

All automated providers are fakes. Docker Engine was unavailable, so database checks used a new
isolated native PostgreSQL 18.6 cluster on loopback port 5547, database `technician_hub_test`, with
synthetic fixtures only. Normal database, manager, calendars and `technician-hub_postgres_data`
were not connected to, migrated, reset or modified. Preservation here is by non-interaction, not a
new normal-database fingerprint comparison. No container/deployment or live provider check is claimed.

The old P0 product decisions and local ACK/detail gaps are addressed for this approved scope.
Operational entry gates TD-012/017/025/029 and live gates TD-022/027/028/030/033 remain open. Controlled
live Telegram acceptance may resume only on the verified matching release after deployment entry
gates, using the expanded acceptance sequence. PILOT READY remains NO until reviewed live evidence.
P1 still includes explicit stop/review handling for incorrect financial submissions (no corrections),
redo/unlisted-job eligibility and timezone/membership acceptance. Deferred commands and intentionally
absent Calendar writes are no longer missing pilot workflow obligations. No Contracts/GPS/CRM work.

## Historical audit at 70186c5 (retained evidence)

Audit date: 2026-10-06. Audited branch: `main`. Exact application HEAD:
`70186c5102b2b7b2d35c68e7815cf965d4986a4d` (native Telegram command-menu change).
The working tree was clean before this audit. The audit commit changes this document only.

## Conclusion and evidence boundary

The implemented product supports a narrower workflow than the authoritative legacy application.
Private onboarding, report/expense intake, manager accounting, manager/automatic schedule delivery,
XLSX downloads, and optional Sheets projections have connected implementation paths. **The complete
technician-to-work-group reporting loop does not.** Saving a report or expense does not send it to
Telegram. `/daily` and `/tomorrow` have no current handlers. Daily Accounting in the manager UI is
not the technician Daily Report workflow.

Most missing links were explicitly deferred by stage scope, not accidentally deleted. Two further
issues require attention: the detailed manager record panels became unreachable during Stage 7;
and schedule acknowledgement does not enforce current availability or latest-dispatch semantics.
No financial corruption or wrong-recipient send is demonstrated by this audit.

Here, IMPLEMENTED means an end-to-end source path exists for the specifically named workflow,
including its human entry and output. It does **not** mean this audit performed browser, database,
or live-provider acceptance. PARTIALLY IMPLEMENTED identifies a missing link in the larger intended
workflow even when its omission was deliberate for one stage. INTENTIONALLY DEFERRED is not approval
to omit that behavior forever. ACCIDENTALLY DROPPED identifies a lost observable capability without
an evidenced product decision; intent cannot be inferred solely from a code deletion.

Business reference: read-only `C:\Users\rasha\OneDrive\Documents\ChatGPT\ez_telega_bot`,
Git HEAD `d0be8647b728f0910184614c1c85bfcb5e1c25fc`; observations are of its available source tree.
No legacy database, secrets, media, or customer records were opened. `C:\HVAC_TECH_CODEX` was not used.
Current executable paths take precedence over old Stage 0-9 status sentences. Legacy executable
behavior takes precedence over contradictory legacy prose. In particular, the early diagram in
legacy `docs/TECHNICIAN_BOT_WORKFLOW.md` says Daily output is private, but its later prose,
`docs/DAILY_REPORT.md`, and `bot.py:_send_daily_report` agree on **group output + private status**.

## Compact workflow matrix

Evidence keys point to the traced source below. Recommendations are proposals, not approved changes.

| Workflow                                                                | Intended behavior                                                                                       | Current behavior                                                                                                                             | Classification          | Missing link                                                                                      | Recommendation                                                                                                       |
| ----------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------- | ------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| Technician creation and setup                                           | Manager creates technician, sets identity/timezone/calendar, connects private chat and group            | Reachable create/profile/assignment/Telegram controls; setup projection and deactivation; pilot blocks deletion, DL/SSN and external avatars | IMPLEMENTED             | None for approved TEST setup; readiness is not release acceptance                                 | Follow setup order; do not use a green readiness badge as parity approval [E1]                                       |
| Private Telegram onboarding                                             | Invitation identifies the technician; status and usable navigation follow binding                       | Actor/purpose/generation checks, durable confirmation, `/start`/`status`, scoped native menu                                                 | IMPLEMENTED             | Live mobile/provider behavior still unaccepted                                                    | Test exact private actor and replay with TEST bot [E2]                                                               |
| Native Menu                                                             | Expose working private actions                                                                          | Exactly `/report` and `/expenses`; private reply keyboard removed, menu repaired on connected/form replies                                   | IMPLEMENTED             | Broader legacy menu intentionally absent, not broken registration                                 | Keep dead commands hidden; verify persisted menu in live client [E2]                                                 |
| `/report` to saved facts                                                | Private report action, eligible job, mobile form, durable report, manager sees values                   | Short-lived form, shared Calendar picker, frozen selection, PG report/revision/audit, browser receipt, manager Accounting facts              | IMPLEMENTED             | No group/private post-save notification in this bounded path; historical detail issue below       | Accept as intake only, not full legacy reporting [E3/E7]                                                             |
| Full Work Report operational loop                                       | Saved report reaches group, private status and Calendar projection; manager can inspect/recover         | Intake/accounting/Sheets enqueue exist; Telegram and Calendar post-save delivery do not                                                      | PARTIALLY IMPLEMENTED   | No report Telegram outbox, delivery/status/retry or Calendar write-back                           | Decide required pilot outputs; add only approved links in a later task [E3/E9]                                       |
| `/expenses` to saved facts                                              | Private form, server-owned date, expense persisted and visible to manager                               | Explicit timezone, scoped form, PG expense/revision/audit, browser receipt, Accounting facts                                                 | IMPLEMENTED             | No post-save Telegram output in this bounded path                                                 | Accept intake separately from group notification [E4/E7]                                                             |
| Full Expense operational loop                                           | Save -> group message -> private status -> recover delivery failure                                     | Facts and accounting exist; browser receipt only                                                                                             | PARTIALLY IMPLEMENTED   | No expense Telegram outbox, status, retry or private completion message                           | Decide group delivery and completion status before pilot [E4]                                                        |
| Work Group as shared operations channel                                 | Technician + company staff converse normally; bot posts reports, expenses, daily summary and schedules  | Human conversation stays in Telegram; binding, onboarding/test messages and official schedule messages exist                                 | PARTIALLY IMPLEMENTED   | Report, expense and Daily Report publications absent                                              | Treat group as schedule channel until required outputs are approved and implemented [E2-E6]                          |
| Group membership/revalidation                                           | Reject wrong actor/audience, invalidate lost access, restore through explicit revalidation              | Trusted-actor onboarding, lifecycle handling, explicit verification; schedule checks membership before send                                  | PARTIALLY IMPLEMENTED   | Continuous member-loss observation is not guaranteed for non-admin bot; ack ignores availability  | Preserve fail-closed send checks; resolve acknowledgement rule and live TD-022 evidence [E2/E6]                      |
| Daily Report technician workflow                                        | `/daily` -> local-day totals -> group Daily Report then next-workday schedule -> concise private result | Manager Daily Accounting only; neither command nor two-message dispatch exists                                                               | PARTIALLY IMPLEMENTED   | Private entry, renderer/orchestration, ordered durable messages, status/recovery                  | Explicitly accept deferral or scope this workflow for the pilot; do not alias `/daily` to a manager endpoint [E5/E7] |
| Technician-requested schedule                                           | `/tomorrow` requests informational next-workday schedule; group output or private fallback/status       | Manager preview and official dispatch exist; no technician command                                                                           | PARTIALLY IMPLEMENTED   | Private command/authorization and informational delivery/status path                              | Decide whether manager/auto schedules suffice for TEST pilot [E5/E6]                                                 |
| Manager/automatic schedule send                                         | Calendar -> preview -> durable dispatch -> chosen group/private destination -> visible result           | Shared fresh projection, encrypted snapshot, worker, bounded retry/ambiguity, history and callback path                                      | IMPLEMENTED             | Live delivery not proven; acknowledgement policy gaps are separate below                          | Exercise existing path after P0 acknowledgement clarification/remediation [E6]                                       |
| Schedule acknowledgement parity                                         | Legacy requires bound actor and latest non-superseded dispatch                                          | Actor/chat/message/generation/expiry validated; each SENT dispatch can be acknowledged                                                       | PARTIALLY IMPLEMENTED   | No availability gate; no superseded/latest-dispatch check                                         | Fix known-unavailable case; approve latest-only versus historical-receipt semantics [E6]                             |
| Google Calendar discovery/jobs                                          | Manager connects, discovers and assigns calendars, reads jobs for operations                            | OAuth/discovery/exclusion/reconnect -> assignment -> Today/preview/report picker; read-only event access                                     | IMPLEMENTED             | Google remains the job source, unlike legacy managed PG visits                                    | Preserve current architecture; confirm explicit eligibility differences [E8]                                         |
| Report write-back to Calendar                                           | Legacy replaces managed report block without destroying dispatcher text                                 | No write scope, event mutation or report Calendar outbox                                                                                     | PRODUCT DECISION NEEDED | Whole outbound report projection was expressly deferred at Stage 5                                | Choose retain read-only or separately approve narrow write-back; do not silently restore [E9]                        |
| Manager daily/weekly accounting                                         | See facts, totals, dates and historical technicians                                                     | Per-technician Overview/Daily/Weekly, backend date navigation, refresh and canonical totals                                                  | IMPLEMENTED             | Not technician self-service, payroll, or a company-wide web finance dashboard                     | Preserve scope; distinguish accounting read from delivery and detailed receipt inspection [E7]                       |
| Manager detailed submission inspection                                  | Open report/expense details including saved attribution and submission time                             | APIs and components remain, but detail page mounts only Accounting                                                                           | ACCIDENTALLY DROPPED    | No production import/JSX route to old detail modals; Accounting omits those details               | Restore a reachable detail action or equivalent approved view; no new financial mutation [E10]                       |
| Corrections and expense voiding                                         | Legacy corrects reports/expenses, retains revisions, excludes void expenses                             | New submissions are revision 1; resubmission conflicts; no correction/void API/UI                                                            | INTENTIONALLY DEFERRED  | Approved correction/void workflow and migration absent                                            | Before pilot, choose stop-on-mistake policy or separately scope remediation; never edit PG/Sheets ad hoc [E3/E4]     |
| Individual/All Tech XLSX                                                | Manager selects week, downloads usable output                                                           | Weekly UI -> manager API -> canonical snapshot -> shared renderer -> download                                                                | IMPLEMENTED             | No technician delivery or financial approval/settlement workflow                                  | Treat exports as outputs; manager handles sharing [E11]                                                              |
| Individual/All Tech Google Sheets                                       | Manager configures targets, business changes refresh projection, failure is recoverable                 | UI target config/sync/status/open -> durable coalesced queue -> worker -> RAW projection                                                     | IMPLEMENTED             | External sharing and historical backfill are manual; no inbound edits                             | Manually sync selected old weeks; review permissions; TD-033 stays open [E12]                                        |
| Receipt / service Contract                                              | Legacy `/receipt`, visit-bound form, immutable contract, PDF to group                                   | No business model/form/PDF/delivery implementation                                                                                           | INTENTIONALLY DEFERRED  | Entire workflow outside current scope                                                             | Keep P2; generated `packages/contracts` is API transport, not this product [E13]                                     |
| Receipt photos for expenses                                             | Humans can put photos in work group; app does not own attachments                                       | No expense upload/link field or storage                                                                                                      | INTENTIONALLY DEFERRED  | In-app attachment workflow intentionally absent in both current and inspected legacy expense flow | Keep manual group photos separate from service Contracts [E4]                                                        |
| Forms/Sheets as database; Discord                                       | Earlier infrastructure should not remain business authority                                             | First-party forms and PG facts; outbound Sheets only; no Discord                                                                             | INTENTIONALLY REMOVED   | None                                                                                              | Do not reconstruct obsolete intake/mapping dependencies [E3/E4/E12]                                                  |
| Wider roles, custom catalogs, CRM/dispatch/first-party Calendar, GPS/AI | Some exist in legacy or appear in future scope                                                          | Hub manager-only access and fixed audited categories; other domains absent/placeholders                                                      | INTENTIONALLY DEFERRED  | No approved current-pilot expansion                                                               | Keep P2; a legacy implementation is not authorization to port unrelated domains [E13]                                |

## Source traces and exact missing links

### E1. Manager setup

`apps/web/src/components/add-technician.tsx` and `profile-panel.tsx` reach
`apps/api/hub/technicians/router.py:create_technician/update_technician/set_calendar`.
The manager sets explicit accounting timezone and uses `telegram-connections.tsx` for separate
private/group invitations. `technicians/service.py:pilot_readiness` checks setup: it requires group
when schedule delivery is enabled and marks Sheets optional. It does not test report notifications,
Daily dispatch, current live acceptance, or deployment operations. Pilot policy intentionally keeps
initials only and deactivation; absence of deletion or sensitive inputs is not lost parity.

### E2. Telegram control surface and group security

`telegram/invitations.py` -> `claims.py` -> `updates.py` -> binding + confirmation outbox ->
`telegram/delivery.py` -> `adapter.py:send` is the connected onboarding path.
`adapter.py:139` registers only report/expenses with `BotCommandScopeChat` and restores the native
menu button for connected private replies. Private sends use `ReplyKeyboardRemove`. Menu setup
failure does not roll back binding; a later eligible reply retries. No group technician menu is set.
`transport.py:113` recognizes start/help/status/getid/report/expenses; unknown `/daily`, `/tomorrow`
and `/receipt` become no recognized command and can receive the connected home response, not a
workflow result. `updates.py:194` gates forms on exact private actor/chat; group messages do not issue
forms. Ordinary group conversation is not a Hub messaging feature and requires no reimplementation.

`telegram/lifecycle.py:14`, `bindings.py`, `verification.py` and `delivery.py` cover access loss,
migration, verification/replacement and generation fencing. `docs/TELEGRAM_ONBOARDING.md` explicitly
records the regular-bot observation limitation: trusted initiating actor proves onboarding presence;
that is not permanent membership proof. `schedule_delivery/delivery.py:219` verifies bot send rights
and technician membership before each schedule send; unproven transient inspection fails without a
send. Actual client/provider membership behavior remains TD-022. No administrator privilege or
provider behavior was assumed or changed here.

### E3. Report path

Private `/report` in `telegram/updates.py:219` -> `work_reports/service.py:issue` -> private fragment
link -> `apps/web/src/components/work-report-form.tsx` -> form/open/select/submit routes in
`work_reports/router.py`. `open_form` uses the Stage 3 calendar reader with server technician identity;
selection freezes one job. `submit` at line 289 locks/authorizes, inserts WorkReport + revision 1,
consumes the session, audits, and calls `accounting_mirrors/service.py:enqueue_for_business_change`
at line 353 in the transaction. Same-payload replay returns the saved receipt; another report for
the same occurrence conflicts. The browser displays success; there is no Telegram confirmation call.
Manager Accounting reads current revisions; configured mirror targets receive a durable refresh.
No report Telegram/Calendar delivery model or worker is called on this path.

Legacy `reports/services.py:257` creates per-revision `WorkReportDelivery` rows for both channels;
`reports/web_views.py` attempts delivery and acknowledgement after saving;
`reports/delivery.py` sends to the work group and updates Calendar. Current
`docs/LEGACY_WORK_REPORT_INVENTORY.md` explicitly DEFERs group broadcast, Calendar descriptions and
corrections. `docs/WORK_REPORTS.md` calls browser receipt authoritative and intentionally queues no
post-save Telegram confirmation. This is an unfinished full workflow, not evidence of accidental
notification removal in a later commit.

### E4. Expense path

Private `/expenses` -> shared purpose-bound form session -> `expense-form.tsx` ->
`expenses/router.py` -> `expenses/service.py:53` saves TechnicianExpense + immutable revision,
server-local submission date, consumed session and audit, and enqueues affected mirror weeks at
line 86. Manager Accounting uses these current facts. New sessions may create distinct identical
expenses; there is no fuzzy deduplication. Browser receipt is the only submission confirmation.
There is no group notification job/status/retry, correction, void, reimbursement or approval path.

Legacy `expenses/services.py:_enqueue/submit_expense`, `expenses/delivery.py` and
`expenses/web_views.py` connect saving to group delivery and private acknowledgement. Current
`LEGACY_EXPENSE_INVENTORY.md` explicitly defers notification/ack delivery and correction/voiding.
No receipt/photo upload is promised by either inspected expense implementation. Photos manually
posted by humans remain outside Hub's record and accounting guarantees.

### E5. Daily and technician schedule requests

Legacy `telegram_integration/bot.py:252,279,322,366,372` connects `/daily` to an immutable two-part
Daily dispatch and `/tomorrow` to an informational schedule request. `expenses/daily_report.py:40`
calculates totals; `expenses/daily_report_delivery.py:86` creates ordered message rows and retries
missing messages without recalculation. A missing group gives a private failure status for Daily;
standalone Tomorrow can show the schedule privately. Saturday/Sunday target Monday; Daily is today.

Current `telegram/transport.py`, `updates.py`, API routers and delivery models have no Daily command,
Daily parent/two-message queue, or informational Tomorrow handler. `accounting/router.py:47` is a
**manager-authenticated** daily read; technician form capabilities intentionally cannot use it.
Stage 7 verification explicitly excludes Telegram Daily delivery. Native-menu work at `70186c5`
exposes only working commands and did not remove an implemented Daily handler. The open decision is
whether that stage deferral remains acceptable for the first pilot.

### E6. Official schedule and acknowledgement gap

Manager `calendar-jobs.tsx` preview -> `schedule-delivery.tsx` send/resend/enable ->
`schedule_delivery/service.py:create_dispatch` re-reads next-workday content and checks preview
fingerprint -> encrypted PG dispatch -> `scheduler.py`/`worker.py` -> `delivery.py:deliver_one` ->
`telegram/adapter.py:send_schedule`. Group is preferred; current private identity is a bounded
fallback. Uncertain sends do not automatically retry/fall back. History distinguishes Sent from
Acknowledged; explicit resend warns of possible duplicates. Automatic decisions use assigned-calendar
local time, default 20:00 through before 23:00; whole-window outages do not reconstruct next-morning
catch-up. These limitations are documented, not a missing technician command implementation.

Callbacks travel `transport.py` -> `updates.py` ->
`schedule_delivery/acknowledgements.py:_acknowledge` (line 23). The guard checks SENT, expiry, exact
actor/bot/chat/message, active technician and binding generations. It does **not** check
`private_availability`/`group_availability`, call `can_deliver`, or query for a newer dispatch.
Ordinary member/bot loss in `telegram/lifecycle.py` changes availability without necessarily
advancing generations. An isolated execution of this exact function with synthetic DB responses
returned ACKNOWLEDGED for a matching group whose availability was UNAVAILABLE or
REVALIDATION_REQUIRED. Wrong actor and changed generation correctly returned ACK_UNAVAILABLE.
This proves a local authorization-condition omission; it does not prove Telegram will let a removed
member generate a new callback. A queued pre-loss callback or return before revalidation must be
covered by the chosen policy rather than relying solely on client behavior.

Legacy `scheduling/delivery.py:434` rejects superseded schedules. Hub records receipt per immutable
SENT dispatch; a newer changed schedule does not invalidate an older button in this guard.
**PRODUCT DECISION NEEDED:** should acknowledgement mean historical message receipt or acceptance
of the current operational schedule? Recommend current available binding and latest applicable
schedule for operational acceptance, preserving older history. Do not silently reinterpret existing
receipts. No fix or migration was made here.

### E7. Human accounting workflow and date semantics

`components/accounting.tsx` is mounted by the real technician detail route. Overview reads
`/accounting/current`; Daily/Weekly select dates and render underlying facts and totals; refresh
re-reads PG. `accounting/service.py` joins current revisions in a read-only consistent snapshot;
`domain.py` calculates Decimal gross, separate expenses, payments, reviews, maintenance and closer
counts. No net, commission, technician pay, payout or settlement is evidenced or inferred.
A technician can submit facts but cannot navigate a personal accounting dashboard or request a
Daily Telegram summary. An external spreadsheet is not a replacement for that missing workflow.

Date normalization was deliberate: Work Reports use the frozen job's operational date; Expenses
use submission-local accounting date. Legacy Daily selected report submission-local date. Calendar
schedule time uses the assigned calendar zone, while accounting Today uses technician accounting
zone. These are explicit Stage 3/7 choices, not arithmetic corruption. Use matching intended TEST
zones initially and include a midnight/date-boundary acceptance case; do not assume all 'today'
labels identify the same date when zones differ.

### E8-E9. Calendar source and report write-back decision

`google_calendar/router.py`/`service.py` handle OAuth, discovery/reconciliation and reconnect;
`calendars/service.py` assigns; `calendar_events/service.py:read_schedule` calls
`google_calendar/provider.py:list_events`. `google_calendar/types.py:4` requests events.readonly.
The job picker is a live read projection, not a first-party booking/calendar database. It needs
provider availability to obtain choices; already selected report facts can submit without rereading
Google. No event create/update/delete/report-description write exists in the provider interface.

Legacy `reports/delivery.py:123` uses `replace_managed_report_block` against a managed visit's Google
mapping, preserving other description text. Hub Stage 5 explicitly deferred this output; no final
permanent-removal decision is evidenced. Approve either a continued read-only pilot with manager
Accounting as the result surface or a separately designed narrow write-back with consent, identity,
conflict and retry policy. Neither is implemented by this audit.

Another material parity difference is job eligibility: legacy reportable entities are managed
WorkOrderVisits and REDO visits remain reportable (`legacy/docs/WORK_REPORTS.md`). Hub reuses the
explicit Stage 3 title filter, which excludes redo/fake/cancel/reschedule titles, all-day events,
and starts outside 08:00-22:00 (`calendar_events/domain.py:JobEventFilter`). It has no managed/external
visit distinction or manual unlisted report path. Stage 5 explicitly accepted that projection.
This is a documented architecture/eligibility normalization, not authority to port Work Orders.
Product should confirm whether a real redo job must be reportable before operational pilot use.

### E10. Manager detail regression across stages

`git show 41b5e22 -- apps/web/src/app/(workspace)/technicians/[id]/page.tsx` shows Stage 7 replacing
both `<WorkReports>` and `<Expenses>` with `<Accounting>`. A scan of production TSX finds no remaining
imports or JSX callers of either old panel. Their standalone component tests do not prove route
reachability. The preserved panels show technician-at-submission and submission timestamp; the
reachable Accounting fact cards at `accounting.tsx:83` do not. Accounting DTOs include submitted_at
but the cards omit it; report/expense fact DTOs do not carry saved technician-name attribution.
The read APIs still return the old detail data, so this is lost human access, not erased records.

Replacing the quadrant is intentional; losing historical attribution/time and direct detail access
has no evidenced policy approval and contradicts the Stage 5/6 promised read-only detail workflow.
Classify that **specific capability loss** as ACCIDENTALLY DROPPED (intent inferred, reachability
confirmed), not all manager visibility. Recommend a reachable detail action in Accounting, or another
approved equivalent, and one route-level navigation regression in a later implementation task.

### E11-E12. Outputs and their human responsibilities

`accounting.tsx:183` downloads Individual/All Tech via `accounting/xlsx_router.py`; projection and
shared XLSX renderer produce a selected-week artifact, without provider calls or business formulas.
All Tech download exists even though there is no separate company-wide web accounting dashboard.

`accounting-mirror.tsx` exposes config/replace/enable/disable/remove/sync/status/open.
`accounting_mirrors/service.py:103` is called by both submission services in their transaction and
coalesces enabled Individual and All Tech targets for the business week. `worker.py` renders current
canonical facts and writes through `provider.py`; generation/claim guards prevent stale completion.
Configuration alone does not backfill historical weeks. The manager explicitly syncs those weeks,
creates distinct existing target spreadsheets, grants Sheets access, and controls Google sharing.
Failure or manual edits in the owned range cannot change PG facts; manual edits there are overwritten.
No workflow auto-shares with technicians, imports spreadsheet corrections or settles payments. Those
are not failures of the implemented projection path. TD-033 remains live-unverified.

### E13. Scope, deferrals and documentation drift

Current `STAGE1_SCOPE.md` lists planned Daily/Receipt labels, but later scope excludes their
implementation. Stage 5/6 inventories defer corrections and post-save broadcasts; Stage 7 excludes
Telegram Daily delivery; TECH_DEBT's current disposition keeps Contracts/GPS outside the pilot.
Legacy `/receipt` -> ServiceContract -> PDF -> work group is real legacy functionality, deliberately
not migrated. `packages/contracts` contains generated API schemas/transport, not service contracts.
Legacy custom payment/review catalogs and broader employee roles are outside Hub's fixed-category,
manager-only approval. Future CRM/first-party Calendar/GPS/AI work is not authorized by this audit.
Google Forms/Sheets-as-intake and Discord were deliberately removed by migration principles.

Historical documents still contain statements such as 'accounting future', old panel availability,
and earlier blocker counts. Use their dated stage scope for provenance, not as current certification.
Current `PILOT_BLOCKER_MATRIX.md` has nine remaining operational/live gates. This audit changes no
TECH_DEBT status and claims no new live evidence.

## Prioritized gap list

### P0 - before continuing the affected live TEST acceptance

1. **Fix or explicitly settle unavailable-binding schedule acknowledgements before TD-028 ack tests.**
   Recommended fix: reject new acknowledgements after known availability loss and before revalidation,
   preserving already-recorded history. Cover loss, rejoin-before-revalidation and queued callback
   order. Settle latest-only versus historical-receipt policy and test an old button after a changed
   schedule. Current code must not be accepted as legacy latest-schedule confirmation.
2. **Approve a single end-to-end acceptance contract before claiming workflow parity.** Record whether
   current TEST acceptance is limited to intake -> browser receipt -> manager Accounting, or includes
   report/expense group publication, Daily and technician-requested schedules. Recommended narrow
   provider acceptance can proceed with these explicitly excluded; full group-workflow acceptance
   cannot pass until missing links are implemented. Do not add dead commands as a workaround. Resolve
   Calendar write-back as read-only-for-pilot versus separately approved future work; no write consent
   or mutation should be introduced just to satisfy an ambiguous checklist.
3. **Complete the existing deployment entry gates for the actual TEST release.** TD-012/017/025/029
   still require deployed TLS/origins, managed secrets/recovery, monitored worker/backlog and alert
   ownership evidence. This source audit cannot establish those from historical local tests or Render
   commits. Retain the existing dedicated-resource and stop rules. No infrastructure change is
   proposed by this audit.

These are scoped gates: a schedule acknowledgement defect does not erase the implemented onboarding
path or by itself forbid a separately approved isolated OAuth/onboarding probe. It does prevent a
clean full schedule/parity acceptance. Do not turn intentionally deferred Contracts into a P0.

### P1 - before a one-technician operational pilot

- Restore reachable manager submission details [E10], or approve an equivalent view that preserves
  saved attribution/time. Compare a form receipt to the actual manager route, not an isolated panel.
- Implement report/expense -> Work Group delivery if the stated shared-results channel remains a
  pilot requirement; include durable status, recovery, actor/generation checks and appropriate private
  completion status. Otherwise explicitly narrow the pilot and assign a manual communication owner.
- Decide and, if required, implement `/daily`'s two-message group workflow and standalone `/tomorrow`.
  Manager totals plus manager schedule send do not satisfy either technician action.
- Approve correction/void handling: either a separately scoped audited workflow or a TEST-only
  stop/review rule for bad submissions. Do not bypass immutable history with SQL or spreadsheet edits.
- Confirm redo/unlisted-job eligibility, calendar/accounting zone choices and group membership
  limitations. Resolve any required changes separately before using real operational cases.
- Complete live TD-022/027/028/030/033 on the approved narrow release. Verify Menu, mobile form receipts,
  actual manager visibility, removed-membership behavior, schedule ack and both Sheets outputs;
  compare XLSX/Sheets with canonical Accounting. Local source presence is not a live PASS.

### P2 - intentionally future product work

Receipt/service Contracts/PDFs, GPS/Moto Watchdog, CRM/first-party Calendar/AI, broader employee roles,
custom financial catalogs, commissions/payroll/payout, application-managed attachments and larger
company-wide finance UX remain separate product scope. Calendar report write-back belongs here only
if the owner explicitly defers it; its permanent removal is not assumed. Correcting missing pilot
links must not expand into these domains.

## Lightweight verification and preservation

- Verified clean current `main`, exact HEAD and recent Git history. Inspected Stage 5/6/7/9 scope,
  parity inventories, current operational/acceptance docs, application producers/consumers and the
  authoritative read-only legacy sources. Git history proves the Stage 7 panel replacement.
- Ran eight no-import/no-network AST/branch probes: exact two BotCommand values; zero production
  import/JSX references for each detail panel; five executions of the source `_acknowledge` function
  with synthetic query/context-manager doubles. Results: AVAILABLE/UNAVAILABLE/REVALIDATION_REQUIRED
  with matching identity/generation -> ACKNOWLEDGED; changed generation/wrong actor -> ACK_UNAVAILABLE.
  These are bounded structural/branch checks, not PostgreSQL, transport or concurrency acceptance.
- Presence/absence tracing checked transport allowlist, submit callers, outbox producers, accounting
  readers, mirror enqueue/worker paths and actual page composition. No claim rests on a keyword match
  or existence of an unmounted component alone. Existing tests were read; the historical regression
  totals were not presented as a new run. No full suite, migrations, browser login or provider calls.
- Only this audit document is changed. No application/schema/generated contracts/Render configuration
  changes; no normal DB/manager/calendar reads or writes, Docker/volume operations, secret reads,
  Google/Telegram calls, push or deployment. Preservation is by non-interaction, not a new DB checksum.
- Documentation-only diff/whitespace validation precedes commit. Repository history includes dedicated
  documentation commits; requested message: `docs: audit end-to-end workflow parity`.

**PILOT READY: NO.** Nine previously open local/live gates remain, and the workflow decisions and
specific gaps above must be resolved or explicitly accepted within a narrower pilot scope. This audit
neither closes those debts nor implements missing product workflows.
