# Stage 10 pilot readiness verification

## Decision

**PILOT READY: NO.** Stage 10 completed the locally provable hardening work, but the
one-technician pilot remains blocked by the open policy decisions and dedicated TEST
Google/Telegram acceptance listed in `PILOT_BLOCKER_MATRIX.md`. No real provider,
technician, or customer data was contacted during this stage.

## Baseline and scope

- Starting branch: `codex/stage9-google-sheets-mirrors-quality-audit`
- Starting commit: `c50e4d448086af013435a408858a9cd989cd4803`
- Stage branch: `codex/stage10-pilot-readiness`
- Normal PostgreSQL volume retained: `technician-hub_postgres_data`
- Feature freeze observed: Contracts and GPS were not started.

The complete 35-item inventory, its dependencies, and every Stage 10 disposition are in
`PILOT_BLOCKER_MATRIX.md`. Before Stage 10 there were 17 pilot blockers. TD-014 is now
resolved by validated database constraints. TD-012, TD-013, TD-017, TD-025, TD-026,
TD-029, and TD-031 received bounded local remediation but remain open. Sixteen pilot
blockers remain.

## Local hardening evidence

- A single backend `TechnicianPilotReadiness` projection owns the readiness rules.
  Manager cards, technician detail, and Dashboard consume that projection without
  recreating the rules in React.
- The profile update endpoint requires `expected_updated_at` and returns `409` for a stale
  sanctioned update.
- Startup validation rejects malformed database URLs, unsafe production debug/cookies,
  wildcard or non-exact origins, production sample passwords, production fake providers,
  incomplete real providers, and incomplete schedule-delivery dependencies.
- `python -m hub.ops.cli preflight` is provider-silent, emits only `PASS`, `WARN`, or
  `BLOCK`, returns a nonzero exit status for blockers, and never prints configured secret
  values.
- `/api/health` verifies PostgreSQL and reports the app version and release commit.
  Authenticated `/api/operations/health` reports migration state, heartbeat-derived worker
  states, provider configuration, and payload-free queue counts.
- PostgreSQL CHECK constraints reject invalid Telegram and GPS provider-state combinations.
- Optional workers have bounded restart policies and graceful shutdown paths. Heartbeat
  freshness, durable claiming, reclaim, and ambiguous-send behavior remain database based.
- Expired form snapshots, OAuth verifier ciphertext, and expired terminal schedule payload
  ciphertext have a bounded, lock-safe, dry-run-first cleanup command. Business revisions,
  audit records, and durable metadata are retained.

## Backup and recovery evidence

`scripts/backup-postgres.ps1` creates a custom-format `pg_dump` in an operator-selected
directory, writes a SHA-256 manifest, and removes its temporary container copy. Provider
encryption keys are deliberately excluded and must be backed up separately from the dump.

The isolated restore drill populated a synthetic manager, technician, calendar, Telegram
binding metadata, Google connection ciphertext, Work Report and revision, Expense and
revision, mirror target/refresh, and Telegram outbox item. It then used the production
backup wrapper, dropped only the disposable restore database, restored the dump, reran
migrations, and verified all 22 structural fingerprints. Result:

```text
backup PASS; restore PASS; fingerprint MATCH; tables 22
manager login PASS; accounting PASS; durable queues PASS
correct credential key PASS; wrong credential key rejected
```

The isolated full-image restart drill restarted PostgreSQL, API, and Web against its own
named volume. All 22 fingerprints matched afterward; login, accounting, queue state, API
DB recovery, and Web recovery passed. The runbook distinguishes container/image/network
loss with an intact volume from volume loss, which requires an external database backup.

## Security, privacy, and operations evidence

- Tracked-file secret-signature and secret-artifact scans found no committed provider key,
  bot token, private key, database dump, `.env`, or backup artifact.
- Health, preflight, queue, fingerprint, and cleanup outputs contain state/counts and opaque
  digests only. They do not emit passwords, provider tokens, encryption keys, customer
  addresses, report comments, or expense notes.
- Production mode requires secure cookies and exact HTTPS origins. Local loopback HTTP is
  reserved for development/test. The deployment runbook requires an approved TLS proxy
  boundary and does not trust arbitrary public forwarded headers.
- Login admission control remains covered by the existing database-backed throttling tests.
  Transferable technician capability links, Telegram platform abuse limits, and provider
  acceptance remain explicitly open debt.
- The pilot architecture document records PostgreSQL as canonical and provider writes as
  side effects/projections. It also records a conservative pilot connection budget and
  sensible Docker resource guidance.
- XLSX generation remains in memory; no business-critical state depends on a container
  filesystem.

## Mutation evidence

`scripts/audit_stage10_mutations.py` detected **19 of 19** deliberate regressions and
restored every changed file byte for byte. The set covers all 18 required mutations plus a
production sample-database-password mutation: readiness omissions, frontend rule drift,
fake production providers, secret output, manager/migration preflight bypass, incomplete
restore coverage, unsafe cleanup, stale heartbeat handling, DB-down health, wildcard
origin, production debug, volume loss, and ambiguous Telegram retry.

## Quality gate evidence

- Backend PostgreSQL regression suite: final result recorded below after the authoritative
  isolated run.
- Stage 10 focused readiness, preflight, operations, cleanup, and recovery tests: passed.
- Frontend unit suite: 148 passed across 11 files.
- Strict TypeScript, ESLint, Ruff, changed-file Prettier, and `git diff --check`: passed.
- Native Next.js production build and fresh API/Web Docker image builds: passed.
- OpenAPI snapshot check and generated TypeScript contract: deterministic.
- Alembic has one head: `fba609190001`; destructive rollback/re-upgrade validation uses
  only `technician_hub_test`.
- All four Compose files validate.
- `pip check` reported no broken requirements; `npm audit --omit=dev` reported zero
  vulnerabilities.
- Isolated backup/restore and full-container restart drills: passed as described above.
- Playwright development and production-image results are recorded below after their final
  clean-database runs.

## Remaining gates

Pilot blockers remain TD-010, TD-011, TD-012, TD-013, TD-017, TD-018, TD-022, TD-023,
TD-025, TD-026, TD-027, TD-028, TD-029, TD-030, TD-031, and TD-033. Production also
requires TD-016, TD-019, TD-020, and TD-034. Later-scale work remains TD-015, TD-024,
TD-032, and TD-035.

Before the pilot, owners must approve the audit/sensitive-data/deployment/profile-image/
retention/key-custody and abuse policies, finish the remaining operational monitoring and
concurrency boundaries, configure the dedicated TEST Google account/project/spreadsheet and
TEST Telegram bot/chats through the documented secret boundary, execute the acceptance
runbook using only fictional data, attach evidence to TD-022/027/028/030/033, and confirm
that every pilot blocker is satisfied.

## Final recorded results

- Backend full suite: `1468 passed, 2 skipped`
- Stage 10 focused suite: `18 passed`
- Playwright development: `28 passed`
- Playwright production image: `28 passed`
- Alembic validation/schema drift: `PASS; fba609190001 is the single head`
- Normal database preservation: `PASS; all 10 protected baseline fingerprints matched`
- Final commit: recorded in the Git history and Stage 10 completion report
