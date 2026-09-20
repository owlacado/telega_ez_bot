# Pilot architecture and runtime inventory

```text
Manager Browser
      |
     Web
      |
     API
      |
 PostgreSQL (canonical)
   /       |          \
Telegram  Schedule   Google Mirror
 Worker    Worker       Worker
   \        |           /
       Google / Telegram
```

PostgreSQL is the canonical system of record. Google Sheets is a deterministic projection,
Telegram sends are side effects with durable receipts, and Google Calendar is an external read
source whose discovered identity and assignments are recorded locally. A provider response never
replaces committed Work Reports, Expenses, accounting revisions, queue state, or audit history.

## Components and dependencies

| Component       | Startup dependency                                                    | Runtime dependency                | Health/failure signal                                                                      |
| --------------- | --------------------------------------------------------------------- | --------------------------------- | ------------------------------------------------------------------------------------------ |
| PostgreSQL      | Persistent volume and valid credentials                               | Disk, memory, connection capacity | `pg_isready`; API DB query                                                                 |
| API             | Healthy PostgreSQL; current migration                                 | PostgreSQL                        | Public `/api/health` checks DB; manager `/api/operations/health` checks schema and workers |
| Web             | Healthy API during Compose startup                                    | API for authenticated pages       | Anonymous `/login` process/shell healthcheck; API health is separate                       |
| Telegram worker | Healthy API/DB; real Telegram settings when enabled                   | PostgreSQL and Telegram           | `telegram_worker_states`; disabled mode exits successfully                                 |
| Schedule worker | Healthy API/DB; Telegram and Google real settings; schedule key       | PostgreSQL, Calendar, Telegram    | `schedule_worker_states`; disabled mode exits successfully                                 |
| Mirror worker   | Healthy API/DB; real Google settings and credential key               | PostgreSQL and Google Sheets      | `accounting_mirror_worker_states`; disabled mode exits successfully                        |
| Google Calendar | Explicit `GOOGLE_MODE=real` and OAuth settings                        | Google OAuth/Calendar APIs        | Stored connection status/retry; no page-load connectivity probe                            |
| Google Sheets   | Google settings plus granted Sheets scope                             | Google Sheets API                 | Durable refresh status/retry and mirror worker heartbeat                                   |
| Telegram        | Explicit `TELEGRAM_MODE=real`, expected bot identity and token source | Telegram Bot API                  | Binding availability, outbox result, worker heartbeat                                      |

Workers claim jobs through PostgreSQL and use database time for leases. Heartbeats are current for
120 seconds; enabled workers with missing, stale, stopped, or error state are reported as such.
SIGTERM stops new cycles, allows bounded current work, writes a stopped state where the database is
available, closes providers, and releases engines. Schedule uncertainty remains terminal and must
be reviewed; the system never blindly retries an ambiguous Telegram send.

## Environment inventory

| Category                              | Variables                                                                                                                                 | Rule                                                                                                                                                           |
| ------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Required core                         | `DATABASE_URL`, `APP_ENV`, `COOKIE_SECURE`, `ALLOWED_ORIGINS`, `APP_VERSION`, `RELEASE_COMMIT`                                            | Production requires PostgreSQL async credentials, HTTPS origins, secure cookies, no debug, a non-sample DB password, and an exact release commit in preflight. |
| Compose database                      | `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_PORT`                                                                      | Local Compose construction only; production values must be unique and managed.                                                                                 |
| Web/ports                             | `API_INTERNAL_URL`, `API_PORT`, `WEB_PORT`                                                                                                | Internal Web-to-API URL and loopback port mappings.                                                                                                            |
| Required Telegram when enabled        | `TELEGRAM_MODE`, `TELEGRAM_EXPECTED_BOT_ID`, `TELEGRAM_EXPECTED_BOT_USERNAME`, one of `TELEGRAM_TOKEN_FILE` or `TELEGRAM_BOT_TOKEN`       | `fake` is accepted only for the isolated test database. A worker verifies bot identity before polling.                                                         |
| Required Google Calendar when enabled | `GOOGLE_MODE`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_OAUTH_REDIRECT_URI`, `GOOGLE_CALENDAR_CREDENTIAL_ENCRYPTION_KEY`       | Exact callback origin/path, external Fernet key, and real mode are required.                                                                                   |
| Required Google Sheets when enabled   | Same Google variables; manager grants Sheets scope                                                                                        | Sheets has no separate credential or spreadsheet environment variable. Target IDs are manager-configured database state.                                       |
| Required schedule when enabled        | `SCHEDULE_DELIVERY_ENABLED`, `SCHEDULE_PAYLOAD_ENCRYPTION_KEY`, `SCHEDULE_AUTO_DELIVERY_LOCAL_TIME`, enabled Telegram and Google settings | Schedule cannot start with either provider disabled.                                                                                                           |
| Optional                              | `SESSION_LIFETIME_SECONDS`, `WORK_REPORT_SESSION_SECONDS`, `TELEGRAM_INVITE_SECONDS`, provider features in disabled mode                  | Bounds are validated centrally. Optional providers do not block core startup.                                                                                  |
| Test-only                             | `TEST_DATABASE_URL`, `E2E_BASE_URL`, `ALLOW_FAKE_PROVIDERS`; `fake` provider modes                                                        | Requires explicit opt-in, `APP_ENV=test`, exact `technician_hub_test`, loopback/`test-db`, and a `_test_only` DB credential.                                   |
| Library compatibility                 | `PTB_TIMEDELTA` in worker containers                                                                                                      | Telegram library behavior; no application secret.                                                                                                              |
| Deprecated/unknown                    | None intentionally supported                                                                                                              | Pydantic ignores unrelated environment keys; the reviewed inventory is in `.env.example`.                                                                      |

## Connections and pilot budget

The API uses its regular SQLAlchemy pool and a separate `NullPool` Google lock engine. Telegram and
mirror workers each use one regular engine; the schedule worker uses one regular engine and one
`NullPool` lock engine. Each default regular engine can open 5 pooled plus 10 overflow connections.
One API and one replica of each of the three workers can therefore open 60 regular connections; one
concurrent ops/migration engine can bring that to 75. At one-technician pilot concurrency, the API
and schedule `NullPool` lock paths add roughly two transient owners, leaving about 20 ordinary
connections below PostgreSQL's default 100 after its usual reserved slots. This is a conservative
pilot-only budget, not a general maximum: unbounded HTTP concurrency can create more `NullPool`
owners. Run at most one replica of each worker and one API replica until explicit pool sizes,
request admission, and deployment `max_connections` are approved. A second full worker set could
raise regular-engine demand beyond 100.

## Persistence and generated files

Business-critical state exists in PostgreSQL or the configured external providers. XLSX exports
are generated in memory and require no persistent container filesystem. Token files and encryption
keys are mounted/configured secrets and must be backed up separately from the database. Container
logs and temporary dump files are operational artifacts, not canonical records.

For a small local pilot, allocate enough memory for PostgreSQL, API, Web, and enabled workers plus
image builds; 4 CPU cores, 8 GB RAM, and monitored free disk are a sensible starting point rather
than a guaranteed sizing result. Configure Docker log rotation (for example size/file limits in the
daemon or deployment platform) and synchronized host time. Queue correctness uses database time,
but TLS, logs, and provider clients still need reasonable infrastructure clock synchronization.

## Network boundary

Local development binds all published ports to loopback and may use HTTP. The API accepts only the
exact hostnames from configured origins, loopback health-probe hosts, and the exact internal Compose
Web-to-API service name `api`; a trusted Origin does not bypass a hostile Host. Any remote pilot
needs an approved HTTPS reverse proxy, exact public origin,
secure cookies, request-size and timeout limits, and explicit proxy trust. Uvicorn's default proxy
trust is loopback-only, and application authorization does not consume `X-Forwarded-*` values.
Terminate, discard, and replace client forwarding headers at the controlled proxy; if that proxy is
not loopback, configure Uvicorn's trusted proxy IPs narrowly and firewall direct API access.

The Web `/login` Docker probe establishes that the Next process can serve its shell. It can remain
healthy while the API or database is down, so it must never be used as aggregate application
readiness. The public API DB probe and authenticated Operations Health supply that separate signal.
