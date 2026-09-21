# Controlled TEST pilot policy decisions

This record now contains the product owner's approved choices for the one-technician internal TEST
pilot. Approval was supplied on 2026-09-19 for every row below. Production retention, collection,
deletion, image, and capacity policy remains a separate legal/business/security decision wherever
the sections below say so.

## Approval summary

| Debt   | Decision owner                 | Recommended TEST-pilot default                  | Approval recorded |
| ------ | ------------------------------ | ----------------------------------------------- | ----------------- |
| TD-010 | Product owner + security owner | Disable permanent technician deletion           | Yes — 2026-09-19 |
| TD-011 | Product owner + security owner | Collect no license ID or SSN last four          | Yes — 2026-09-19 |
| TD-018 | Product owner + security owner | Use initials; permit no external profile image  | Yes — 2026-09-19 |
| TD-023 | Product owner + operations     | Adopt the specified application admission limits | Yes — 2026-09-19 |
| TD-026 | Product owner + operations     | Adopt the specified manager admission limits    | Yes — 2026-09-19 |
| TD-031 | Product owner + records owner  | Retain business evidence; purge only transients | Yes — 2026-09-19 |
| TD-013 | Product owner + engineering    | Approve the narrow database version boundary    | Yes — 2026-09-19 |

## TD-010 — deletion audit and accountability

**Question.** May a manager permanently delete the pilot technician, and if so what reason,
reviewed version, append-only enforcement, actor durability, access, and retention are required?

**Options and consequences.** Disabling permanent deletion and using deactivation is the smallest
risk and preserves all evidence, but an operator cannot exercise deletion during the pilot. Keeping
deletion with the current audit event preserves actor/target/time but leaves the known reason,
version, append-only, durable-actor, and retention gaps. Enabling deletion only after database
append-only enforcement and an approved retention/access policy provides the complete control but
requires schema, API, UI, migration, and recovery work.

**Approved decision.** Disable permanent deletion for this internal TEST pilot; deactivate and
retain the fictional record.

**Changes after approval.** For the recommended option, add a production/pilot configuration gate
that rejects permanent deletion while retaining the current development/test regression path. If
deletion is approved instead, require a bounded reason and expected database version, preserve a
non-sensitive actor tombstone, enforce append-only audit rows in PostgreSQL, authorize audit reads,
and implement the approved retention rule.

**Implemented pilot control.** The manager UI exposes deactivation only, the API always rejects
technician DELETE with 409, and PostgreSQL rejects direct technician DELETE. Historical and business
rows are retained. A future production decision to restore deletion must first reopen TD-010.

## TD-011 — license ID and SSN last-four protection

**Question.** Will the pilot collect either identifier, and if so who may read it and how must it be
encrypted, rotated, recovered, logged, exported, and backed up?

**Options and consequences.** Collecting neither field removes the pilot exposure but leaves the
fields unavailable for operational use. Field-level authenticated encryption with keys outside the
database preserves the capability but requires masking, migration, rotation, recovery, backup, and
access testing. Retaining plaintext with role restrictions leaves database and backup exposure and
is not recommended.

**Approved decision.** Collect neither value; leave both columns null for the TEST pilot.

**Changes after approval.** Hide or disable those inputs in pilot mode, reject non-null writes at
the API boundary, and add a preflight/data check. If collection is approved, implement versioned
field encryption and the approved authorization, rotation, recovery, export, and backup rules
before accepting real values.

**Implemented pilot control.** Create/update/detail contracts and the manager UI omit both fields;
extra manager-API input is rejected and PostgreSQL rejects new non-null values. Existing legacy
values are not erased by the migration and remain outside public response schemas. Production
collection remains prohibited until encryption and access policy are approved.

## TD-018 — external profile images

**Question.** Should browsers load technician images from external hosts, and what privacy, host,
HTTPS, and content-security policy applies?

**Options and consequences.** Initials only makes no external request and is simplest. An HTTPS
allowlist supports approved hosts but exposes client network metadata to those hosts and needs CSP
maintenance. Managed upload/proxying gives stronger control but creates a new storage and content
handling surface outside this pilot's scope. Arbitrary URLs retain the known privacy and intranet
request risk.

**Approved decision.** Use initials only and leave `photo_url` empty for the TEST pilot.

**Changes after approval.** For initials-only, reject or ignore non-null photo URLs in pilot mode
and set `img-src 'self'` (plus required framework assets) in the deployed CSP. An allowlist choice
requires HTTPS-only validation, exact hosts, matching CSP, and browser privacy tests. Managed upload
requires separate design approval and is not part of this pass.

**Implemented pilot control.** The API and manager UI omit `photo_url`, PostgreSQL rejects new
non-null values, Avatar always renders generated initials, and Web responses set `img-src 'self'`.
No binary upload surface exists.

## TD-023 — Telegram response budgets and processed-update retention

**Question.** Which Telegram identities may receive bot responses, what per-sender/global response
budgets apply, and how long are deduplication rows retained without weakening offset recovery?

**Options and consequences.** A dedicated TEST bot used only by the fictional technician and TEST
group minimizes exposure but Telegram users can still discover or message a public bot. Adding an
allowlist and suppressing replies to unknown senders reduces outbound amplification but requires
identity configuration and support handling. General public replies require higher operational
capacity and abuse monitoring. Short dedupe retention reduces storage but narrows forensic history;
indefinite retention is simplest but grows without bound.

**Approved decision.** Apply application admission at 30 actions per minute per sender, a burst of
10 actions per 10 seconds per sender, and 300 actions per minute globally. Retain processed-update
metadata for 7 days and delete only rows below the durable worker offset. These limits do not alter
Telegram provider send/retry handling.

**Changes after approval.** Add configured identity admission, database-backed per-sender/global
admission buckets, sanitized rejection outcomes, and bounded cleanup that proves the retained offset
cannot replay deleted updates. The existing invitation, verification, and test-send budgets remain.

**Implemented pilot control.** Configurable database-backed buckets commit admission together with
an `ADMITTED` processed-update reservation before application work. A retry resumes that reservation
without another charge; finalized, rejected, and callback outcomes remain durably deduplicated.
Cleanup requires both the seven-day age and a durable worker offset beyond the update. Independent
crash/retry, callback, concurrent-duplicate, boundary, cleanup, and mutation checks pass.

## TD-026 — Google request budgets and OAuth-attempt retention

**Question.** What per-manager/global OAuth-start and successful scan budgets apply, and how long
should non-secret OAuth-attempt metadata remain after verifier ciphertext is cleared?

**Options and consequences.** Very low budgets protect quota but can slow recovery. Higher budgets
reduce operator friction while increasing compromised-session and quota exposure. Keeping metadata
longer improves investigation but expands retained identifiers; immediate deletion reduces evidence.

**Approved decision.** Allow 5 OAuth starts per 15 minutes per manager and 20 per hour globally.
Allow 6 manual Calendar scan/reconnect actions per 10 minutes per manager and 30 per hour globally.
Retain OAuth-attempt metadata for 7 days. Existing short-lived state/PKCE TTL, single use, provider
`Retry-After`, and worker/provider retry policy remain unchanged.

**Changes after approval.** Add database-backed per-manager and global OAuth/scan buckets, expose
only aggregate rejection metrics, and extend bounded cleanup to metadata older than the approved
period without weakening single-use state or replay protection.

**Implemented pilot control.** OAuth start and manual scan/reconnect use configurable
database-backed manager/global buckets. Cleanup clears expired/consumed verifier ciphertext first
and deletes only already-cleared attempt metadata after seven days.

## TD-031 — business, form, audit, archive, and backup retention

**Question.** How long must submitted Work Reports, Expenses, revisions, audit events, form-session
metadata, and backups remain; when may records be anonymized or archived; who may approve it?

**Options and consequences.** Retaining all submitted business/audit evidence through the TEST
pilot is safest for reconciliation and practical at this size but does not define production
retention. Automatic time-based deletion reduces storage but can destroy financial and incident
evidence. Reviewed anonymization can reduce personal data while retaining accounting facts, but it
needs a field-by-field policy and immutable audit record.

**Approved decision.** During the TEST pilot, never automatically delete Work Reports, Expenses,
revisions, or audit records. Continue bounded cleanup for transient secret/session payloads. Keep a
rolling 30-day operational backup window. Perform no automatic anonymization during the pilot.

**Changes after approval.** Encode approved durations and legal holds as configuration, add bounded
archive/anonymization jobs with dry-run and audit records, test backup expiry consistently, and keep
business deletion separate from transient cleanup. No broader deletion is authorized by this
record.

**Implemented pilot control.** Cleanup remains limited to transient snapshots/ciphertext and the
approved OAuth/Telegram metadata. The backup script removes only its exact script-owned dump and
manifest filenames older than 30 days after publishing a complete new pair. Independent synthetic
execution retained arbitrary operator files, partial names, lookalikes, and newer artifacts. Final
production retention, legal holds, anonymization, and off-host policy remain open.

## TD-013 — narrow database-owned version boundary for approval

**Question.** Should one database-owned technician version guard profile edits and destructive
actions against concurrent changes to the technician and the small set of dependent states that
change identity, readiness, calendar source, or message destination?

**Proposed boundary.** Add `technicians.record_version BIGINT NOT NULL DEFAULT 1`. PostgreSQL, not
the ORM clock, increments it when protected technician profile columns change. Narrow triggers also
increment the owning technician version when any of these effective states changes: active calendar
assignment; current Google connection identity, generation, scopes, or status; current private or
work-group Telegram binding identity, generation, or availability; and schedule-delivery enabled
state. Historical revisions, audit rows, queue progress, mirror progress, and display-only provider
metadata stay outside the boundary because they do not change the profile or current destination.

Every sanctioned profile or destructive request supplies `expected_record_version`. The service
locks the technician, compares the version, applies its transaction, and returns the resulting
version. Database triggers cover raw SQL and alternate writers. A dependent-state transaction that
changes several rows increments once per affected technician by collecting distinct technician IDs
in a statement-level transition-table trigger or an equivalent transaction-local helper. Migration
backfills `1`, installs triggers, and verifies no existing behavior depends on `updated_at` as the
concurrency token. `updated_at` remains display/audit time.

**Alternatives and consequences.** Keeping only `expected_updated_at` is smaller but leaves raw SQL
and dependent-state gaps. Expanding the version to every related row creates unnecessary conflicts
from queue and history activity. Separate versions per subsystem reduce conflicts but complicate
deletion review and clients.

**Approved decision.** Use the single narrow `record_version` boundary above for the one-manager
pilot. It closes the identified gap without creating a general event-sourcing architecture.

**Changes after approval.** Add one additive migration, update API schemas/services and generated
frontend contracts, move stale-write tests from timestamps to the monotonic version, add direct-SQL
and dependent-state trigger tests, and preserve 409 behavior.

**Implemented pilot control.** Migration `fca609190001` introduced the version and triggers;
independent audit migration `fda609200001` makes technician identity database-owned and narrows
assignment, Telegram, and schedule triggers to effective state. The transaction-local distinct-ID
helper increments each affected technician once per transaction. Concurrent transactions serialize,
rollback leaves no bump, and display-only or absent-equivalent rows do not bump. PATCH compares and
returns the current version under the existing lock; `updated_at` remains display time. Full details
are in `AUDIT_PILOT_POLICY_IMPLEMENTATION.md`.

## Locally completed operational evidence

- The HTTPS/proxy boundary is explicit in `PILOT_ARCHITECTURE.md`: only the controlled proxy exposes
  the remote service, direct API access is blocked, forwarding headers are replaced, and trusted
  proxy IPs are narrow.
- `PILOT_RUNBOOK.md` now gives a managed-secret inventory, recovery/rotation order, existing request
  budgets, alert thresholds, and an executable `queues --require-pass` monitor.
- `scripts/verify_pilot_key_recovery.py` proves synthetic correct-key recovery, wrong-key failure,
  and envelope rotation without a database or provider call. It does not claim Google revocation or
  deployed secret-store acceptance.
- `INCIDENT_RUNBOOK.md` defines worker/backlog/claim signals and immediate response thresholds.

TD-012, TD-017, TD-025, and TD-029 remain open until the selected deployment installs the proxy,
secret store, alert route, schedules the checks, rehearses recovery with deployed synthetic secrets,
and then completes any provider-dependent acceptance. Local documentation and tooling alone cannot
prove those external operational controls exist.
