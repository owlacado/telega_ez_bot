# Stage 10 pilot-readiness security and operations audit

## Decision and baseline

**PILOT READY: NO.** The audit found and fixed local security and recovery defects, but it
did not execute any live Google or Telegram acceptance and it cannot approve the remaining
product, security, retention, deployment, or key-custody decisions. Passing local tests does not
change those gates.

- Starting branch: `codex/stage10-pilot-readiness`
- Starting commit: `4b14035344ca2d50efa20a1f5bc32cb3e02eff57`
- Audit branch: `codex/stage10-pilot-readiness-quality-audit`
- Starting state: clean; normal PostgreSQL/API/Web healthy; one manager; three calendars;
  retained `technician-hub_postgres_data`; Alembic head `fba609190001`; zero drift.
- Scope boundaries: no live Google, Telegram, technician, or customer interaction; Contracts and
  GPS were not started.

## Findings and fixes

No CRITICAL issue was found.

Three HIGH issues were fixed:

1. Fake-provider safety accepted the ordinary Compose hostname `db` and had no independent
   opt-in. Fake Google or Telegram now requires all of: `ALLOW_FAKE_PROVIDERS=true`,
   `APP_ENV=test`, exact database `technician_hub_test`, loopback or `test-db`, and a database
   credential ending `_test_only`. Production-like, normal-DB, renamed-DB, ordinary-`db`, and
   partial-guard variants fail closed.
2. Known repository test encryption keys were structurally valid and could pass production
   configuration. Production now rejects the documented Google and schedule test keys without
   printing them.
3. The API had exact Origin enforcement but no Host policy. `TrustedHostMiddleware` now permits
   only configured-origin hosts, loopback probes, and the exact internal Compose service `api`.
   Hostile Host plus trusted Origin and spoofed forwarding headers returns 400. Production-image
   testing caught and corrected the initially omitted internal `api` hostname.

Four MEDIUM issues were fixed:

1. The backup name had one-second granularity, copying could overwrite a same-name artifact,
   failure cleanup did not cover every path, and a dump could be visible before a manifest was
   safely prepared. Backups now use a random suffix, refuse collisions, stage dump and manifest,
   publish the completed pair, remove failed publications, and always attempt container-temp
   cleanup.
2. The restore drill did not explicitly seed and assert schedule queue and audit evidence. It now
   covers all three queues, audit rows, and an atomic concurrent audit transaction while `pg_dump`
   establishes its snapshot.
3. The restart drill covered DB/API/Web but omitted worker processes and did not prove unhealthy
   behavior while PostgreSQL was stopped. It now runs actual Telegram, schedule, and mirror worker
   loops with guarded process-local fakes, verifies current durable heartbeats, restarts the whole
   stack, stops PostgreSQL, checks fail-closed API health, and verifies in-place recovery.
4. Operator documentation did not quantify the pilot connection budget or clearly distinguish the
   Web shell probe from application readiness. The architecture and runbooks now do both and state
   the private backup ACL and external-resource cleanup boundaries.

LOW findings remain documented:

- Docker accepts an operator-supplied `RELEASE_COMMIT`; a dirty source tree can therefore produce
  an image claiming a clean commit. The release procedure requires a reviewed clean build, but the
  Dockerfile cannot independently attest source cleanliness.
- `ops fingerprint` hashes every selected row. It emits no row payload, but its work and memory grow
  with database size. This remains aligned with TD-015 and is acceptable only for the small pilot
  dataset/offline operator use.

## Independent open-debt matrix

This reconstruction uses each current `TECH_DEBT.md` description and acceptance condition. `Local`
means the full debt is locally solvable; `Partial` means only bounded controls can be proven without
a decision, deployment, or provider.

| ID     | Exact current obligation                                                                              | Status         | Pilot | Production | Later scale | Live provider | Product decision  | Local   |
| ------ | ----------------------------------------------------------------------------------------------------- | -------------- | ----- | ---------- | ----------- | ------------- | ----------------- | ------- |
| TD-010 | Deletion reason, reviewed version, append-only guarantee, retention/access, durable actor attribution | OPEN           | Yes   | Yes        | No          | No            | Yes               | Partial |
| TD-011 | Encrypt/protect plaintext license ID and SSN last4; define access, rotation, recovery, backup policy  | OPEN           | Yes   | Yes        | No          | No            | Yes               | Partial |
| TD-012 | Managed credentials, TLS termination, approved proxy/host/origin and comprehensive request budgets    | OPEN (PARTIAL) | Yes   | Yes        | No          | No            | Yes               | Partial |
| TD-013 | Database-owned profile version and dependent binding/assignment version boundary                      | OPEN (PARTIAL) | Yes   | Yes        | No          | No            | Boundary approval | Partial |
| TD-015 | Pagination/selected projections and measured fleet/history limits                                     | OPEN           | No    | Eventually | Yes         | No            | Scale target      | Partial |
| TD-016 | Approved RPO/RTO, encrypted off-host retention, restore cadence and deployment rollback               | OPEN (PARTIAL) | No    | Yes        | No          | No            | Yes               | Partial |
| TD-017 | Correlation, centralized metrics/alerts, global DB/lock/network deadlines and admission               | OPEN (PARTIAL) | Yes   | Yes        | No          | No            | Operations        | Partial |
| TD-018 | HTTPS-only/approved-host image or managed-upload/CSP policy                                           | OPEN           | Yes   | Yes        | No          | No            | Yes               | Partial |
| TD-019 | Runtime response validation/version compatibility for independently deployed clients                  | OPEN           | No    | Yes        | No          | No            | No                | Yes     |
| TD-020 | Manual screen-reader, cross-browser, zoom/reflow and touch acceptance                                 | OPEN           | No    | Yes        | No          | No            | No                | No      |
| TD-022 | Real TEST-bot membership, group-add/fallback/client permission acceptance and policy                  | OPEN           | Yes   | Yes        | No          | Yes           | Membership policy | No      |
| TD-023 | Per-sender/global Telegram response budgets and dedupe-event retention policy                         | OPEN           | Yes   | Yes        | No          | Partly        | Yes               | Partial |
| TD-024 | Telegram name/title refresh policy while IDs remain authoritative                                     | OPEN           | No    | Eventually | Yes         | Yes           | If enabled        | No      |
| TD-025 | Key custody/recovery, rotation exercise, crash/orphan grant handling and durable revocation           | OPEN (PARTIAL) | Yes   | Yes        | No          | Partly        | Operations        | Partial |
| TD-026 | Per-manager/global Google budgets plus OAuth-attempt metadata retention                               | OPEN (PARTIAL) | Yes   | Yes        | No          | Partly        | Yes               | Partial |
| TD-027 | Real TEST Google consent, refresh, identity, ACL/private-event, recurrence/DST and revocation         | OPEN           | Yes   | Yes        | No          | Yes           | No                | No      |
| TD-028 | Combined real TEST schedule send, membership, HTML/limits, callbacks, local time and ambiguity        | OPEN           | Yes   | Yes        | No          | Yes           | No                | No      |
| TD-029 | Schedule key custody/rotation/recovery, alerting, backlog/claim monitoring and capacity               | OPEN (PARTIAL) | Yes   | Yes        | No          | Partly        | Operations        | Partial |
| TD-030 | Dedicated TEST mobile Work Report and Expense bearer-link/HTTPS/timezone acceptance                   | OPEN           | Yes   | Yes        | No          | Yes           | No                | No      |
| TD-031 | Approved business/form/audit retention, anonymization, archive and backup policy                      | OPEN (PARTIAL) | Yes   | Yes        | No          | No            | Yes               | Partial |
| TD-032 | Long XLSX cell presentation policy beyond bounded wrapped full values                                 | OPEN           | No    | Eventually | Yes         | No            | Yes               | Partial |
| TD-033 | Real TEST Google Sheets OAuth, writes, formatting, retries and reconciliation                         | OPEN           | Yes   | Yes        | No          | Yes           | No                | No      |
| TD-034 | Real quota/latency/grid evidence for very large Sheets fleets                                         | OPEN           | No    | Yes        | No          | Yes           | Scale target      | No      |
| TD-035 | Supported-client visual acceptance for approximate Google row heights                                 | OPEN           | No    | Eventually | Yes         | Yes           | If changed        | No      |

TD-001 through TD-009, TD-014, and TD-021 remain resolved. This audit closes no existing
TECH_DEBT item: 35 entries remain 11 resolved and 24 open. The 16 pilot blockers remain TD-010,
TD-011, TD-012, TD-013, TD-017, TD-018, TD-022, TD-023, TD-025, TD-026, TD-027, TD-028, TD-029,
TD-030, TD-031, and TD-033. Additional production gates are TD-016, TD-019, TD-020, and TD-034;
later-scale items are TD-015, TD-024, TD-032, and TD-035.

## Readiness model

`TechnicianPilotReadiness` remains the single backend projection. An active technician requires an
accounting timezone, private Telegram, and one available assigned calendar. A Google calendar also
requires the current connection and event scope. When schedule delivery is disabled, a work group
is optional; when enabled it is required. Google Sheets mirrors, XLSX, Contracts, and GPS do not
block readiness. Sheets status changes from optional-unconfigured to optional-configured without
changing `ready`.

Readiness is recomputed from current rows on every list/detail request. Tests change timezone,
private binding, assignment/availability, Google scope, schedule mode/group, and active state and
observe the next response immediately. Dashboard, card, and detail consume the same API projection;
the 30/30 mutation run detects a frontend recomputation. Reasons expose only bounded state labels
and do not expose chat IDs, spreadsheet IDs, tokens, ciphertext, or provider error detail.

## Preflight and HTTP security

Configuration construction is the first preflight gate, so runtime and CLI share the same failures.
Production-like debug, insecure cookies, sample DB credentials, fake providers, malformed DB URLs,
missing enabled-provider keys, known test keys, wildcard/non-ASCII/noncanonical origins, remote HTTP,
paths, credentials, queries, and fragments fail closed. Exact HTTPS and multiple exact origins pass;
lookalikes do not match. Zero or inactive-only managers block, one or multiple active managers pass.
DB failure and stale/incorrect migration head return nonzero with sanitized output.

Manager cookies remain HttpOnly and SameSite Strict for normal login. Production requires Secure;
loopback development may use HTTP. The existing OAuth flow reissues the same manager session with
SameSite Lax for the cross-site callback without dropping HttpOnly/Secure or extending its lifetime.
Origin/CSRF checks remain exact. Host validation is independent. The application does not use
public-client forwarding headers for authorization; Uvicorn's default proxy trust is loopback-only,
and the runbook requires a narrow trusted-proxy IP and direct-API firewall if deployed behind a
non-loopback proxy.

## Health, workers, and queues

Public API health executes `SELECT 1`: healthy DB returns 200, stopped/unreachable DB returns 503,
and secrets are absent. Operations Health is manager-only; anonymous and technician capability
requests cannot obtain migration, provider, heartbeat, or queue topology. It performs no live
provider HTTP request.

Telegram, schedule, and mirror status comes from durable status plus DB-clock heartbeat freshness.
Fresh RUNNING/STARTING, stale, STOPPED, explicit ERROR, MISSING, and intentionally DISABLED states are
distinct; an explicit error is not hidden by freshness. The 120-second boundary uses PostgreSQL
time. Missing/stale enabled workers make aggregate health WARN; migration mismatch makes it BLOCK.
Queue output contains only pending/processing/failed/ambiguous counts with each worker's documented
state mapping.

SIGTERM paths stop new loop iterations, bound current work, persist STOPPED when DB access remains,
close providers, and dispose engines. Multiple workers use durable claims/advisory locks and remain
claim-safe, but the connection budget permits only one pilot replica of each. Ambiguous Telegram
sends remain terminal; only an explicit manager-confirmed resend creates another attempt. Mirror
refresh is deterministic/idempotent and may be retried or manually resynced.

The Web `/login` probe proves only that the Next process serves its shell. It may remain healthy
while API/DB is unavailable; API and Operations Health are the application signals.

## Backup, restore, restart, and cleanup

The backup command passes no database password on its command line, emits no secret, resolves an
operator-selected directory, refuses collisions, stages output, hashes the completed dump, publishes
the dump/manifest pair, exits nonzero on failure, and cleans the container and host partials. The
operator must use a private ACL: a dump contains business data and encrypted credential ciphertext.

The isolated restore has a synthetic manager, technician, calendar/assignment, Telegram metadata,
encrypted Google refresh credential, Work Report and revision, Expense and revision, schedule queue,
Telegram outbox, mirror target/queue, and audit events. A two-row transaction commits while `pg_dump`
establishes its MVCC snapshot; restore must match the complete pre- or post-transaction fingerprint,
never a split state. All 22 table fingerprints, Alembic state, login, accounting totals, durable
queues, correct-key decrypt, and wrong-key failure are checked. Older backups are restored to an
isolated DB and migrated forward; the normal DB is never reset.

The restart drill uses a dedicated named volume and restarts DB, API, Web, and the three worker
loops. It verifies login, accounting, queue-row counts, 22 fingerprints, fresh worker heartbeats,
stopped-DB unhealthy health, and recovery without database reconstruction. A whole schedule decision
window outage remains unsolved: persistence can recover a created decision or dispatch, but cannot
invent a historical automatic decision that was never evaluated. Telegram offset/deduplication and
mirror catch-up behavior retain their earlier crash/concurrency coverage.

Cleanup uses PostgreSQL time, row locks with `SKIP LOCKED`, and a clamped 1..1000 batch. A 1,001-row
probe processes exactly 100. A racing refresh that commits while cleanup waits is rechecked and
survives. Dry-run does not mutate even inside its transaction; stable immediate apply returns the
same selection, while concurrent changes can legitimately alter a later batch. Apply clears only
expired form snapshots, consumed/expired OAuth verifier ciphertext, and expired terminal schedule
payload ciphertext. Work Reports, Expenses, revisions, audit history, managers, technicians,
calendars, and durable queue receipts remain. TD-031 stays open because cleanup is an implementation
mechanism, not an approved retention/anonymization/archive policy.

## Deployment, privacy, and operator review

The API/Web build injects version and commit through image environment metadata and does not require
`.git` at runtime. One API plus three workers can open 60 regular SQLAlchemy connections; one ops
engine raises that to 75, and the one-technician NullPool lock paths add about two transient owners.
Against PostgreSQL's default 100 and usual reserved slots, the pilot margin is about 20. A second
full worker set can exceed 100, so replica count is constrained until pools and admission are
configured.

Business state remains in PostgreSQL/external providers. XLSX is in memory; backup destination is
operator-owned; container `/tmp` is transient. Privacy regressions place canaries in Work Report
comments, addresses, Expense notes, OAuth-like values, Telegram-like values, DB passwords, provider
keys, and preflight input. Responses, caplog, audit rows, ops output, and Git-visible artifacts do not
contain them. The tracked secret scan reports zero findings.

The provider matrix covers private/group onboarding, Calendar discovery/events, schedule send and
acknowledgement, Work Report, Expense, Individual mirror, and All Tech mirror. The acceptance runbook
keeps secrets out of Git, shell history, screenshots, chat/Codex, and test source; requires fictional
technicians/jobs and dedicated TEST chat/calendar/spreadsheets; and now requires explicit intent
before deleting external TEST resources. Pilot and incident runbooks cover DB/API/Web and every
worker, revoked Google, invalid Telegram token, 429, stuck queues, ambiguous send, restore, rollback,
and concrete stop conditions. Mirror lag/rate limit is degraded projection behavior, while wrong
identity/destination, duplicate finance, or DB corruption is a stop.

## Mutation and quality evidence

`scripts/audit_stage10_mutations.py` detected **30/30** weakened variants and restored every source
byte-for-byte. It covers all 25 required categories plus sample DB password, production test key,
frontend rule drift, incomplete fingerprint inventory, and normal-volume loss.

- Backend PostgreSQL suite: 1,497 passed, 2 skipped; the subsequently added DB-clock boundary
  regression passed in the final focused run.
- Stage 10 focused readiness/preflight/health/cleanup/security: 47 passed.
- Frontend unit: 148 passed in 11 files; TypeScript and ESLint passed.
- Playwright development: 28 passed.
- Playwright production image: 28 passed.
- Native Next build and fresh no-cache API/Web Docker builds: passed.
- Backup/restore concurrent snapshot drill: passed, 22 tables.
- Full-stack restart and DB outage/recovery drill: passed, including all workers.
- Migration matrix: fresh, every populated stage, guarded rollback, downgrade/re-upgrade, one head,
  zero drift; final head `fba609190001`.
- OpenAPI deterministic check, Ruff lint/changed-file format, Prettier, Compose configs, `pip check`,
  `npm audit --omit=dev`, secret scan, and `git diff --check`: passed.
- Normal database opaque before/after fingerprints match: one manager and three calendars preserved.

## Remaining gates and next actions

**CODE COMPLETE BUT LIVE TEST REQUIRED:** TD-022, TD-027, TD-028, TD-030, and TD-033. Provision the
dedicated TEST Google project/account/calendar/spreadsheets and TEST Telegram bot/private/group,
execute every acceptance row with fictional data, and attach sanitized reviewer evidence.

**PRODUCT/SECURITY DECISION REQUIRED:** TD-010, TD-011, TD-018, TD-023, TD-026, and TD-031. Approve
audit access/retention and durable attribution; sensitive-field handling; image/CSP policy;
Telegram/Google budgets; dedupe/OAuth retention; and business/form archive/anonymization policy.

**OPERATIONAL SETUP REQUIRED:** TD-012, TD-017, TD-025, and TD-029. Approve and rehearse TLS/proxy,
managed secrets, request/connection budgets, alerts/deadlines, Google key/revocation recovery, and
schedule key/worker capacity. TD-013 additionally needs a database-owned version/dependent-state
boundary. The register marks these BEFORE INTERNAL PILOT; a one-technician TEST pilot is therefore
not approved merely because sanctioned profile PATCH conflicts and local worker recovery pass.

Only after these owners close every applicable acceptance condition should the blocker matrix be
updated and `PILOT READY` reconsidered.
