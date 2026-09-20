# Dedicated TEST provider acceptance runbook

The authoritative minimal resource list, entry gate, ordered execution, stop conditions, and
evidence template are in `PILOT_LIVE_ACCEPTANCE_PLAN.md`. Use that plan as the operator checklist;
this document retains the credential boundary and a compact cross-check.

Use only a dedicated TEST Google account/project, a dedicated TEST Telegram bot, dedicated TEST
private and group chats, a fictional technician, fictional calendar jobs, and a dedicated TEST
spreadsheet. Stop if any real customer, technician, chat, calendar, or spreadsheet is visible.

## Credential boundary

Configure secrets in the deployment secret store or private server files. Never paste a bot token,
OAuth client secret, refresh/access token, encryption key, authorization code, spreadsheet ID, or
chat ID into Git, documentation, screenshots, issue text, a Codex prompt, or test source. Keep the
database backup and the Google/schedule encryption keys in separate protected systems.

## Controlled sequence

1. Pass the plan's policy, deployment, preflight, monitoring, backup, and fingerprint entry gate.
2. Complete private and group Telegram acceptance.
3. Complete Google OAuth, Calendar discovery, and event-read acceptance.
4. Complete mobile Work Report and Expense acceptance.
5. Complete combined schedule send and acknowledgement acceptance.
6. Complete Individual and All Tech mirror acceptance using different TEST spreadsheets.
7. Reconcile UI, canonical accounting, XLSX, and both Sheets projections; restart and verify recovery.
8. Record reviewed evidence, disconnect/revoke intentionally, and preserve required business/audit data.

## Acceptance record

For each row in `TEST_PROVIDER_ACCEPTANCE_MATRIX.md`, record PASS/FAIL, release commit, browser/mobile
client versions, provider project/bot labels without IDs, UTC time, observed failure behavior, and a
sanitized evidence location. A failure leaves the corresponding debt OPEN. A fake or localhost-only
rerun cannot replace this record.
