# Stage 1 verification

Verified locally on Windows on September 16, 2026 (UTC runs continued September 17), using PostgreSQL 18.6, Python 3.13, Node 24, Next 16.3.5, React 19.3 and the repository's existing lockfiles. Stage 0 starting HEAD was personally inspected: `f10509369879df4ed6e0ab757e0887779f6f7129`, branch `codex/stage0-foundation`, clean working tree. Stage 1 branch: `codex/stage1-telegram-onboarding`. No push.

## Implemented versus verified

**Implemented:** manager authentication; secure private/group invitations and explicit approvals; generation/conflict/lifecycle safeguards; minimal audit; real optional Telegram adapter/worker; durable onboarding/test delivery; profile dialogs and generated contracts.

**Automatically verified with fakes:** 101 backend PostgreSQL tests, 14 frontend tests, two native browser flows, and the same two flows against production API/web images with a separate PostgreSQL database. No SQLite or mocked business backend was used. The only fake boundary is the Telegram provider. Real adapter startup/error behavior is inspected/tested without constructing a network-enabled Telegram bot.

**Not yet live-verified:** actual Telegram clients, permissions UI, real bot credentials, live messages, real group migrations and provider-specific network behavior. Follow the dedicated TEST-bot runbook; no existing operational bot was used. This is not production security certification.

## Results

| Check                                                                | Result                                               |
| -------------------------------------------------------------------- | ---------------------------------------------------- |
| Backend integration, auth, PostgreSQL concurrency, worker and outbox | 101 passed                                           |
| Frontend components                                                  | 14 passed, no unhandled errors                       |
| Playwright native development (3001/8001/test DB 5437)               | 2 passed                                             |
| Playwright production containers (3002/test DB 5438)                 | 2 passed                                             |
| Production Next build and strict TypeScript                          | Passed                                               |
| ESLint, Ruff lint/format, Prettier                                   | Passed after fixes                                   |
| OpenAPI snapshot and generated TypeScript refresh comparison         | Passed                                               |
| Fresh DB Alembic upgrade, metadata drift                             | Passed                                               |
| Stage 0 fixture → Stage 1 → Stage 0 → Stage 1 preservation           | Passed                                               |
| Default and E2E Compose configuration, API/web image builds, startup | Passed                                               |
| Default startup excludes Telegram worker                             | Confirmed                                            |
| Disabled worker CLI                                                  | “Telegram is disabled. No provider was initialized.” |
| Git-visible secret-pattern scan and `git diff --check`               | Passed, no findings/errors                           |

Backend test output included three python-telegram-bot deprecation warnings about a future `retry_after` timedelta type. The adapter handles integer and timedelta forms; Compose opts into the timedelta form. Browser/build tools emitted environment/install-script advisory notices, not failures. No dependency downgrade was used to obtain passing checks.

An initial model-registration omission produced an incomplete migration; it was detected against the disposable test DB and corrected with an additional additive revision before development upgrade. A timing-sensitive fake delivery test exposed a host/DB clock comparison at queue availability; eligibility now uses the DB clock. A mocked frontend replacement response was corrected to use its actual contract. All affected checks were rerun successfully. These are resolved issues, not skipped checks.

## Exact native commands

Run from `C:HVAC_TECHNICIAN_HUB`, after dependency setup in README. Do not run suites concurrently against the same test DB.

```powershell
$env:Path = 'C:Program Files
odejs;C:Program FilesDockerDocker
esourcesin;' + $env:Path
docker compose --profile test up -d --wait test-db
..venvScriptspython.exe scripts/validate_migrations.py
..venvScriptspython.exe -m pytest apps/api/tests -q --tb=short
..venvScripts
uff.exe check apps/api scripts
..venvScripts
uff.exe format --check apps/api scripts
..venvScriptspython.exe scripts/check_contracts.py
..venvScriptspython.exe -m hub.export_contracts
npm.cmd run contracts:generate
npm.cmd test
npm.cmd run lint
npm.cmd run format:check
npm.cmd run build
npm.cmd run typecheck
npm.cmd run test:e2e
..venvScriptspython.exe scripts/scan_secrets.py
git diff --check
```

`powershell -ExecutionPolicy Bypass -File scripts/verify.ps1` provides the sequential native checks. It also installs Chromium if needed. Browser installation/dependency downloads are not provider calls. A fresh checkout needs the Python editable package and npm dependencies described in README.

The migration script refuses any database name except `technician_hub_test` on its local allowlist. It tests a fresh schema and seeds fictional Stage 0 technician/calendar/assignment/Telegram/GPS rows before upgrade; their UUIDs, assignment and signed IDs survive downgrade/upgrade. **It must never target the user's development DB.** No destructive migration check ran there.

Default development Compose was upgraded only forward to `4344e0e76774`. Row counts were unchanged before/after: technicians 0, calendars 3, assignments 0, Telegram bindings 0, GPS bindings 0. No production manager or technician was auto-created. Temporary test managers use fresh random passwords delivered over subprocess stdin and are deleted after browser tests.

## Exact production-container commands

```powershell
cd C:HVAC_TECHNICIAN_HUB
$env:TELEGRAM_MODE = 'disabled'
docker compose config --quiet
docker compose build api web
docker compose up -d --wait
docker compose ps --services --status running
docker compose exec -T api python -m hub.telegram.worker
docker compose -f compose.e2e.yaml config --quiet
docker compose -f compose.e2e.yaml up -d --wait
$env:E2E_BASE_URL = 'http://127.0.0.1:3002'
$env:TEST_DATABASE_URL = 'postgresql+asyncpg://hub:hub_test_only@127.0.0.1:5438/technician_hub_test'
npm.cmd run test:e2e
Remove-Item Env:E2E_BASE_URL, Env:TEST_DATABASE_URL
# Stops only the isolated, tmpfs-backed browser-test stack:
docker compose -f compose.e2e.yaml down
```

The E2E stack has no Telegram worker, no token and no persistent development volume. The Python harness checks the exact isolated database and only invokes injected fake-provider services. It is not an HTTP endpoint. The real browser signs in, creates a technician, issues private/group invitations, observes candidates, approves each, confirms a group test, verifies SENT, independently disconnects group, deletes after the countdown, and signs out. The other flow preserves profile/calendar CRUD and assignment behavior.

Visual inspection used an ignored full-page screenshot with fictional data after approval; separate connection states and delivery outcomes fit the existing profile panel and 2×2 desktop layout. QR rendering is local SVG. Test traces are disabled to avoid retaining credentials or invitation links.

## Coverage highlights and limits

Auth covers unauthenticated business denial, cookie flags, hash-only storage, login/logout/rotation, expiry/revocation, CSRF and hostile Origin, generic failures, throttling and no default-account bypass. Onboarding covers wrong purpose/context, missing username, bot/anonymous rejection, simultaneous claims, competing ownership approvals, stale generations, expiry/revoke/regenerate, rejected replacement preserving identity, group checks/retry and migration conflict. Lifecycle covers inactive/deleted profiles, late updates, independent disconnect, blocking/access loss, private-change group suspension, deletion cascades, and a stale membership update waiting behind group replacement.

Worker tests cover exclusive poller locking, webhook/identity/polling-conflict refusal, durable offset ordering, interruption/restart/deduplication, bounded timeout/rate-limit behavior, UNKNOWN sends without replay, notifications failing independently of approval, and send/deletion serialization. A fake provider asserts no idle SQL transaction is held during send. Frontend tests cover login, invitation memory/copy/local QR, approval/rejection, independent states, replacement confirmation, hidden/unmounted polling and existing deletion safeguards.

The secret scanner examines tracked and untracked Git-visible files, not ignored credential files or unrelated projects. It detects selected common patterns and is not a comprehensive secret-discovery guarantee. No credentials were searched for. No live Telegram, Google, Moto Watchdog, Discord, email or SMS calls, public tunnels, deployments or pushes occurred. `C:HVAC_TECH_CODEX` and `C:MotoWatchdogProbe` were untouched.

The next manual work is only the separate TEST-bot procedure in [TELEGRAM_ONBOARDING.md](TELEGRAM_ONBOARDING.md#later-manual-test--not-performed-in-this-coding-stage). Stage 1 stops here; Calendar integration, reports and GPS are not started.
