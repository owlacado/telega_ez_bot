# Architecture

Technician Hub is a modular monorepo, deployed locally as a web process, API process, PostgreSQL database, and optional Telegram worker. This provides explicit module boundaries without distributed service infrastructure.

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
- `integrations`: the existing Telegram/GPS binding models and provider Protocols. `TelegramBinding` remains the sole approved Telegram identity record. Calendar/accounting/GPS ports remain unimplemented.
- `auth`: managers, hashed sessions, shared database rate limits, request middleware, login/logout/current-session routes and interactive provisioning CLI.
- `audit`: small append-oriented action records without arbitrary metadata payloads.
- `telegram`: invitations, binding services, trusted update parsing/processing, lifecycle, membership verification, durable outbox, async Bot API adapter, optional polling worker. Network transport contains no SQL or identity rules. The same backend package/image owns API and worker; there is no second service database.
- `core`: settings, SQLAlchemy async sessions, timestamps, structured error handling. Engine/session factory lifetime is owned by the FastAPI application, not hidden global connection state.

## PostgreSQL is authoritative

There is no CSV, Sheets, or in-browser database. UUIDs are created independently of external identifiers. The API rejects unknown fields, including attempts to change `id`. Provider IDs are nullable bindings keyed by the technician UUID, so removing a connection cannot change who the technician is.

Tables: `technicians`, `calendars`, `calendar_assignments`, `telegram_bindings`, `gps_bindings`, `managers`, `manager_sessions`, `rate_buckets`, `audit_events`, `telegram_invitations`, `telegram_outbox`, `telegram_worker_states`, `telegram_processed_updates`; plus Alembic's version table. UUID primary keys, foreign keys with explicit delete behavior, status checks, an SSN last-four check, nullable unique Telegram identifiers, and partial unique indexes enforce the domain rules.

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

Frontend routes: `/login` plus protected `/`, `/technicians`, `/technicians/{id}`, `/calendars`. A server layout validates the cookie against `/auth/me` before rendering business pages; the client rechecks sessions while visible. Backend middleware protects every business request, including docs/OpenAPI. A fixed left sidebar persists its collapsed state in browser local storage. Data remains API-backed. The desktop detail grid holds profile/connections, accounting, jobs, and location. Smaller screens stack the panels.

Dashboard setup checks include both active and inactive profiles and require an assigned calendar plus connected private Telegram, work group, and GPS. Telegram availability errors are represented separately from approved identity and propagated to integration attention states. GPS remains unconfigured.

## Sensitive data and future work

Full SSNs have no model field and are rejected as unknown input. SSN last four is optional, accepts only four ASCII digits, and is masked in the form. Driver license and last-four values currently use ordinary PostgreSQL fields. Stage 1 adds manager authentication, authorization and audit. Field encryption, enterprise roles and a managed secrets vault remain deferred. Local ports bind only to loopback. Use fictional data until those capabilities are implemented.

Photo URLs load only when explicitly supplied by a user; the browser fetches the image without a referrer. No remote fonts, sample photos, analytics, or background provider calls are used.

Future adapters must accept internal technician identity and resolve their own bindings. Accounting output must come from an explicit real data source. GPS presentation supports `ACTIVE_TRIP`, `LAST_KNOWN_STOP`, `NO_DATA`, and `UNKNOWN`; there is no `PARKED` state, and public share data must not be treated as proof of a current parked position. No Moto Watchdog share token is stored.

No Kubernetes, Redis, RabbitMQ, Celery, or cloud infrastructure is introduced.

## Stage 1 state and transactions

A technician UUID is permanent until local deletion. Approved Telegram IDs are nullable unique signed BIGINT values on `telegram_bindings`; API IDs are strings to avoid JavaScript precision loss. Pending invitation/candidate metadata lives separately. Expiration/rejection cannot overwrite an approved identity.

- A 32-byte random token is URL-safe encoded (43 characters). Only its SHA-256 digest is stored. The issue response alone returns the link/optional scoped group command with no-store headers.
- One open invitation per technician/purpose is enforced by a partial unique index. Row locks serialize issuance and consumption. Claims carry expected private/group generations and are rechecked after network membership queries.
- Approval locks the technician/invitation, validates expiry/status/generation, takes an external-ID transaction advisory lock and checks ownership; existing unique indexes are the final guard. Binding switch, invalidation, notification enqueue and audit commit together.
- Private approval/disconnect increments generations and suspends the retained group until revalidation. Group actions are independent. Changes never infer identity from names/usernames.
- The outbox stores internal references, destination kind and binding generations, not arbitrary browser-supplied chat IDs or message contents. Send destinations are resolved from the current approved binding immediately before dispatch.
- Send/delete/disconnect/approval serialize on a technician session advisory lock held on a dedicated AUTOCOMMIT connection. No SQL transaction spans provider I/O. An already-started send completes before local deletion; the deletion then removes remaining local jobs. External messages cannot be recalled by deleting the profile.
- A per-bot session advisory lock permits one poller. Each update's effects and `(bot_id, update_id)` deduplication record commit together; only then does the durable offset advance. A crash in that gap safely replays the deduplicated update. A processing failure stops offset advancement past the failed event.
- A send left PROCESSING at restart becomes UNKNOWN, never blindly replayed. A read-only VERIFY_GROUP job may be requeued. Explicit Telegram retry-after failures retry at most three attempts, up to 600 seconds per wait; ambiguous network send errors become UNKNOWN. Command receipts are best-effort and are not an exactly-once channel.

The API process never instantiates the real provider. Default worker mode is disabled, real mode validates expected identity and refuses any configured webhook. Polling/network retries are bounded. Runtime status comes from a dedicated heartbeat, expiring after 90 seconds, not API health.

## Added routes and contracts

- Public `POST /api/auth/login`; authenticated `GET /api/auth/me`, `POST /api/auth/logout`.
- Authenticated `GET /api/telegram/runtime`.
- Under `/api/technicians/{id}/telegram`: `GET` state; `POST /invitations`; `POST /invitations/{invitation_id}/revoke`, `/review`, `/retry`; `POST /disconnect`; `POST /test-message`.
- No HTTP route accepts provider updates, raw Telegram user IDs or arbitrary delivery targets. The test harness invokes the same application services in a separate guarded local process.

Generated OpenAPI/TypeScript adds manager session, invitation, candidate, connection, runtime and delivery shapes. Existing technician/calendar contracts remain compatible. Shared aliases are exported from `@hub/contracts`.

Migrations, in order: Stage 0 `863590d3075e`; auth/audit `b89e091fa280`; existing-binding extensions `5644c8fc030a`; invitation/outbox/worker persistence `4344e0e76774`. Additive upgrades preserve Stage 0 data. Destructive downgrade/upgrade checks are restricted to a disposable test database.

See [Telegram security](TELEGRAM_SECURITY.md) for retention and authentication details, and [onboarding](TELEGRAM_ONBOARDING.md) for opt-in operation and client limitations.
