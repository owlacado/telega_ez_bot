# One-technician pilot runbook

For the proposed single-Web/single-worker Render deployment, use `RENDER_DEPLOYMENT.md` for the
specific network, secret, migration, manager-provisioning, and health commands. Its Render-managed
TEST database is separate from the local Compose database. The selected deployment still needs
the operational controls below and all live TEST-provider acceptance before pilot readiness.

**Current release status: PILOT READY — NO.** Approved application policies are implemented. Do not
start the pilot until the nine remaining items in `PILOT_BLOCKER_MATRIX.md` are satisfied: four
selected-deployment operational controls and five dedicated live TEST-provider acceptances.

## Before the pilot

1. Verify the approved choices in `PILOT_POLICY_DECISIONS.md` and the independent evidence in
   `AUDIT_PILOT_POLICY_IMPLEMENTATION.md`.
2. Use a reviewed release commit and clean build. Store the commit in `RELEASE_COMMIT`; verify the
   database reports the single expected migration head `fea610060001`.
3. Instantiate and record the remote TEST deployment contract from `PILOT_ARCHITECTURE.md`: one
   HTTPS proxy, private application network, replaced forwarding headers, exact trusted proxy IP,
   request limits, exact HTTPS origin, secure cookie, and direct-API firewall.
4. Provision unique database credentials, Google client secret, Google credential key, schedule
   payload key, and Telegram token in the deployment secret store. For Compose, mount the Telegram
   token as a read-only file; on Render, supply `TELEGRAM_BOT_TOKEN` as a managed secret environment
   variable. Grant only the service identity and named recovery custodians access. Keep the
   two encryption keys and recovery copies outside the database backup system.
5. Run `python scripts/verify_pilot_key_recovery.py`. It must report PASS and must never receive or
   print deployed keys. Rehearse the deployed secret-store recovery procedure with newly generated
   synthetic values: stop dependent workers, back up the synthetic DB, remove runtime access,
   restore the same value, verify recovery, replace it, and verify the old value fails closed.
6. Run `python -m hub.ops.cli preflight`; do not continue on any `BLOCK`.
7. Schedule `python -m hub.ops.cli queues --require-pass` at least once per minute and route nonzero
   exit to the named pilot operator. Confirm required workers are `RUNNING`, not merely present. The
   strict exit covers aggregate WARN/BLOCK; the scheduler must also evaluate the JSON counts and
   compare consecutive samples for the numeric thresholds below.
8. Run `python -m hub.ops.cli fingerprint` and store the opaque output in the private change record.
9. For Compose, create a private backup with `powershell -File scripts/backup-postgres.ps1 -OutputDirectory <private-path>`;
   use a directory whose ACL is limited to the backup operators, then verify its SHA-256 manifest
   and latest isolated restore-drill evidence. The script publishes a unique dump/manifest pair and
   refuses to overwrite an artifact. On Render, use its managed PostgreSQL backup/PITR and document
   the private isolated restore drill; do not point the Compose script at Render. The dump still
   contains business data and encrypted
   credentials, so ciphertext does not make it safe to distribute. The default rolling retention
   is 30 days; `-RetentionDays` may change it only through a recorded operational policy change.
10. Complete `PILOT_LIVE_ACCEPTANCE_PLAN.md` in order and link sanitized acceptance records.

The pilot alert route pages immediately for preflight/health BLOCK, two consecutive API health
failures 30 seconds apart, migration mismatch, any enabled worker MISSING/STALE/STOPPED/ERROR, any
FAILED or AMBIGUOUS queue row, backup/manifest/restore failure, PostgreSQL connection use at or above
80, disk free below 20%, or credential recovery failure. Warn for more than 5 pending rows, any
processing row present across two five-minute checks, provider retry delayed more than 15 minutes,
or mirror lag over 15 minutes. From ten minutes before through ten minutes after the schedule window,
an enabled schedule worker that is not RUNNING is an immediate page. These are one-technician TEST
thresholds; record any approved change before applying it.

## Technician onboarding

Create one fictional/test-approved technician first. Set the active status and explicit IANA
accounting timezone. The pilot UI/API do not accept driver license ID, SSN last four, or an external
profile image; generated initials are the only technician image representation.
Assign exactly one available calendar. Complete private Telegram onboarding and the work group required for report/expense activity. For a Google calendar, confirm current connection and event-read
scope. The API checklist must show `Ready for Pilot`; an optional mirror may remain `OPTIONAL`.

## Daily operation

At the start of day, inspect Operations Health and queue counts. Confirm the technician identity,
calendar, timezone, Telegram destination, and today's fictional/approved jobs. During work, issue
short-lived Work Report or Expense links only to the intended TEST private chat. Treat the links as
transferable bearer capabilities: do not forward them, and revoke/reconnect the binding after a
suspected leak. Check the submitted record and canonical daily accounting. Open Saved submissions
for saved attribution, revision and submission time. Verify the matching Work Group message and
Recent Telegram activity outcome; a browser receipt proves persistence, not Telegram delivery.
Review FAILED/CANCELLED/UNKNOWN with the operator. Never submit a duplicate expense to recover a
notification or manually reset an uncertain send. Repair/revalidate the group; replacement does
not backfill older activity. See PILOT_LIVE_ACCEPTANCE_PLAN.md for the controlled failure sequence.

Before schedule delivery, preview it, confirm the work group and day, and verify the schedule worker
is current. Never resend an `AMBIGUOUS` Telegram dispatch automatically; a manager must check the
chat and choose whether to create a new attempt. A stopped schedule worker delays sends, and a
whole-window outage may fail to reconstruct a missed historical automatic decision. Monitor before
and during the configured delivery window.

Google Sheets mirrors are optional. A failed or lagging mirror does not alter PostgreSQL accounting.
Use the existing manual resync action for deterministic Google writes after fixing authorization or
quota issues. Compare canonical accounting before treating a projection as current.

At end of day, inspect failed/ambiguous queues, the technician's daily/weekly accounting, audit
events, and provider status. Run the cleanup command first without `--apply`, then apply only the
reviewed bounded cleanup. Create and verify the scheduled private backup.

Application admission is independent of provider retry/send limits. Telegram allows 30 actions per
minute per sender, a 10-action/10-second sender burst, and 300 actions per minute globally. Google
allows 5 OAuth starts per 15 minutes per manager and 20 per hour globally; manual Calendar
scan/reconnect allows 6 per 10 minutes per manager and 30 per hour globally. Treat 429 responses as
an operational signal; do not increase a limit during an incident without recording the change.
Processed Telegram updates and cleared OAuth-attempt metadata have a seven-day bounded cleanup.

## Secret recovery and rotation

Never replace an encryption key merely to clear a preflight error. First stop every dependent
worker, capture queue state, make a private database backup, and verify the current recovery copy.
With the correct restored key, existing ciphertext must decrypt; with a wrong key it must remain
unreadable without mutation.

There is no unattended in-place credential rotation. For Google, while the old key is available,
disconnect the TEST account through the supported flow, preserve incident evidence for any failed
remote revocation, install the new key, restart, and deliberately reconnect/regrant. For schedule
payloads, stop delivery, require zero PENDING/PROCESSING rows, review every AMBIGUOUS row, retain the
old key for its approved recovery window, install the new key, and then restart. Never bulk-edit,
blank, or silently re-encrypt database ciphertext. A live Google revocation/reconnect still belongs
to TD-025 acceptance; the local synthetic rehearsal does not close it.

## Immediate stop conditions

Stop the pilot and preserve evidence for business-data corruption, duplicate financial records,
wrong technician identity, wrong schedule destination, unrecoverable provider credentials, database
integrity failure, or persistent provider ambiguity that requires operator review. Disable the
affected worker before investigation. Ordinary mirror lag alone is projection delay, not canonical
data corruption, unless it masks a separate PostgreSQL/accounting failure.

## Rollback and offboarding

Stop optional workers first. Preserve fingerprints and a backup before application rollback; never
run an automatic destructive downgrade. If migration rollback is unsafe, restore the prior release
against a compatible restored database in an isolated environment. For offboarding, deactivate the
technician, disable schedules/mirrors, disconnect provider bindings, revoke TEST grants, and retain
Work Reports, Expenses, revisions, and audit data under the approved policy. Do not bypass protected
business-record deletion constraints.

## Known limitations

- Provider acceptance remains unexecuted until the dedicated runbook is completed.
- Form links are short-lived, single-use, purpose/technician/generation-bound bearer capabilities,
  but deliberate transfer before use is possible.
- Google and Telegram are eventually consistent and cannot provide local database atomicity.
- Ambiguous Telegram sends require human review; blind retry can duplicate a message.
- Automatic schedule decisions can be missed across the whole decision window during long downtime.
- Production collection of DL/SSN remains prohibited until encryption/access policy is approved;
  the pilot API/UI and database guard reject new values.
- Production deletion, anonymization, and retention still require final legal/business policy.
- The Web `/login` probe checks only the Web process and static shell; use API and Operations Health
  to decide whether the application is usable.
- Run only one API and one replica of each enabled worker under the pilot connection budget.
- XLSX and Google row heights approximate unusually long wrapped text; full values remain stored.
- Contracts and GPS are outside the current product and are not readiness requirements.
