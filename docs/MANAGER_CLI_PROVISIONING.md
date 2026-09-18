# Manager CLI provisioning blocker — 2026-09-18

Branch: `codex/stage5-work-reports-quality-audit`, created from clean
`e86279ef0df1cd4bda4026de59d7db4a93a9eee0`. The earlier discrepancy investigation
stopped before branch creation; this task created the requested branch. This is a
scoped provisioning fix, not completion of the Stage 5 Work Report audit.

## Confirmed root cause and severity

The user confirmed that the password for the reported failed attempt was shorter
than 14 characters. The original `create_manager` raised `ValueError` in its length
check, **before hashing, INSERT, audit or commit**. CLI `main()` caught every
`Exception` and replaced it with the same generic “Operation failed” message.
The password value was never requested, read, logged or reproduced.

The account was not created by that failed attempt. Docker's generic suggestion
was not the cause. This is a **MEDIUM diagnostic/coverage defect**, not a reproduced
CRITICAL/HIGH authentication bypass, data-loss defect or hashing outage. The actual
password policy was already documented correctly, but failure feedback was not
actionable. The fix preserves the policy.

Historical disappearance: **UNRESOLVED / INSUFFICIENT EVIDENCE** for any distinct
earlier attempt. The confirmed current short-password failure must not be applied
retroactively to an unrecorded earlier success/failure. Prior shell history showed
the documented command, but did not record its result; no account success receipt
or subsequent successful sign-in was available. No claim of deleted manager data
is made. No real local manager has been created automatically.

## Environment and database evidence

- Compose project `technician-hub`, config `C:\HVAC_TECHNICIAN_HUB\compose.yaml`.
- Normal API uses asyncpg, host `db`, port 5432, database `technician_hub`.
  Connection credentials were not printed.
- Database container `technician-hub-db-1` mounts retained volume
  `technician-hub_postgres_data` at `/var/lib/postgresql`.
- API/database health and Compose configuration passed; Google/Telegram disabled.
- Before investigation: managers 0, sessions 0, audit events 0; `manager` absent in
  both active/inactive states.
- Live auth columns, lengths, timestamps/defaults, username uniqueness, audit FK
  and INSERT privileges match the ORM/migrations. No custom auth-table triggers.
- Migration head `e5f509180001`; zero Alembic drift. No migration was required.
- No normal database INSERT/DELETE/UPDATE/reset was performed. Only the API image
  was refreshed after isolated verification; normal database container/volume were
  not restarted/recreated. Counts remain unchanged.

## Exact flow and policies

Argparse accepts create-manager/revoke-sessions and required username. Create
requires an interactive stdin, reads two hidden getpass values, rejects mismatch,
then runs the async service using the **same Settings database URL as the API**.
The service trims/lowercases username, checks normalized length 1–100, checks
password length 14–128, hashes with Argon2id in a thread pool, flushes Manager,
adds `manager.created`, and commits both together. Success prints only after
commit; the CLI closes its async session and disposes its engine.

`manager` is valid; no reserved-name rule exists. Names are unique regardless of
active status. There is no additional username character whitelist in the service;
normal PostgreSQL text restrictions still apply. Password length is Python Unicode
character count, not encoded byte count. No uppercase, lowercase, digit, symbol,
username-exclusion or common-password rule exists. Whitespace is preserved. Tests
cover both length boundaries, lowercase-only, Unicode and whitespace values. This
describes compatibility, not a recommendation to choose a weak password.

## Implementation changes

- Distinct safe InvalidManagerUsername/InvalidManagerPassword exception types.
- Allowlisted CLI error codes/messages for policy, duplicate username (including
  inactive), missing manager, hashing, configuration, schema and database errors.
- Unexpected failures retain a safe generic code. Arbitrary exceptions, SQL
  parameters, traceback locals and environment values are never printed.
- CLI engine now hides SQL parameter values as an additional diagnostic safeguard.
- No speculative dependency changes, manual hashes, password arguments, test
  endpoint, seed password, authorization bypass or normal-account mutation.

## Fresh-image and test-gap findings

Before the fix, both service and actual Linux pseudo-terminal CLI provisioning
succeeded using generated compliant credentials in isolated PostgreSQL. The
Argon2 hash/verify round trip also passed in the current image. Image Python is
3.13.15. Relevant native/container versions match the lock:
argon2-cffi 25.1.0, bindings 26.1.0, SQLAlchemy 2.0.54, asyncpg 0.31.0,
greenlet 3.5.6, AnyIO 4.15.1, cryptography 50.0.1. The CLI uses stdlib argparse and
getpass. No fresh-image dependency regression was reproduced.

Existing auth fixtures called `create_manager` directly with generated valid
credentials. They did use real PostgreSQL and hashing, but bypassed interactive
CLI prompts and its generic exception handler. New subprocess tests exercise
`cli.main()` with test-side prompt substitution; Linux Docker also exercises actual
getpass in a fresh real PTY process. No production test switch was introduced.

Coverage includes success + normal API login, 14/128 boundaries, too short/long,
mismatch, invalid username, case-normalized duplicate/inactive duplicate, concurrent
creation, database failure, hashing/unexpected exceptions containing a synthetic
secret, rollback after audit failure, noninteractive refusal, exit codes and no
secret echo. One successful creation produces exactly one manager and one safe
audit event; failed attempts leave neither partial manager nor audit/session state.

## Verification

- Native PostgreSQL CLI/auth/audit/Telegram-security selection: **110 passed,
  2 skipped** in 87.53 seconds. The skips are POSIX terminal cases run in Docker.
- Final Docker CLI + auth suite: **36 passed**, no warnings. Both real hidden
  terminal cases (valid and short password) passed in the rebuilt API image.
- Synthetic CLI account authenticated through the actual Next.js web proxy,
  survived isolated PostgreSQL + API restarts on a dedicated named test volume,
  then authenticated again using a fresh browser-equivalent HTTP client.
- The first isolated restart probe started API migration before PostgreSQL was
  ready (`CannotConnectNowError`). The harness was corrected to wait for database
  health before API startup, then the full persistence probe passed. This was test
  orchestration, not the user's password rejection or a data-loss finding.
- Fresh isolated startup/migration and rebuilt normal API are healthy; both
  schemas report `e5f509180001` and no new upgrade operations. Normal managers,
  sessions and audits remain **0 / 0 / 0**, with the same retained database volume.
- Ruff lint passed; all 125 Python files formatted; changed Markdown formatting
  passed; Git whitespace check passed. Secret-pattern scan: **236 files, 0 findings**.
  No frontend code changed, so frontend rebuild/TypeScript were not required for
  this scoped blocker. The broader Stage 5 verification remains a separate task.

## User action

Run from `C:\HVAC_TECHNICIAN_HUB`:

```powershell
docker compose exec api python -m hub.auth.cli create-manager --username manager
```

Choose your own unique password/passphrase of **14–128 characters**, type it twice
at the hidden prompts, and wait for the explicit success message. Then sign in at
`http://localhost:3000`. Never send the password to an agent or put it in command
arguments. If a safe error code is returned, share only that code/message.

Provisioning blocker resolution permits the existing Stage 5 audit to resume at
section 3; it does not close TD-030/031 or any previous pilot/production gate.
No volumes were deleted, nothing pushed, no live providers contacted, no Stage 6.
