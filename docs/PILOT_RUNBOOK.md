# One-technician pilot runbook

**Current release status: PILOT READY — NO.** Do not start the real pilot until the open items in
`PILOT_BLOCKER_MATRIX.md` are satisfied, including dedicated TEST provider acceptance and approved
policies for sensitive fields, audit/retention, abuse budgets, images, credentials, and deployment.

## Before the pilot

1. Use a reviewed release commit and clean build. Store the commit in `RELEASE_COMMIT`.
2. Provision unique database credentials, external Google and schedule encryption keys, and a bot
   token in the deployment secret store. Keep keys separate from database backups.
3. Put the Web behind the approved HTTPS proxy. Set secure cookies and exact HTTPS origins.
4. Run `python -m hub.ops.cli preflight`; do not continue on any `BLOCK`.
5. Run `python -m hub.ops.cli queues` and confirm required workers are `RUNNING`, not merely present.
6. Run `python -m hub.ops.cli fingerprint` and store the opaque output in the private change record.
7. Create a private backup with `powershell -File scripts/backup-postgres.ps1 -OutputDirectory <private-path>`;
   verify its SHA-256 manifest and latest isolated restore-drill evidence.
8. Complete the dedicated TEST provider runbook and link sanitized acceptance records.

## Technician onboarding

Create one fictional/test-approved technician first. Set the active status and explicit IANA
accounting timezone. Do not enter a real driver license or SSN last four while TD-011 is open.
Assign exactly one available calendar. Complete private Telegram onboarding and, only when schedule
delivery is enabled, the work group. For a Google calendar, confirm current connection and event-read
scope. The API checklist must show `Ready for Pilot`; an optional mirror may remain `OPTIONAL`.

## Daily operation

At the start of day, inspect Operations Health and queue counts. Confirm the technician identity,
calendar, timezone, Telegram destination, and today's fictional/approved jobs. During work, issue
short-lived Work Report or Expense links only to the intended TEST private chat. Treat the links as
transferable bearer capabilities: do not forward them, and revoke/reconnect the binding after a
suspected leak. Check the submitted record and canonical daily accounting.

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
- DL/SSN fields are plaintext and must remain empty for the pilot while TD-011 is open.
- External profile images need an approved privacy/CSP policy.
- XLSX and Google row heights approximate unusually long wrapped text; full values remain stored.
- Contracts and GPS are outside the current product and are not readiness requirements.
