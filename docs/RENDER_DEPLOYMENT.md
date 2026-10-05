# Render deployment: one Web, one worker, one TEST PostgreSQL

This Blueprint is the base deployment for a controlled fictional-technician TEST pilot. It defines exactly one Docker Web service, one Docker Background Worker, and one new Render-managed PostgreSQL database in Oregon. It does not import or connect to the normal local database. Google, Telegram, and schedule delivery are disabled for the base deployment.

## Resource shape and resizing signals

The plan identifiers below are current Render Blueprint plan IDs. Keep one instance of each service during the pilot.

| Resource | Plan | Purpose | Can resize later? | Metric that justifies resizing |
| --- | --- | --- | --- | --- |
| `technician-hub-test-web` | `0.5c-512mb` (0.5 CPU, 512 MB) | Caddy, FastAPI, and the full Next.js runtime in one Web container | Yes | Sustained CPU or memory pressure, OOM/restarts, or login/API latency outside the pilot SLO after measuring the cause |
| `technician-hub-test-worker` | `0.5c-512mb` (0.5 CPU, 512 MB) | Supervises Telegram, schedule-delivery, and Google Sheets mirror children when enabled | Yes | Sustained CPU or memory pressure, restarts, growing durable backlog, stale heartbeat, or missed delivery/mirror SLA |
| `technician-hub-test-db` | `0.5c-1g` (0.5 CPU, 1 GB, persistent paid Postgres) | New private TEST system of record | Yes | Memory/CPU pressure, connection saturation, storage/IO pressure, or measured query latency |

Render also offers `0.1c-256mb` paid Postgres, but it is not the smallest **suitable** choice for this deployment. The documented single-replica connection budget can reach 75 regular connections plus temporary owners; 256 MB gives too little database-memory margin even though both small plans currently allow at most 100 connections. `0.5c-1g` is therefore the initial database plan. Review the Dashboard price before creation.

CRM, the first-party Calendar, and future LLM/RAG workloads can grow on this architecture. Do not split services before measurements justify it. The combined worker can be separated later if CPU, memory, backlog, heartbeat, or SLA evidence shows that one workload interferes with another.

## Process, TLS, and network boundary

Render terminates public HTTPS and forwards HTTP to the Web container. Only Caddy binds `0.0.0.0:$PORT` (Render defaults to `10000`). Caddy routes `/api`, `/api/*`, `/docs`, `/docs/*`, `/redoc`, `/redoc/*`, and `/openapi.json` to Uvicorn on `127.0.0.1:8000`; every application route goes to the Next.js standalone server on `127.0.0.1:3000`. FastAPI and Next.js do not bind the public port.

Caddy strips inbound `Forwarded`, `X-Forwarded-*`, and `X-Real-IP` values before either upstream. Uvicorn runs with `--no-proxy-headers`. The application uses the exact configured origin and Host allowlist instead of trusting those headers. `COOKIE_SECURE=true` makes the browser send authentication cookies only over the public Render HTTPS boundary; the internal HTTP hop does not weaken that browser policy. Caddy limits request bodies to 1 MB and applies 15-second request-header/body read timeouts.

The Web startup supervisor runs FastAPI, Next.js, and Caddy as independent child processes. An unexpected child exit fails the service. SIGTERM fans out to all children with the configured 60-second Render shutdown window. The Background Worker uses the same supervisor for the Telegram, schedule, and mirror workers. Disabled features create no child, so the initial worker remains alive without a crash loop. When features are later enabled, an unexpected child exit fails the worker so Render can restart it. Queue claims, leases, offsets, heartbeats, and retry state remain durable in PostgreSQL.

## Environment inventory

### Blueprint safe config

The `technician-hub-test-shared` Blueprint environment group links the same security-sensitive non-secret values to Web and Worker so they cannot drift independently:

- `APP_ENV=pilot`
- `APP_VERSION=0.3.0`
- `COOKIE_SECURE=true`
- `DEBUG=false`
- `ALLOW_FAKE_PROVIDERS=false`
- `TELEGRAM_MODE=disabled`
- `GOOGLE_MODE=disabled`
- `SCHEDULE_DELIVERY_ENABLED=false`

The worker alone receives `PTB_TIMEDELTA=true`. The Render entrypoint rejects fake modes, rejects `ALLOW_FAKE_PROVIDERS=true`, and rejects local/Compose/test database hosts on Render.

### Render-generated

- `RENDER_DATABASE_URL` is populated in both services from the new database's private `connectionString`.
- `RENDER_EXTERNAL_URL` is generated for the Web service. The Blueprint exposes this value as `PUBLIC_APP_ORIGIN` in both Web and Worker using `fromService`; no URL is guessed or typed twice.
- Render supplies `$PORT`, `RENDER_GIT_COMMIT`, and its other runtime metadata.
- The entrypoint derives `DATABASE_URL`, `RELEASE_COMMIT`, and exact `ALLOWED_ORIGINS`. When Google is later enabled, it derives `GOOGLE_OAUTH_REDIRECT_URI` as `${PUBLIC_APP_ORIGIN}/api/calendar-connections/google/callback` and rejects a conflicting callback.

`PUBLIC_APP_ORIGIN` is therefore the official full `https://...onrender.com` URL on the first Blueprint sync. It has no path or trailing slash and satisfies the existing exact-origin validation. If a custom domain is adopted later, treat that as a reviewed configuration change: update the canonical origin/callback design and redeploy both services rather than trusting forwarded headers.

### Initial manual values

**None.** The base Blueprint contains no `sync: false` variable. The new database credential, Web origin, port, and release commit all come from Render. Do not paste `.env`, a database URL, provider placeholders, or any secret into the Blueprint creation form. The fresh database intentionally contains no manager; create one only after migration as described below.

### Later live-TEST secrets

These values are deliberately absent from `render.yaml` and are not required while providers remain disabled:

| Feature | Variables required before activation |
| --- | --- |
| Dedicated TEST Telegram bot | `TELEGRAM_EXPECTED_BOT_ID`, `TELEGRAM_EXPECTED_BOT_USERNAME`, `TELEGRAM_BOT_TOKEN` |
| Dedicated TEST Google OAuth | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_CALENDAR_CREDENTIAL_ENCRYPTION_KEY` |
| TEST schedule delivery | `SCHEDULE_PAYLOAD_ENCRYPTION_KEY` plus enabled and valid Telegram/Google configuration |

After the base deployment passes, store those values in one Render secret environment group linked to both services. Keep recovery copies of encryption keys in the approved secret manager, outside PostgreSQL backups. Activate modes through a reviewed Blueprint change so Web and Worker move from `disabled` together. Real Google mode already fails static runtime configuration without OAuth credentials, encryption key, and the exact callback. Real Telegram cannot initialize without the configured bot identity and token, and preflight blocks a missing token source. Schedule delivery requires its encryption key, Telegram identity, and Google access. Use only dedicated TEST resources and no customer data.

## Database, migrations, and operator commands

The database is new, private, and managed by Render. `ipAllowList: []` prevents public database access. Both services consume its internal connection string; the entrypoint converts the Render `postgresql://` URL to SQLAlchemy's `postgresql+asyncpg://` form. Application images contain no PostgreSQL process or persistent business-data volume.

The Web service owns the release migration step:

1. Render creates the empty TEST database and injects its internal connection string.
2. After the Web image builds, Render runs `python -m hub.render_runtime migrate` as `preDeployCommand`.
3. That command runs `alembic upgrade head`. A nonzero migration exit stops the Web deployment before the new release receives traffic.
4. The Worker never runs migrations and should be left stopped or ignored until the first Web migration succeeds.
5. After the Web deploy succeeds, create the first manager interactively in the Web Shell:

   `python -m hub.render_runtime create-manager --username <test-manager-name>`

   The command prompts for a password; do not place the password in shell history. It does not seed a default account.
6. Run `python -m hub.render_runtime preflight` in the Web Shell. Require no `BLOCK`. A preflight run before manager creation is expected to block on `manager`.
7. Run `python -m hub.render_runtime queues` in the Worker Shell. With the base configuration, the provider workers must report `DISABLED`, not failed or stale.

Other operator commands are `python -m hub.render_runtime revoke-sessions --username <test-manager-name>` and a controlled rerun of `python -m hub.render_runtime migrate`. Every wrapper resolves and validates the Render database before invoking the underlying command.

## Exact first deployment steps

Stop after completing this base sequence. Do not configure Google or Telegram during it.

1. Open **Render Dashboard → New → Blueprint**.
2. Connect or select GitHub repository `owlacado/telega_ez_bot`.
3. Select branch `main` and the root `render.yaml`.
4. Review the preview. It must show exactly these three resources in `oregon`: Web `technician-hub-test-web`, Background Worker `technician-hub-test-worker`, and PostgreSQL `technician-hub-test-db`. The shared environment group is configuration, not an additional service.
5. Confirm the plans are Web `0.5c-512mb`, Worker `0.5c-512mb`, PostgreSQL `0.5c-1g`, with one Web and one Worker instance. Review the displayed monthly cost before approving creation.
6. Confirm the database is new, private, empty, and has no public allowlist. Do not import the local database.
7. The initial manual-value list must be empty. If Render prompts for a provider secret or `PUBLIC_APP_ORIGIN`, stop and recheck that the Blueprint is using the reviewed commit; do not enter placeholders.
8. Create the resources. Render generates the database credential and Web URL, wires `PUBLIC_APP_ORIGIN` to the Web `RENDER_EXTERNAL_URL` for both services, builds the images, runs the Web migration, and then starts the services.
9. In the Web deploy log, confirm the release commit is the reviewed 40-character commit and `python -m hub.render_runtime migrate` succeeded. If migration fails, stop and investigate; do not create a manager against a partial release.
10. Open `https://<assigned-web-host>/api/health` and require HTTP 200. Open `https://<assigned-web-host>/login` and require the login page. Do not infer aggregate health from `/login` alone.
11. Open the Web service **Shell** and run `python -m hub.render_runtime create-manager --username <test-manager-name>`. Enter a unique TEST password only at the hidden prompt.
12. In the same Web Shell run `python -m hub.render_runtime preflight`; require no `BLOCK` and confirm the schema head, database, release, and active manager checks pass. Provider-disabled entries may be warnings.
13. Open the Worker service **Shell** and run `python -m hub.render_runtime queues`; require the provider components to report `DISABLED`.
14. Sign in at `/login` with the new TEST manager. Verify the authenticated application and Operations Health page load. Stop here.

## After base deployment passes

Provider activation is a separate change and a separate acceptance run. Create the dedicated TEST bot/private chat/group and dedicated TEST Google account/calendar/jobs/Spreadsheet listed in `PILOT_LIVE_ACCEPTANCE_PLAN.md`; use no customer data. Store later secrets in one Render secret environment group attached to both services, retain approved recovery copies, register the exact derived Google callback, and review a Blueprint change that enables the required modes together. Then redeploy, rerun preflight/queue checks, and execute the live acceptance plan in order. This base-deployment task does not authorize or perform any provider contact.

## Operational controls still open

The Blueprint provides a private database, one-replica boundary, exact origin, secure cookies, internal application ports, stripped forwarding headers, body/read limits, a health path, and reproducible migrations. The operator must still configure Render-native backup retention/restore evidence, secret custody, alert routing, queue/heartbeat checks, and connection/resource alerts. The local `scripts/backup-postgres.ps1` targets Compose and must never be pointed at Render. Follow `PILOT_RUNBOOK.md`; keep TD-022/027/028/030/033 open until dedicated live TEST acceptance succeeds.
