# Technician Hub

Stage 5 adds [technician Work Reports](docs/WORK_REPORTS.md): private `/report`,
secure mobile job selection/submission, immutable PostgreSQL history, and manager
read-only visibility. Technicians with report history must be deactivated rather
than permanently deleted. See [legacy parity](docs/LEGACY_WORK_REPORT_INVENTORY.md)
and [Stage 5 verification](docs/STAGE5_WORK_REPORT_VERIFICATION.md).

A local operations workspace built around the human technician. PostgreSQL owns identity; calendars and future provider connections attach to an immutable UUID.

**Stage 4 foundation: durable Telegram schedule delivery and acknowledgements, alongside audited calendar views, discovery, assignment and onboarding.** Manager business views require a manager session; Stage 5's three technician-form endpoints use separately scoped private capabilities. Google and Telegram default to disabled; the Telegram worker is an opt-in Compose profile. No provider credentials are needed for automated verification. This remains local-only; sensitive-field encryption, broader deployment hardening, and live provider validation are deferred. Use fictional profiles and do not enter real DL/SSN values.

Connect Telegram now creates a one-time invitation and binds automatically when the intended technician presses Start. Work-group linking uses a separate invitation and requires that same linked account to send the group command; ordinary bot membership is sufficient. Existing invitations retain their old manager-review policy after upgrade. See [the onboarding runbook](docs/TELEGRAM_ONBOARDING.md) for safe link handling, configuration, disconnect/reconnect behavior and the manual TEST-bot procedure, and [completion verification](docs/TELEGRAM_COMPLETION_VERIFICATION.md) for current evidence.

Google Calendar uses manager-initiated OAuth, encrypted offline credentials, complete manual CalendarList discovery, exclusion/restore, and atomic technician assignments. Discovery requests CalendarList read access. Managers can separately grant `calendar.events.readonly` for bounded on-demand jobs and schedule previews. Google event writes remain unavailable. Stage 4 adds explicit schedule Send/Resend and opt-in calendar-local automatic delivery through an encrypted durable dispatch queue. See [Stage 3 rules](docs/STAGE3_CALENDAR_EVENTS.md) and [verification](docs/STAGE3_CALENDAR_EVENTS_VERIFICATION.md). See [Google integration and safe TEST-account acceptance](docs/GOOGLE_CALENDAR_INTEGRATION.md) and [Stage 2 verification](docs/STAGE2_GOOGLE_CALENDAR_VERIFICATION.md). No real Google account is needed for automated tests.

## Quick start on Windows

Install Docker Desktop with Linux containers and start its engine. Open PowerShell:

```powershell
cd C:\HVAC_TECHNICIAN_HUB
docker compose up -d --build --wait
docker compose exec api python -m hub.auth.cli create-manager --username manager
```

The first run builds both apps, waits for PostgreSQL, and applies Alembic migrations automatically. No manual `.env` file is required for the local defaults.

- Application: <http://localhost:3000>
- API documentation: <http://localhost:8000/docs> (requires an authenticated session on the same hostname)
- Database-backed health: <http://localhost:8000/api/health>

The manager CLI prompts twice for a hidden password (14–128 characters). There is no default account/password and no public registration. Sign in at the application URL. To revoke sessions: `docker compose exec api python -m hub.auth.cli revoke-sessions --username manager`.

The password policy is length only: 14–128 Unicode characters, with whitespace
preserved; there are no hidden uppercase/number/symbol requirements. Prefer a long,
unique passphrase. Usernames are trimmed/lowercased and must then be 1–100
characters; `manager` is valid. Existing names, including inactive accounts, cannot
be recreated. A successful command explicitly prints `Manager created. Sign in
through the web application.` Do not assume an account exists merely because both
password prompts completed. Safe CLI errors distinguish `PASSWORD_POLICY`,
`USERNAME_EXISTS`, configuration, hashing and database failures without printing
passwords, hashes, connection URLs or raw exceptions. See the
[provisioning investigation](docs/MANAGER_CLI_PROVISIONING.md).

Optionally seed three clearly labeled fictional calendars:

```powershell
cd C:\HVAC_TECHNICIAN_HUB
docker compose exec api python -m hub.seed
```

The seed is idempotent, allowed only when `APP_ENV=development`, and creates no technicians, Telegram IDs, or GPS tokens. Add your first fictional technician in the UI.

To stop, press Ctrl+C or run `docker compose down`. The named PostgreSQL volume persists. **Do not add `-v` unless you intend to erase the development database.** After code changes, run `docker compose up --build`.

Copy `.env.example` to `.env` only if you need to customize ports or local credentials. All published ports bind to `127.0.0.1`. If changing credentials, use URL-safe characters or percent-encode credentials in the connection URL. The web-to-API proxy in Compose uses the internal service address; the browser stays on the same origin.

## Native development with hot reload

Prerequisites: Node.js 24 LTS, Python 3.13 (3.12+ supported), Docker Desktop. These are project-local installs; no global npm packages are required.

```powershell
cd C:\HVAC_TECHNICIAN_HUB
docker compose up -d db
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r apps/api/requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e apps/api
npm.cmd ci
.\.venv\Scripts\python.exe -m alembic -c apps/api/alembic.ini upgrade head
.\.venv\Scripts\python.exe -m hub.auth.cli create-manager --username manager
.\.venv\Scripts\python.exe -m hub.seed
.\.venv\Scripts\python.exe -m uvicorn hub.main:app --reload --host 127.0.0.1 --port 8000
```

In a second terminal at the repository root:

```powershell
npm.cmd run dev
```

Do not run Compose `api`/`web` on the same ports at the same time. Native API uses PostgreSQL on `127.0.0.1:5436`. Override `DATABASE_URL` for the API or `API_INTERNAL_URL` for the native Next.js proxy if needed. The proxy destination is captured during the production build.

If this terminal cannot locate Node or Docker credential helpers, reopen PowerShell after installing those applications, or set the PATH for this terminal:

```powershell
$env:Path = 'C:\Program Files\nodejs;C:\Program Files\Docker\Docker\resources\bin;' + $env:Path
```

## Verification

Install native dependencies as above, then:

```powershell
cd C:\HVAC_TECHNICIAN_HUB
powershell -ExecutionPolicy Bypass -File scripts/verify.ps1
```

The script starts a **separate, disposable** PostgreSQL test database on port 5437, runs migration round-trip and drift checks, backend integration tests, component tests, linting, formatting, strict TypeScript, the production build, the Playwright flow, Compose configuration, and whitespace checks. It stops on the first failure. Browser installation is a one-time setup download; test execution calls only localhost.

Tests never use SQLite. They refuse to truncate anything except a local database named `technician_hub_test`. Do not run backend and browser suites simultaneously against that database. Browser fixtures are fictional and removed after the smoke flow.

Individual commands:

```powershell
docker compose --profile test up -d --wait test-db
.\.venv\Scripts\python.exe scripts/validate_migrations.py
.\.venv\Scripts\python.exe -m pytest apps/api/tests -q
npm.cmd test
npm.cmd run lint
npm.cmd run typecheck
npm.cmd run format:check
.\.venv\Scripts\ruff.exe check apps/api
.\.venv\Scripts\ruff.exe format --check apps/api
npm.cmd run build
npx.cmd playwright install chromium
npm.cmd run test:e2e
docker compose config --quiet
git diff --check
```

Playwright starts an authenticated API on 8001 and Next.js on 3001. It uses random temporary manager credentials, a fake Google provider, and a stdin-only local fake Telegram harness, never a public simulation endpoint. Do not point these tests at the development database. Current production-image tests use an independent stack on 3005/5442; see [Stage 2 verification](docs/STAGE2_GOOGLE_CALENDAR_VERIFICATION.md).

## Structure and contracts

```text
apps/web/           Next.js App Router UI
apps/api/hub/       FastAPI: auth, audit, Telegram, Google Calendar, technicians, core
apps/api/migrations/  Alembic PostgreSQL migrations
packages/contracts/  OpenAPI snapshot and generated TypeScript API types
packages/shared/     Pure display helpers; no backend dependency
infrastructure/      Dockerfiles
scripts/             Local verification and migration validation
docs/                Architecture, scope, verification evidence
```

Pydantic schemas own API contracts. After changing them:

```powershell
.\.venv\Scripts\python.exe -m hub.export_contracts
npm.cmd run contracts:generate
npm.cmd run typecheck
```

Commit both the OpenAPI snapshot and generated types. Runtime requests are validated in FastAPI; generated TypeScript describes response and request shapes without importing frontend code into Python.

## Day-to-day behavior

- Dashboard shows database-derived counts and missing calendar, private Telegram, work group, and GPS connections. No fictional financial metrics.
- Technicians supports name search, horizontal identity cards, a quick add dialog, and persistent detail editing.
- Calendar selection saves immediately. One technician has at most one active primary calendar, and a calendar is assigned to at most one technician. Changing/unassigning preserves assignment history.
- Permanent deletion requires an exact `DELETE First Last` in the browser and a 10-second wait. The API independently requires `{ "confirmation": "DELETE" }`. It permanently deletes the technician and bindings, leaving local calendars intact.
- Google calendar removal requires confirmation of the current assignee and creates a local exclusion; scans preserve that exclusion until Restore. Assigned removal unassigns atomically and preserves history. Local demo deletion retains its separate confirmation/detach contract. No Google calendar is deleted.

Open a technician's **Connect Telegram** dialog, generate a link, review the claiming account, and explicitly approve it. Then connect and approve a separate work group. Replacement keeps the current identity until approval; replacing/disconnecting private access suspends group delivery until revalidation. Test messages require a selected approved destination and confirmation. Already delivered messages are not erased by local deletion.

Read [Stage 1 scope](docs/STAGE1_SCOPE.md), [onboarding and dedicated-test-bot runbook](docs/TELEGRAM_ONBOARDING.md), [security and privacy](docs/TELEGRAM_SECURITY.md), [architecture](docs/ARCHITECTURE.md), and [verification evidence](docs/STAGE1_VERIFICATION.md). [Stage 0 scope](docs/STAGE0_SCOPE.md) and [historical verification](docs/VERIFICATION.md) describe the starting foundation.

## Stage 4 schedule delivery

See [Schedule delivery](docs/SCHEDULE_DELIVERY.md) for the unified immutable dispatch path, dedicated
payload key, separate worker, calendar-local automatic delivery (OFF by default),
acknowledgement authorization, uncertainty recovery, retention, and dedicated TEST
acceptance runbook. The Telegram polling worker receives callbacks; the schedule
worker sends durable dispatches and evaluates automatic decisions. Neither starts
inside the web API. Stage 3 job filtering and wall-clock projection remain authoritative.

Stage 4 quality evidence: [verification and self-audit](docs/STAGE4_SCHEDULE_DELIVERY_VERIFICATION.md).

Independent Stage 5 audit: [Work Report integrity and verification](docs/AUDIT_STAGE5_WORK_REPORTS.md).

## Stage 6: technician expenses

Private Telegram **Expenses** opens the shared secure mobile form. PostgreSQL
stores expense facts and immutable revision 1; managers see a read-only list and
truthful expense-only daily totals. Set the technician's explicit **Accounting
timezone** in their profile first; existing profiles have no default. No receipt
upload, Google Form/Sheet mapping, corrections, payout or full accounting is added.
See [Expenses](docs/EXPENSES.md), [legacy evidence](docs/LEGACY_EXPENSE_INVENTORY.md),
and [verification](docs/STAGE6_EXPENSES_VERIFICATION.md).
