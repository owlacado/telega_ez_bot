# Architecture

Technician Hub is a modular monorepo, deployed locally as a web process, API process, and PostgreSQL database. This provides explicit module boundaries without distributed service infrastructure.

## Dependency direction

```text
Next.js UI -> same-origin /api proxy -> FastAPI routers -> module services -> PostgreSQL
     |                                      |
     v                                      v
contracts (generated OpenAPI types)     Pydantic contracts + SQLAlchemy models
shared (pure display helpers)          integration Protocol interfaces
```

The backend imports no web implementation. API contracts are exported from FastAPI into `packages/contracts/openapi.json`; `openapi-typescript` generates the web types. `packages/shared` contains only pure TypeScript presentation helpers.

## Modules

- `technicians`: immutable UUID identity, profile validation, list/search, status, guarded permanent deletion. List responses intentionally omit license ID and SSN last four.
- `calendars`: local calendar directory, atomic assignment replacement, assignment history, guarded local record removal. This module calls the technician lookup service; technician routes orchestrate calendar assignment on create.
- `integrations`: separate Telegram/GPS binding models and future `TelegramProvider`, `CalendarProvider`, `AccountingProvider`, and `GpsProvider` Protocol interfaces. No implementations, credentials, background workers, polling, or network clients exist.
- `core`: settings, SQLAlchemy async sessions, timestamps, structured error handling. Engine/session factory lifetime is owned by the FastAPI application, not hidden global connection state.

## PostgreSQL is authoritative

There is no CSV, Sheets, or in-browser database. UUIDs are created independently of external identifiers. The API rejects unknown fields, including attempts to change `id`. Provider IDs are nullable bindings keyed by the technician UUID, so removing a connection cannot change who the technician is.

Tables: `technicians`, `calendars`, `calendar_assignments`, `telegram_bindings`, `gps_bindings`; plus Alembic's version table. UUID primary keys, foreign keys with explicit delete behavior, status checks, an SSN last-four check, nullable unique Telegram identifiers, and partial unique indexes enforce the domain rules.

Calendar assignments have their own UUID and timestamps, a calendar-name snapshot, and an active flag. Switching closes the previous assignment and creates another in a single transaction. Technician and calendar row locks serialize concurrent changes; database indexes are the final guard. Reassigning the same calendar is idempotent. An already assigned calendar returns HTTP 409 rather than silently transferring it.

Unassigning preserves technician identity and history. Removing a calendar marks its assignments inactive and sets their calendar FK to null while preserving the historical name. Deleting a technician permanently cascades to its assignment history and provider bindings; independent local calendar records remain.

Alembic migrations are the only schema lifecycle mechanism. Application startup never calls `create_all()`. Compose applies `alembic upgrade head` before serving requests.

## API and UI

API routes:

- `GET /api/health`: executes a database query; unavailable database yields a sanitized 503.
- `GET, POST /api/technicians`
- `GET, PATCH, DELETE /api/technicians/{id}`
- `PUT, DELETE /api/technicians/{id}/calendar`
- `GET /api/technicians/{id}/calendar-assignments`
- `GET, POST /api/calendars`
- `PATCH, DELETE /api/calendars/{id}`

Successful creates return 201; deletes return 204; invalid requests return 422; missing records 404; assignment/identifier conflicts 409. Errors use `{ "error": { "code", "message", "details"? } }`. Validation errors never echo submitted values. Responses disable caching. Deletion requires a JSON confirmation body, but the countdown belongs only to the browser.

Frontend routes: `/`, `/technicians`, `/technicians/{id}`, `/calendars`. A fixed left sidebar persists its collapsed state in browser local storage. Data remains API-backed. The desktop detail grid holds profile/connections, accounting, jobs, and location. Smaller screens stack the panels.

Dashboard setup checks include both active and inactive profiles and require an assigned calendar plus connected private Telegram, work group, and GPS. Those future bindings remain not connected in normal Stage 0 use; attention counts therefore reflect unfinished integration setup honestly.

## Sensitive data and future work

Full SSNs have no model field and are rejected as unknown input. SSN last four is optional, accepts only four ASCII digits, and is masked in the form. Driver license and last-four values currently use ordinary PostgreSQL fields. There is no encryption, user login, RBAC, audit trail, or secrets manager in Stage 0. Local ports bind only to loopback. Use fictional data until those capabilities are implemented.

Photo URLs load only when explicitly supplied by a user; the browser fetches the image without a referrer. No remote fonts, sample photos, analytics, or background provider calls are used.

Future adapters must accept internal technician identity and resolve their own bindings. Accounting output must come from an explicit real data source. GPS presentation supports `ACTIVE_TRIP`, `LAST_KNOWN_STOP`, `NO_DATA`, and `UNKNOWN`; there is no `PARKED` state, and public share data must not be treated as proof of a current parked position. No Moto Watchdog share token is stored.

No Kubernetes, Redis, RabbitMQ, Celery, or cloud infrastructure is introduced.
