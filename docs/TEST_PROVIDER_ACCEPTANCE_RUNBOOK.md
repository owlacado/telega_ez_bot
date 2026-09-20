# Dedicated TEST provider acceptance runbook

Use only a dedicated TEST Google account/project, a dedicated TEST Telegram bot, dedicated TEST
private and group chats, a fictional technician, fictional calendar jobs, and a dedicated TEST
spreadsheet. Stop if any real customer, technician, chat, calendar, or spreadsheet is visible.

## Credential boundary

Configure secrets in the deployment secret store or private server files. Never paste a bot token,
OAuth client secret, refresh/access token, encryption key, authorization code, spreadsheet ID, or
chat ID into Git, documentation, screenshots, issue text, a Codex prompt, or test source. Keep the
database backup and the Google/schedule encryption keys in separate protected systems.

## Controlled sequence

1. Record the release commit, expected Alembic head, operators, TEST identities, and stop criteria.
2. Back up the normal database with `scripts/backup-postgres.ps1` and verify its private manifest.
3. Create one isolated fictional pilot technician with an explicit IANA accounting timezone.
4. Connect the dedicated TEST Telegram private chat; verify bot identity and one-time invitation.
5. Connect the dedicated TEST group; verify actor, member, send permission, removal, and revalidation.
6. Connect the dedicated TEST Google account with the intended Calendar scope and optional Sheets scope.
7. Scan CalendarList; verify primary/shared/hidden visibility, stable identity, exclusion, and rescan.
8. Read fictional events covering recurrence, cancellation, private fields, DST, empty day, and pagination.
9. Submit one fictional Work Report from the TEST mobile Telegram link; retry its receipt safely.
10. Submit one fictional Expense and verify timezone-normalized accounting.
11. Send one schedule; verify destination, HTML/length behavior, acknowledgement, late acknowledgement,
    removed membership, provider failure, and the manual decision for an ambiguous outcome.
12. Configure and sync one Individual TEST spreadsheet; verify values, owned range, formatting, retry,
    manual resync, revocation, and reconnect.
13. Configure and sync All Tech to a different TEST spreadsheet; verify deterministic tab identity and
    that targets cannot overwrite one another.
14. Compare UI, canonical accounting JSON, XLSX totals, and both Sheets projections.
15. Disconnect integrations and revoke TEST grants/token if ending the exercise. Delete a TEST chat,
    calendar, or spreadsheet only when it is dedicated to this exercise and the operator explicitly
    intends external deletion; otherwise only disconnect it. Delete disposable technician data only
    through supported rules, and retain sanitized evidence.

## Acceptance record

For each row in `TEST_PROVIDER_ACCEPTANCE_MATRIX.md`, record PASS/FAIL, release commit, browser/mobile
client versions, provider project/bot labels without IDs, UTC time, observed failure behavior, and a
sanitized evidence location. A failure leaves the corresponding debt OPEN. A fake or localhost-only
rerun cannot replace this record.
