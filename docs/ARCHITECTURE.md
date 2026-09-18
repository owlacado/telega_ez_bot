# Architecture

## Stage 5 Work Reports (current lifecycle extension)

`work_reports` adds TechnicianFormSession, WorkReport and immutable WorkReportRevision.
The worker calls its domain service from trusted private commands; only opaque
short-lived bearer form credentials authorize technician HTTP submission. Manager
auth is a separate boundary. Read [WORK_REPORTS.md](WORK_REPORTS.md) for the explicit
bearer-link threat model, unchanged Stage 3 projection, frozen server job snapshot,
Decimal/payment/review facts, atomic replay semantics and bounded read-only views.

Deletion semantics below are historical for technicians **without business records**.
Reports now RESTRICT technician/calendar deletion; revision/identity triggers prevent
history mutation. The deferred report→current-revision FK supports truthful future
latest-revision-only calculations. Stage 5 itself implements no accounting or
correction flow. Confirmation is the committed form receipt, without a provider send.

Stage 2 adds the Google Calendar provider described in [GOOGLE_CALENDAR_INTEGRATION.md](GOOGLE_CALENDAR_INTEGRATION.md). CalendarConnection and single-use GoogleOAuthAttempt are distinct from technician identity. Calendar rows now have LOCAL_DEMO/GOOGLE source, connection-scoped provider identity, last-seen availability, and explicit local exclusions. Existing assignment history and both active-assignment uniqueness indexes remain authoritative. A normalized CalendarProvider boundary owns OAuth, refresh, revoke, and complete CalendarList pagination; Stage 3 adds the read-only event boundary described below. Fernet-encrypted refresh credentials stay server-side; access tokens are ephemeral. Network fetch and short atomic reconciliation are separated by generation checks and PostgreSQL advisory coordination.

Current Telegram completion supersedes the original review-only flow described below for **new** invitations. New PRIVATE_TELEGRAM/WORK_GROUP credentials automatically activate the existing binding in the same transaction as claim/audit/outbox. A new group claim requires the exact linked private actor and bot membership/send capability, without administration. Legacy invitations retain review semantics through the server-owned automatic=false migration value. All existing generations, advisory locks, unique IDs, manager auth, provider boundaries, outbox and deletion protections remain. See [the current runbook](TELEGRAM_ONBOARDING.md) and [completion verification](TELEGRAM_COMPLETION_VERIFICATION.md).

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
- `integrations`: the existing Telegram/GPS binding models and provider Protocols. `TelegramBinding` remains the sole approved Telegram identity record. Google Calendar has its own normalized adapter; accounting/GPS ports remain unimplemented.
- `auth`: managers, hashed sessions, shared database rate limits, request middleware, login/logout/current-session routes and interactive provisioning CLI.
- `audit`: small append-oriented action records without arbitrary metadata payloads.
- `telegram`: invitations, binding services, trusted update parsing/processing, lifecycle, membership verification, durable outbox, async Bot API adapter, optional polling worker. Network transport contains no SQL or identity rules. The same backend package/image owns API and worker; there is no second service database.
- `core`: settings, SQLAlchemy async sessions, timestamps, structured error handling. Engine/session factory lifetime is owned by the FastAPI application, not hidden global connection state.

## PostgreSQL is authoritative

There is no CSV, Sheets, or in-browser database. UUIDs are created independently of external identifiers. The API rejects unknown fields, including attempts to change `id`. Provider IDs are nullable bindings keyed by the technician UUID, so removing a connection cannot change who the technician is.

Tables: `technicians`, `calendars`, `calendar_assignments`, `telegram_bindings`, `gps_bindings`, `managers`, `manager_sessions`, `rate_buckets`, `audit_events`, `telegram_invitations`, `telegram_outbox`, `telegram_worker_states`, `telegram_processed_updates`, `calendar_connections`, `google_oauth_attempts`; plus Alembic's version table. UUID primary keys, foreign keys with explicit delete behavior, status checks, an SSN last-four check, nullable unique Telegram identifiers, and partial unique indexes enforce the domain rules.

Calendar assignments have their own UUID and timestamps, a calendar-name snapshot, and an active flag. Switching closes the previous assignment and creates another in a single transaction. Technician and calendar row locks serialize concurrent changes; database indexes are the final guard. Reassigning the same calendar is idempotent. The technician assignment endpoint rejects a calendar owned by another technician. The explicit calendar-table transfer endpoint checks the displayed assignee and atomically transfers it.

Unassigning preserves technician identity and history. A CHECK constraint requires an active assignment to reference a calendar, and calendar names must be nonblank. Deleting a local demo calendar marks its assignments inactive and sets their calendar FK to null while preserving the historical name. Google calendar removal instead preserves the calendar row, deactivates its assignment and sets an explicit local exclusion. Deleting a technician permanently cascades to its assignment history and provider bindings; independent local calendar records remain.

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

Successful creates return 201; deletes return 204; invalid requests return 422; missing records 404; assignment/identifier conflicts 409. Errors use `{ "error": { "code", "message", "details"? } }`. Validation errors never echo submitted values. Responses disable caching. Technician deletion requires `confirmation: "DELETE"` and the displayed `expected_updated_at` timestamp. The version is compared under the technician row lock; a changed profile returns 409. This is a profile version, not a version of its entire relationship graph. The countdown belongs only to the browser and is not an authorization boundary. Calendar deletion keeps its separate confirmation/detach contract. Mutation responses are captured inside the transaction and returned only after commit succeeds.

Frontend routes: `/login` plus protected `/`, `/technicians`, `/technicians/{id}`, `/calendars`. A server layout validates the cookie against `/auth/me` before rendering business pages; the client rechecks sessions while visible. Backend middleware protects every business request, including docs/OpenAPI. A fixed left sidebar persists its collapsed state in browser local storage. Data remains API-backed; resource state is keyed by URL and ignores cancelled requests and stale mutation callbacks. The desktop detail grid holds profile/connections, accounting, jobs, and location. Smaller screens stack the panels.

Dashboard setup checks include both active and inactive profiles and require an assigned calendar plus connected private Telegram, work group, and GPS. Telegram availability errors are represented separately from approved identity and propagated to integration attention states. GPS remains unconfigured.

## Sensitive data and future work

Full SSNs have no model field and are rejected as unknown input. SSN last four is optional, accepts only four ASCII digits, and is masked in the form. Driver license and last-four values currently use ordinary PostgreSQL fields. Stage 1 adds manager authentication, authorization and audit. Field encryption, enterprise roles and a managed secrets vault remain deferred. Local ports bind only to loopback. Use fictional data until those capabilities are implemented.

Photo URLs load only when explicitly supplied by a user; the browser fetches the image without a referrer. No remote fonts, sample photos, or analytics are used. Provider workers run only through explicit opt-in configuration; Stage 4 additionally requires per-technician automatic enablement.

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

The API process never instantiates the real Telegram provider; the explicitly enabled Google adapter runs in the API. Default worker mode is disabled, real mode validates expected identity and refuses any configured webhook. Polling/network retries are bounded. Runtime status comes from a dedicated heartbeat, expiring after 90 seconds, not API health.

## Added routes and contracts

- Public `POST /api/auth/login`; authenticated `GET /api/auth/me`, `POST /api/auth/logout`.
- Authenticated `GET /api/telegram/runtime`.
- Under `/api/technicians/{id}/telegram`: `GET` state; `POST /invitations`; `POST /invitations/{invitation_id}/revoke`, `/review`, `/retry`; `POST /disconnect`; `POST /test-message`.
- No HTTP route accepts provider updates, raw Telegram user IDs or arbitrary delivery targets. The test harness invokes the same application services in a separate guarded local process.

Generated OpenAPI/TypeScript adds manager session, invitation, candidate, connection, runtime and delivery shapes. Technician deletion now additionally requires the displayed expected_updated_at; the other existing technician/calendar contracts remain compatible. Shared aliases are exported from `@hub/contracts`.

Migrations, in order: Stage 0 `863590d3075e`; auth/audit `b89e091fa280`; existing-binding extensions `5644c8fc030a`; invitation/outbox/worker persistence `4344e0e76774`. Additive upgrades preserve Stage 0 data. Destructive downgrade/upgrade checks are restricted to a disposable test database.

See [Telegram security](TELEGRAM_SECURITY.md) for retention and authentication details, and [onboarding](TELEGRAM_ONBOARDING.md) for opt-in operation and client limitations.

Stage 0 audit migration `a04e70c92001` branches from `863590d3075e`. Reconciliation revision `d6c2f8a14001` joins that branch and Stage 1 `4344e0e76774`, preserving both existing migration histories and supporting upgrades from either installed head.

Audit evidence and current debt are tracked in [AUDIT_STAGE0.md](AUDIT_STAGE0.md), [TECH_DEBT.md](TECH_DEBT.md), and [AUDIT_RECONCILIATION.md](AUDIT_RECONCILIATION.md).

Migration e7b310920001 follows the reconciliation head and preserves old credentials/queued messages while translating the private-purpose vocabulary. Both fresh and populated upgrade/downgrade paths are checked; see scripts/validate_migrations.py.

## Stage 3: on-demand calendar event projections

`calendar_events` owns normalized read models, operational date windows, title/work-window filtering,
job ordering and schedule formatting. The Google adapter alone issues Events.list HTTP reads.
`CalendarProvider.list_events` returns normalized DTOs; no Google SDK event objects enter the domain.
There is no event table, event mirror, or background event synchronization. Stage 4 stores only an encrypted delivery snapshot, purged on confirmed send; it reuses this projection for Telegram delivery.

Manager-authorized GET routes `/api/technicians/{id}/calendar/today` and
`/api/technicians/{id}/calendar/next-schedule` take short SQL snapshots, refresh credentials under the
existing lifecycle guard, read the provider outside SQL transactions, then recheck manager session,
assignment UUID, calendar availability/timezone, current connection generation and granted scopes.
Changed identities discard the fetched data. Per-technician nonblocking advisory guards suppress
simultaneous event reads without consuming the transaction pool. Rotated refresh credentials are
encrypted and committed before pagination. A scope-specific failure removes only event capability;
Calendar discovery remains available. Provider Retry-After uses the shared persisted connection deadline.

OAuth `request_event_access` is bound to the single-use attempt by additive migration c3e410a20917.
It is accepted only for same-account RECONNECT, and requests both narrow read scopes with incremental
authorization. Partial consent is represented solely by `CalendarConnection.granted_scopes`.
An omitted refresh token must be verified for identity and refreshed capability before reuse.
The migration downgrade consumes pending upgrade attempts before dropping their policy flag.

The browser owns one Today reader and a preview reader only while its modal is open. Request identity,
AbortController and mount cleanup prevent stale success/failure from another technician or assignment.
Refresh clears previous jobs; errors cannot label cached jobs current. Strict Mode dispatch is deferred
one microtask to deduplicate its immediate setup/cleanup cycle. Operational display times arrive as
server-normalized `HH:mm`; date-only labels use explicit UTC formatting without changing their date.

## Stage 4 schedule delivery

See [Schedule delivery](SCHEDULE_DELIVERY.md) for the unified immutable dispatch path, dedicated
payload key, separate worker, calendar-local automatic delivery (OFF by default),
acknowledgement authorization, uncertainty recovery, retention, and dedicated TEST
acceptance runbook. The Telegram polling worker receives callbacks; the schedule
worker sends durable dispatches and evaluates automatic decisions. Neither starts
inside the web API. Stage 3 job filtering and wall-clock projection remain authoritative.
