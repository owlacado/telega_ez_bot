# Technician Hub

A local operations workspace built around the human technician. PostgreSQL owns identity; calendars and future provider connections attach to an immutable UUID.

**Stage 1: secure Telegram onboarding.** All business data requires a manager session. Telegram defaults to disabled and its worker is an opt-in Compose profile. No provider credentials are needed for automated verification. This remains local-only; sensitive-field encryption, broader deployment hardening, and live Telegram validation are deferred. Use fictional profiles and do not enter real DL/SSN values.

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

Playwright starts an authenticated API on 8001 and Next.js on 3001. It uses random temporary manager credentials and a stdin-only local fake Telegram harness, never a public simulation endpoint. Do not point these tests at the development database. Production-image tests use an independent stack on 3002/5438; see [Stage 1 verification](docs/STAGE1_VERIFICATION.md).

## Structure and contracts

```text
apps/web/           Next.js App Router UI
apps/api/hub/       FastAPI: auth, audit, Telegram, technicians, calendars, core
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
- Calendar removal requires confirmation and an explicit detach flag when assigned. It removes only the Hub record; no Google calls exist. Historical assignments keep a name snapshot.

Open a technician's **Connect Telegram** dialog, generate a link, review the claiming account, and explicitly approve it. Then connect and approve a separate work group. Replacement keeps the current identity until approval; replacing/disconnecting private access suspends group delivery until revalidation. Test messages require a selected approved destination and confirmation. Already delivered messages are not erased by local deletion.

Read [Stage 1 scope](docs/STAGE1_SCOPE.md), [onboarding and dedicated-test-bot runbook](docs/TELEGRAM_ONBOARDING.md), [security and privacy](docs/TELEGRAM_SECURITY.md), [architecture](docs/ARCHITECTURE.md), and [verification evidence](docs/STAGE1_VERIFICATION.md). [Stage 0 scope](docs/STAGE0_SCOPE.md) and [historical verification](docs/VERIFICATION.md) describe the starting foundation.
