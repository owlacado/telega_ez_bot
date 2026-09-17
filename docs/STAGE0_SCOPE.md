# Stage 0 scope

## Implemented

- A separate repository and `codex/stage0-foundation` branch.
- Next.js, strict TypeScript, App Router, Tailwind CSS, restrained sidebar-based UI.
- Persistent 240px/70px sidebar with accessible navigation labels and collapsed tooltips.
- Database-derived dashboard counts and actionable setup list.
- Technician search, identity cards, initials/photo fallback, quick create and direct detail navigation.
- Technician create/read/update/delete, profile validation, active/inactive status, immutable API identity.
- A two-by-two desktop detail layout and responsive stacking.
- Local calendar CRUD API, directory table, assignment selection, change, unassign, historical records, confirmed local removal.
- Disabled schedule, Telegram, work group, GPS, and Google scan controls with explanations.
- Honest accounting, jobs, and vehicle-location empty states.
- Permanent deletion with typed full-name confirmation, ten-second frontend delay, backend explicit confirmation, and real PostgreSQL cascade behavior.
- PostgreSQL constraints, Alembic migrations, async SQLAlchemy, structured errors, generated API contracts.
- Development-only idempotent calendar seed; no fabricated provider IDs or binding rows on create.
- Docker Compose local stack, isolated PostgreSQL test profile, Windows instructions, automated validation.
- Backend integration tests, frontend component tests, and a Playwright smoke flow.

## Not implemented

- Telegram messages or bot calls; work-group onboarding; schedule delivery.
- Google Calendar discovery/synchronization; Google Sheets accounting.
- Moto Watchdog requests or token storage; live tracking or fabricated positions.
- Any accounting values, fabricated jobs, revenue charts, or external integrations.
- Discord, email, SMS, cloud resources, queues, or background jobs.
- Full SSN storage, file/photo uploads, user authentication, or authorization.

## Deferred to next stages

- Authenticated manager accounts, role access, audit trails, encrypted sensitive fields, retention controls, production deployment hardening.
- Real providers behind the existing ports, credential lifecycle, reconciliation, retries, webhooks, and observability.
- Confirmed calendar discovery and synchronization; verified Telegram account/work-group association.
- Accounting source integration and real financial widgets.
- Evidence-aware vehicle location using only the supported future states.
- Pagination and indexed search when the dataset requires them.

This application is a local foundation. Intentionally deferred features are visible as disabled controls or empty states, not fake successful integrations.
