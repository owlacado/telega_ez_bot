# Operator incident runbook

For every incident, record UTC time, release commit, affected component, safe UUID/job IDs, and
status codes. Do not copy business payloads, addresses, comments, Expense notes, tokens, bot/chat
identifiers, password hashes, credentials, or encryption keys into logs or tickets. Take an opaque
fingerprint and private backup before state-changing recovery when the database is available.

## Safe diagnostics

```powershell
python -m hub.ops.cli preflight
python -m hub.ops.cli queues
python -m hub.ops.cli fingerprint
docker compose ps
docker compose logs --tail 200 api web telegram-worker schedule-worker accounting-mirror-worker
```

The queue command reports pending, processing, failed, and ambiguous counts without payloads. The
manager Operations Health page reports DB/schema/provider configuration and persisted heartbeat
states. A container shown as running is not evidence that its worker heartbeat is current.

## Component incidents

| Incident                     | Immediate action                                                                 | Recovery and verification                                                                                                              |
| ---------------------------- | -------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| API down                     | Stop manager writes; check DB health and sanitized API logs                      | Restore DB reachability/config, restart API, verify `/api/health`, login, operations health and one read                               |
| DB down                      | Stop all workers; preserve the volume; never initialize a replacement over it    | Restore network/container with the same named volume, or restore a verified dump to a new isolated DB; migrate forward and fingerprint |
| Web down                     | Use no ad-hoc direct mutations; API/DB may remain healthy                        | Restart Web, verify anonymous `/login`, authenticated navigation and exact release ID                                                  |
| Telegram worker down         | Pause onboarding/form issuance; inspect heartbeat and queue counts               | Fix config/network, restart; queued work may resume, but review `UNKNOWN` manually                                                     |
| Schedule worker down         | Disable/hold automatic delivery and monitor the configured window                | Restart before the window; inspect PENDING/PROCESSING/FAILED/AMBIGUOUS; do not claim missed-window reconstruction                      |
| Mirror worker down           | Continue canonical business operations                                           | Restart after Google/config recovery; request existing manual resync because writes are deterministic/idempotent                       |
| Google authorization revoked | Stop scans/mirrors/schedules that require Google                                 | Reconnect through UI, confirm account/scopes, rescan and manually resync; do not rewrite ciphertext                                    |
| Telegram token invalid       | Stop Telegram and schedule workers                                               | Replace token in secret store, verify expected bot identity, restart, revalidate bindings/destinations                                 |
| Google rate limiting         | Leave canonical DB untouched; honor persisted retry time                         | Wait for allowed retry, reduce operator requests, then rescan/resync; record sanitized quota code                                      |
| Stuck durable queue          | Stop the owning worker before changing state; capture queue counts and heartbeat | Use existing UI action or worker reclaim semantics. Never edit payload/state with raw SQL during pilot                                 |
| Ambiguous schedule send      | Stop automatic retries for that item                                             | Check TEST chat/provider evidence, record decision, and only a manager-confirmed resend may create a new attempt                       |
| Backup restore               | Isolate target and preserve source evidence                                      | Follow the restore procedure below; never restore over the retained normal DB as a test                                                |

## Database and volume disasters

If a container, image, or Docker network is lost while the named volume remains, recreate the image
and network with Compose while attaching the unchanged volume. Confirm the database name, migration
head, manager count, and fingerprint before enabling workers. Container recreation does not recreate
deleted volume contents.

If the volume is lost, obtain the latest verified private database dump and the separately protected
provider/schedule keys. Restore to a new isolated PostgreSQL instance, verify the manifest digest,
run `alembic upgrade head`, compare the stored opaque fingerprint, test manager login/accounting and
durable queues, then point a staged application at it. A database restored without the original
Google or schedule key retains ciphertext but cannot use it; stop affected workers and restore the
key or deliberately reconnect. Never silently replace, blank, or re-encrypt unknown ciphertext.

## Deployment and migration recovery

Safe order: backup and manifest; build the recorded release; validate a single Alembic head and
upgrade path; stop workers; apply forward migration; start API/Web; run preflight and health; then
start enabled workers and verify current heartbeats. If migration fails, keep workers stopped, retain
the original DB/backup and migration error, diagnose on a restored copy, and deploy a corrective
forward migration. Do not reset the database or automatically downgrade the normal environment.

## Cleanup and retention

`python -m hub.ops.cli cleanup-expired-data` is dry-run. Review counts, then use
`--apply --batch-size 100` for bounded cleanup. It expires and clears abandoned form snapshots,
clears consumed/expired OAuth verifier ciphertext, and clears expired terminal schedule ciphertext.
It intentionally retains technicians, assignments, provider metadata, submitted forms, Work Reports,
Expenses, all revisions, audit events, queue receipts, and fingerprints. Apply the approved retention
policy before adding any broader deletion.

Configure bounded container-log rotation at the Docker daemon or deployment platform. Keep audit
records in PostgreSQL under the approved access/retention policy; container logs are not the audit
system.
