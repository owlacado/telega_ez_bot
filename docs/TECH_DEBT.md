# Technical debt register

Scope: independent Stage 1 Telegram quality audit from c480fe2. **24 entries: 10 RESOLVED, 14 OPEN.** Unresolved severity counts: **CRITICAL 0, HIGH 2, MEDIUM 9, LOW 3**. Resolved counts: HIGH 3, MEDIUM 7. This audit adds TD-023 and TD-024; no existing item is closed. Evidence is in AUDIT_STAGE1_TELEGRAM.md. TD-014 was due BEFORE STAGE 1 and remains overdue; it is a BEFORE NEXT STAGE blocker, not a newly deferred obligation.

Future stages must update this register when debt is discovered, resolved, or a milestone changes. RESOLVED means implemented and covered by the referenced audit checks. No CRITICAL finding was identified.

| ID     | Severity | Area                                  | Required Before       | Status   |
| ------ | -------- | ------------------------------------- | --------------------- | -------- |
| TD-001 | HIGH     | Identity / navigation                 | BEFORE STAGE 1        | RESOLVED |
| TD-002 | HIGH     | Permanent deletion                    | BEFORE STAGE 1        | RESOLVED |
| TD-003 | MEDIUM   | Database integrity                    | BEFORE STAGE 1        | RESOLVED |
| TD-004 | MEDIUM   | Transactions / response               | BEFORE STAGE 1        | RESOLVED |
| TD-005 | MEDIUM   | Input validation                      | BEFORE STAGE 1        | RESOLVED |
| TD-006 | MEDIUM   | Frontend mutations                    | BEFORE STAGE 1        | RESOLVED |
| TD-007 | MEDIUM   | Failure recovery                      | BEFORE STAGE 1        | RESOLVED |
| TD-008 | MEDIUM   | Accessibility / layout                | BEFORE INTERNAL PILOT | RESOLVED |
| TD-009 | HIGH     | Authentication / authorization        | BEFORE STAGE 1        | RESOLVED |
| TD-010 | HIGH     | Deletion audit / accountability       | BEFORE INTERNAL PILOT | OPEN     |
| TD-011 | HIGH     | Sensitive data protection             | BEFORE INTERNAL PILOT | OPEN     |
| TD-012 | MEDIUM   | Deployment / credentials / origins    | BEFORE INTERNAL PILOT | OPEN     |
| TD-013 | MEDIUM   | Concurrent profile editing            | BEFORE INTERNAL PILOT | OPEN     |
| TD-014 | MEDIUM   | Provider state invariants             | BEFORE NEXT STAGE     | OPEN     |
| TD-015 | MEDIUM   | Scaling / response size               | LATER SCALE           | OPEN     |
| TD-016 | MEDIUM   | Durability / operations               | BEFORE PRODUCTION     | OPEN     |
| TD-017 | MEDIUM   | Observability / timeouts              | BEFORE INTERNAL PILOT | OPEN     |
| TD-018 | MEDIUM   | External profile images               | BEFORE INTERNAL PILOT | OPEN     |
| TD-019 | LOW      | Runtime contracts                     | BEFORE PRODUCTION     | OPEN     |
| TD-020 | LOW      | Accessibility coverage                | BEFORE PRODUCTION     | OPEN     |
| TD-021 | MEDIUM   | Search consistency                    | BEFORE STAGE 1        | RESOLVED |
| TD-022 | MEDIUM   | Telegram membership / live acceptance | BEFORE INTERNAL PILOT | OPEN     |
| TD-023 | MEDIUM   | Telegram abuse / retention            | BEFORE INTERNAL PILOT | OPEN     |
| TD-024 | LOW      | Telegram metadata freshness           | LATER SCALE           | OPEN     |

## TD-001: Identity / navigation

- **Severity:** HIGH
- **Area:** Identity / navigation
- **Description:** A path change retained the preceding technician and allowed a late response to overwrite the new identity.
- **Why it matters:** Users could act on the wrong profile under a different URL.
- **Evidence:** apps/web/src/lib/use-resource.ts; resource.test.tsx reproduced two failures on the baseline.
- **Recommended remediation:** Resource results are keyed by path, aborted completions are ignored, and stale mutation callbacks cannot replace a newer resource.
- **Required before milestone:** BEFORE STAGE 1
- **Status:** RESOLVED

## TD-002: Permanent deletion

- **Severity:** HIGH
- **Area:** Permanent deletion
- **Description:** Deletion accepted an unchanged literal even when the profile had changed since confirmation opened. Dialog version changes did not reset approval; same-tick clicks could submit twice.
- **Why it matters:** Permanent deletion is irreversible and must correspond to the profile the operator reviewed.
- **Evidence:** technicians/router.py; delete-technician.tsx; stale-delete, version reset and double-submit regressions.
- **Recommended remediation:** Require a timezone-aware expected_updated_at and compare under row lock. Reset dialog by identity/version and synchronously guard submission. The version covers profile fields, not all dependent history.
- **Required before milestone:** BEFORE STAGE 1
- **Status:** RESOLVED

## TD-003: Database integrity

- **Severity:** MEDIUM
- **Area:** Database integrity
- **Description:** PostgreSQL accepted blank calendar names and active assignments with a null calendar.
- **Why it matters:** Alternate writers or raw calendar deletion could create inconsistent active reservations.
- **Evidence:** Direct database tests failed on f105093; migration a04e70c92001 adds validated CHECK constraints.
- **Recommended remediation:** Keep the additive constraints. Calendar removal first deactivates assignment history; raw deletion of an actively assigned calendar now fails. Repair invalid legacy rows deliberately before upgrading.
- **Required before milestone:** BEFORE STAGE 1
- **Status:** RESOLVED

## TD-004: Transactions / response

- **Severity:** MEDIUM
- **Area:** Transactions / response
- **Description:** Mutation handlers read/refresh their result after commit and lock release. Calendar rename could raise StopIteration if deletion won the next transaction.
- **Why it matters:** Successful writes appeared as server failures and could provoke duplicate retries.
- **Evidence:** test_calendar_rename_response_survives_postcommit_delete deterministically reproduced a 500.
- **Recommended remediation:** Construct response snapshots after flush while the transaction is held; return only after commit succeeds. Applied to technician create/update, calendar create/rename and assignment.
- **Required before milestone:** BEFORE STAGE 1
- **Status:** RESOLVED

## TD-005: Input validation

- **Severity:** MEDIUM
- **Area:** Input validation
- **Description:** Control characters reached storage; null bytes produced database errors. Whitespace-only license IDs became empty strings.
- **Why it matters:** Invalid data and misleading 503 responses differed from documented validation semantics.
- **Evidence:** Nine control-character cases and blank-license normalization failed before the fix.
- **Recommended remediation:** Reject C0/DEL characters at input validation, retain international names, normalize blank optional license IDs to null, and never echo sensitive input values.
- **Required before milestone:** BEFORE STAGE 1
- **Status:** RESOLVED

## TD-006: Frontend mutations

- **Severity:** MEDIUM
- **Area:** Frontend mutations
- **Description:** Profile inputs remained editable while a save was pending; a later edit could appear saved by an earlier response.
- **Why it matters:** The visible form and persisted record could disagree without warning.
- **Evidence:** components.test.tsx slow save/failure regression reproduced editable pending fields. Reconciliation also reproduced duplicate invitation generation in a same-tick double click; telegram.test.tsx verifies the synchronous guard and failure recovery.
- **Recommended remediation:** Disable form controls during mutations and use synchronous pending guards. Add/create and delete flows receive the same protection.
- **Required before milestone:** BEFORE STAGE 1
- **Status:** RESOLVED

## TD-007: Failure recovery

- **Severity:** MEDIUM
- **Area:** Failure recovery
- **Description:** Raw database connection refusal bypassed SQLAlchemy error handlers; malformed API JSON/error envelopes were not handled consistently.
- **Why it matters:** Offline dependencies produced generic failures and unsupported response shapes could crash a page without recovery.
- **Evidence:** Real localhost connection-refusal test reproduced HTTP 500; api.test.ts and browser error tests cover response failures.
- **Recommended remediation:** Translate connection failures in both the database dependency and Stage 1 authentication middleware to sanitized 503 responses; normalize malformed responses and provide a recoverable page error boundary.
- **Required before milestone:** BEFORE STAGE 1
- **Status:** RESOLVED

## TD-008: Accessibility / layout

- **Severity:** MEDIUM
- **Area:** Accessibility / layout
- **Description:** Several small text colors failed WCAG AA contrast, including sidebar labels and deletion explanation. Long calendar names also overflowed profile cards; dialog Tab cycling and focus restoration were unreliable.
- **Why it matters:** Important instructions and destructive actions must remain readable and reachable.
- **Evidence:** Axe found 3.28:1 sidebar and 3.98:1 initials contrast on the initial audit run; reconciliation additionally found and fixed a 3.49:1 GPS placeholder heading and explicitly scrolls it into view for testing; e2e/audit.spec.ts now passes at four sizes, including all dialogs, in development and production.
- **Recommended remediation:** Darken affected text without changing layout or product design; verify long names, dialogs, focus, Escape and no document overflow.
- **Required before milestone:** BEFORE INTERNAL PILOT
- **Status:** RESOLVED

## TD-009: Authentication / authorization

- **Severity:** HIGH
- **Area:** Authentication / authorization
- **Description:** Stage 0 exposed business endpoints without operator authentication.
- **Why it matters:** Sensitive reads and irreversible deletion require an authorized operator.
- **Evidence:** Stage 1 `hub/auth/middleware.py`, `auth/security.py`, `auth/service.py`, protected workspace layout, and `tests/test_auth.py`: active manager sessions gate business routes and API documentation; Argon2 passwords, opaque hashed sessions, expiry/revocation, trusted origins and CSRF checks protect manager operations. The current product authorizes its single trusted manager role for read/update/delete.
- **Recommended remediation:** Retain these controls and their denial/revocation/CSRF regression tests. Additional roles would require an explicit future authorization design; they are not required by the current manager-only scope.
- **Required before milestone:** BEFORE STAGE 1
- **Status:** RESOLVED by Stage 1; verified during reconciliation. This does not resolve deployment or sensitive-data debt.

## TD-010: Deletion audit / accountability

- **Severity:** HIGH
- **Area:** Deletion audit / accountability
- **Description:** Stage 1 now atomically records deletion actor, target UUID, action, outcome and time, surviving technician deletion. Reason, reviewed profile version, append-only enforcement and retention/access policy remain undefined.
- **Why it matters:** Operators cannot reconstruct who removed a person or distinguish authorized deletion from abuse.
- **Evidence:** `delete_technician`, `hub/audit/models.py`, Stage 1 worker deletion tests, and `test_version_guard_preserves_stage1_delete_audit`. A stale rejection writes no successful deletion event; a successful deletion retains the manager and target identity.
- **Recommended remediation:** Design an append-only audit trail with actor identity and minimal non-sensitive tombstones, retention and access policy. Preserve atomic deletion semantics. Stage 1 supplies identity and the transactional event; retention and append-only guarantees remain outside this reconciliation.
- **Required before milestone:** BEFORE INTERNAL PILOT
- **Audit evidence:** Telegram events and `technician.deleted` survive deletion because target_id has no cascade FK; actor_id becomes null if the manager is deleted. Existing regression confirms this. Retention, append-only enforcement and durable actor attribution still lack a policy.
- **Status:** OPEN

## TD-011: Sensitive data protection

- **Severity:** HIGH
- **Area:** Sensitive data protection
- **Description:** License ID and SSN last4 are plaintext database columns and readable in the detail endpoint.
- **Why it matters:** Database/backup compromise or unauthorized profile access exposes sensitive identifiers.
- **Evidence:** Technician model, TechnicianDetail schema and profile-panel.tsx. Full SSNs are rejected; forms mask last4, but masking is not encryption.
- **Recommended remediation:** Before real personal data: field access policy, encryption with keys outside the database, rotation/recovery, secure backups and log redaction tests. Deferred by explicit Stage 0 scope; do not populate real identifiers.
- **Required before milestone:** BEFORE INTERNAL PILOT
- **Status:** OPEN

## TD-012: Deployment / credentials / origins

- **Severity:** MEDIUM
- **Area:** Deployment / credentials / origins
- **Description:** Compose still defaults to local sample credentials and HTTP. Stage 1 adds a production cookie configuration gate, exact trusted origins, CSRF checks and bounded login/onboarding rates. Managed credentials, TLS termination, host policy and a comprehensive request-rate policy remain deployment work.
- **Why it matters:** An accidental network deployment or untrusted local browser context increases access and denial-of-service risk. CORS absence is not authentication; CSRF must be designed with future cookie sessions.
- **Evidence:** compose.yaml, core/config.py, main.py, next.config.ts and .env.example; no permissive CORS middleware found.
- **Recommended remediation:** Add a production configuration gate, unique managed credentials, TLS termination, allowed hosts/origins, session-aware CSRF controls and bounded request rates. Keep current loopback-only isolation for this prototype.
- **Required before milestone:** BEFORE INTERNAL PILOT
- **Status:** OPEN

## TD-013: Concurrent profile editing

- **Severity:** MEDIUM
- **Area:** Concurrent profile editing
- **Description:** PATCH is serialized but last writer wins; it has no expected version condition. updated_at uses ORM onupdate rather than a database trigger.
- **Why it matters:** Two operators can overwrite changes. Raw SQL writers can leave the delete version unchanged; the deletion version also excludes dependent binding/assignment changes.
- **Evidence:** TechnicianUpdate, update_technician and Timestamps; deletion now checks only the profile version.
- **Recommended remediation:** Define the record-version boundary, use conditional updates/ETags for edits, and require every sanctioned writer to advance that version. Consider a database-owned monotonic version if alternate writers are introduced.
- **Required before milestone:** BEFORE INTERNAL PILOT
- **Status:** OPEN

## TD-014: Provider state invariants

- **Severity:** MEDIUM
- **Area:** Provider state invariants
- **Description:** Provider schemas constrain enums and unique IDs but permit combinations such as CONNECTED with no identifier and GPS NONE with CONNECTED.
- **Why it matters:** Future binding code could persist states that the UI cannot interpret reliably.
- **Evidence:** `integrations/models.py` still permits contradictory status/identifier combinations at the database layer. Stage 1 Telegram services enforce a tested state machine with generations and advisory locks; completion adds atomic automatic claim, exact group actor matching, uniqueness-race and rollback tests, while the database still lacks complete status/identifier CHECK constraints; GPS remains a placeholder. Direct-writer database invariants remain incomplete.
- **Recommended remediation:** Before each provider is enabled, specify its state machine and add database constraints/transaction tests for supported combinations. Retain Stage 1 state-machine/concurrency tests; add missing database invariants in a separately scoped change.
- **Required before milestone:** BEFORE NEXT STAGE (original BEFORE STAGE 1 deadline remains overdue)
- **Audit evidence:** `test_live_schema_constraints_and_documented_gap` directly verifies deployed uniqueness/FKs/partial invitation index and reproduces CONNECTED with a null identifier. No schema change is justified without a complete state policy and existing-data repair plan; GPS is outside this audit.
- **Status:** OPEN

## TD-015: Scaling / response size

- **Severity:** MEDIUM
- **Area:** Scaling / response size
- **Description:** List and history endpoints are unpaginated. Select-in relationships load all assignment history and sensitive columns even for summaries; the dashboard downloads complete lists.
- **Why it matters:** Query count is bounded at tested sizes, but row volume and memory grow with both technicians and historical assignments.
- **Evidence:** technicians/router.py, technicians/service.py, Technician relationships and calendar_rows; scripts/audit_performance.py measures 10/50/250.
- **Recommended remediation:** When volume warrants, add paginated lists/history, aggregate dashboard counts, selected columns and active-assignment projections. Avoid speculative caching before measuring a realistic workload.
- **Required before milestone:** LATER SCALE
- **Audit evidence:** The quality audit profiles list, detail and Telegram status with bindings and pending invitations at 10/50/250 records; query counts remain bounded. Dashboard attention derives from two list requests, with no per-technician status fetching. Row/history growth remains unbounded.
- **Status:** OPEN

## TD-016: Durability / operations

- **Severity:** MEDIUM
- **Area:** Durability / operations
- **Description:** A named PostgreSQL volume is the only durability mechanism; backup restoration and recovery targets are not defined.
- **Why it matters:** Volume loss or operator error can permanently remove data and audit evidence.
- **Evidence:** compose.yaml and infrastructure; no backup/restore runbook or automated restore verification.
- **Recommended remediation:** Define RPO/RTO, encrypted off-host backups, retention, restore drills and deployment rollback. Pilot data must remain disposable until an appropriate backup process exists.
- **Required before milestone:** BEFORE PRODUCTION
- **Status:** OPEN

## TD-017: Observability / timeouts

- **Severity:** MEDIUM
- **Area:** Observability / timeouts
- **Description:** Safe error envelopes lack correlation IDs and centralized structured logging/metrics. Database/network timeout policy is implicit.
- **Why it matters:** Failures can be sanitized for users yet difficult to diagnose, and stalled requests may occupy connections too long.
- **Evidence:** core/errors.py, main.py engine configuration, health endpoint and frontend fetch.
- **Recommended remediation:** Add redacted structured events, correlation IDs, bounded connect/query/request timeouts and health/latency alerts. SQL parameter hiding, bounded worker retries, sanitized worker status events and malformed-update handling are present; they do not constitute a full application logging/timeout policy.
- **Required before milestone:** BEFORE INTERNAL PILOT
- **Audit evidence:** This audit fixes pooled advisory waiter starvation, stale polling offsets, Retry-After truncation and closed provider error codes. PostgreSQL pool-contention and worker regressions pass. Global DB deadlines, correlation IDs, alerting and lock-wait budgets remain incomplete.
- **Status:** OPEN

## TD-018: External profile images

- **Severity:** MEDIUM
- **Area:** External profile images
- **Description:** Arbitrary HTTP(S) photo URLs are loaded directly by the browser; the server does not fetch them.
- **Why it matters:** Remote hosts observe client network requests and HTTP images may fail under HTTPS. A URL can point at an intranet resource even though API SSRF is absent.
- **Evidence:** HttpUrl schema and Avatar img with no-referrer; unsafe schemes rejected by regression tests.
- **Recommended remediation:** Adopt an HTTPS-only/approved-host or managed-upload policy and CSP appropriate to deployment, balancing privacy and image compatibility.
- **Required before milestone:** BEFORE INTERNAL PILOT
- **Status:** OPEN

## TD-019: Runtime contracts

- **Severity:** LOW
- **Area:** Runtime contracts
- **Description:** Generated TypeScript contracts are compile-time only. Structurally invalid success JSON can reach the route error boundary.
- **Why it matters:** The boundary gives recovery but cannot identify which field violates the API contract.
- **Evidence:** api.ts, generated schema.d.ts, audit browser test for unexpected JSON shape.
- **Recommended remediation:** If APIs become independently deployed or accept external clients, add generated runtime schema validation and version compatibility tests at the transport boundary.
- **Required before milestone:** BEFORE PRODUCTION
- **Status:** OPEN

## TD-020: Accessibility coverage

- **Severity:** LOW
- **Area:** Accessibility coverage
- **Description:** This audit covers Chromium keyboard interaction and automated WCAG checks, not every assistive technology or browser.
- **Why it matters:** Automated checks cannot establish screen-reader usability or detect every focus/announcement issue.
- **Evidence:** e2e/audit.spec.ts; visual inspection at four desktop/tablet widths.
- **Recommended remediation:** Run a screen-reader and cross-browser acceptance pass before production, including zoom/reflow and touch controls.
- **Required before milestone:** BEFORE PRODUCTION
- **Status:** OPEN

## TD-021: Search consistency

- **Severity:** MEDIUM
- **Area:** Search consistency
- **Description:** The API matched name terms independently while the frontend required a contiguous full-name substring.
- **Why it matters:** Reversed or repeated-space searches could return different answers between UI and API.
- **Evidence:** technicians/page.tsx and list_technicians; Unicode/reversed-token API regression.
- **Recommended remediation:** Match all trimmed search terms against first or last name in both layers; retain Unicode display and UUID identity.
- **Required before milestone:** BEFORE STAGE 1
- **Status:** RESOLVED

## TD-022: Telegram membership visibility / live acceptance

- **Severity:** MEDIUM
- **Area:** Telegram provider semantics
- **Description:** New onboarding works with a regular bot member. Telegram does not guarantee third-party membership queries or departure events for such bots. Trusted linked-account group commands prove presence at claim time, not continued membership. Actual client group-add/fallback UI and permissions have not been live-tested.
- **Why it matters:** A group can remain reserved after the linked person leaves; no future sensitive workflow may assume that reservation proves current audience authorization.
- **Evidence:** Official getChatMember/Update documentation and TELEGRAM_ONBOARDING.md; fake tests prove exact actor, bot membership/send restriction, private-change revalidation and provider-failure behavior. No live provider was contacted.
- **Recommended remediation:** Before pilot, execute the documented dedicated TEST-bot acceptance and approve an explicit membership/revalidation policy. Before adding sensitive group delivery, revisit authorization/consent and reliable membership verification; never silently request admin rights or treat failed lookup as permission.
- **Required before milestone:** BEFORE INTERNAL PILOT
- **Audit evidence:** Ordinary-member send checks now include default group permissions; missing permission data fails closed. Bot removal/private blocking is observable while my_chat_member updates are delivered; third-party departures are not reliably observable. Provider failures suspend availability, and group migration requires revalidation. Manual live acceptance remains unperformed.
- **Status:** OPEN

## TD-023: Telegram abuse controls and event retention

- **Severity:** MEDIUM
- **Area:** Telegram operational reliability
- **Description:** Invitation creation is bounded per manager/technician (12 per 15 minutes), login and fixed test messages are throttled, but incoming invalid commands/ordinary private messages have no per-sender response budget. Each accepted update adds a deduplication row; no retention policy exists.
- **Why it matters:** A public bot can be flooded with unauthenticated messages, exhausting outbound quotas or delaying legitimate onboarding without guessing any token. Lifetime event accumulation increases storage cost.
- **Evidence:** worker.cycle processes up to 50 updates sequentially and emits best-effort replies; process_update persists each update; TelegramProcessedUpdate has no cleanup job. Safe generic errors and bounded polling do not prevent sender spam.
- **Recommended remediation:** Before exposing a pilot bot publicly, define per-sender/global response budgets, rate-limit observations and a safe deduplication retention window coordinated with Telegram update retention and offset recovery. Do not treat token entropy as denial-of-service protection.
- **Required before milestone:** BEFORE INTERNAL PILOT
- **Status:** OPEN

## TD-024: Telegram profile and group-title metadata freshness

- **Severity:** LOW
- **Area:** Telegram display metadata
- **Description:** User name/username and group title are bounded metadata captured during claim; subsequent username/title changes do not automatically refresh the manager display.
- **Why it matters:** A stale label can confuse operators, but cannot transfer identity or routing because IDs remain authoritative. Empty usernames and Unicode render safely.
- **Evidence:** claims.py captures metadata; lifecycle.py handles identity migration and availability rather than title/profile refresh. Quality tests prove bounded Unicode and canonical-name isolation.
- **Recommended remediation:** Add a narrowly scoped refresh policy when operational demand warrants it, preserving IDs and canonical names. Do not identify technicians by username or group title.
- **Required before milestone:** LATER SCALE
- **Status:** OPEN
