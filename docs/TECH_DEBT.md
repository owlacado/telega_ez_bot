# Technical debt register

Scope: Stage 4 durable schedule delivery following audited Stage 3 baseline `b145177`. **29 entries: 10 RESOLVED, 19 OPEN.** Unresolved severity counts: **CRITICAL 0, HIGH 2, MEDIUM 14, LOW 3**. Resolved counts remain HIGH 3, MEDIUM 7. Stage 2 adds TD-025 through TD-027 and closes no unrelated debt. See STAGE2_GOOGLE_CALENDAR_VERIFICATION.md and AUDIT_STAGE2_GOOGLE_CALENDAR.md. The independent audit adds evidence and localized remediation without closing any existing operational obligation. TD-014's historical deadline remains overdue; Stage 2 protects its own new state model but does not repair pre-existing Telegram/GPS database combinations.

Future stages must update this register when debt is discovered, resolved, or a milestone changes. RESOLVED means implemented and covered by the referenced audit checks. No CRITICAL finding was identified.

| ID     | Severity | Area                                       | Required Before       | Status   |
| ------ | -------- | ------------------------------------------ | --------------------- | -------- |
| TD-001 | HIGH     | Identity / navigation                      | BEFORE STAGE 1        | RESOLVED |
| TD-002 | HIGH     | Permanent deletion                         | BEFORE STAGE 1        | RESOLVED |
| TD-003 | MEDIUM   | Database integrity                         | BEFORE STAGE 1        | RESOLVED |
| TD-004 | MEDIUM   | Transactions / response                    | BEFORE STAGE 1        | RESOLVED |
| TD-005 | MEDIUM   | Input validation                           | BEFORE STAGE 1        | RESOLVED |
| TD-006 | MEDIUM   | Frontend mutations                         | BEFORE STAGE 1        | RESOLVED |
| TD-007 | MEDIUM   | Failure recovery                           | BEFORE STAGE 1        | RESOLVED |
| TD-008 | MEDIUM   | Accessibility / layout                     | BEFORE INTERNAL PILOT | RESOLVED |
| TD-009 | HIGH     | Authentication / authorization             | BEFORE STAGE 1        | RESOLVED |
| TD-010 | HIGH     | Deletion audit / accountability            | BEFORE INTERNAL PILOT | OPEN     |
| TD-011 | HIGH     | Sensitive data protection                  | BEFORE INTERNAL PILOT | OPEN     |
| TD-012 | MEDIUM   | Deployment / credentials / origins         | BEFORE INTERNAL PILOT | OPEN     |
| TD-013 | MEDIUM   | Concurrent profile editing                 | BEFORE INTERNAL PILOT | OPEN     |
| TD-014 | MEDIUM   | Provider state invariants                  | BEFORE NEXT STAGE     | OPEN     |
| TD-015 | MEDIUM   | Scaling / response size                    | LATER SCALE           | OPEN     |
| TD-016 | MEDIUM   | Durability / operations                    | BEFORE PRODUCTION     | OPEN     |
| TD-017 | MEDIUM   | Observability / timeouts                   | BEFORE INTERNAL PILOT | OPEN     |
| TD-018 | MEDIUM   | External profile images                    | BEFORE INTERNAL PILOT | OPEN     |
| TD-019 | LOW      | Runtime contracts                          | BEFORE PRODUCTION     | OPEN     |
| TD-020 | LOW      | Accessibility coverage                     | BEFORE PRODUCTION     | OPEN     |
| TD-021 | MEDIUM   | Search consistency                         | BEFORE STAGE 1        | RESOLVED |
| TD-022 | MEDIUM   | Telegram membership / live acceptance      | BEFORE INTERNAL PILOT | OPEN     |
| TD-023 | MEDIUM   | Telegram abuse / retention                 | BEFORE INTERNAL PILOT | OPEN     |
| TD-024 | LOW      | Telegram metadata freshness                | LATER SCALE           | OPEN     |
| TD-025 | MEDIUM   | Google credential operations               | BEFORE INTERNAL PILOT | OPEN     |
| TD-026 | MEDIUM   | Google request budgets / attempt retention | BEFORE INTERNAL PILOT | OPEN     |
| TD-027 | MEDIUM   | Google live sandbox acceptance             | BEFORE INTERNAL PILOT | OPEN     |

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
- **Stage 2 evidence:** Google connection, scan, assignment, exclusion, restore, and revocation outcomes now use the same safe transactional audit boundary. No token, authorization code, or state is included. Retention, append-only enforcement, and durable attribution remain OPEN.
- **Independent Stage 2 audit evidence:** Independent Google audit: assignment/exclusion/restore no-ops no longer create misleading history. Actor/target/time and failed-callback attribution tests pass. Technician deletion still cascades assignment history; manager deletion can null audit actor IDs. An approved retention/append-only policy remains required.
- **Status:** OPEN

## TD-011: Sensitive data protection

- **Severity:** HIGH
- **Area:** Sensitive data protection
- **Description:** License ID and SSN last4 are plaintext database columns and readable in the detail endpoint.
- **Why it matters:** Database/backup compromise or unauthorized profile access exposes sensitive identifiers.
- **Evidence:** Technician model, TechnicianDetail schema and profile-panel.tsx. Full SSNs are rejected; forms mask last4, but masking is not encryption.
- **Recommended remediation:** Before real personal data: field access policy, encryption with keys outside the database, rotation/recovery, secure backups and log redaction tests. Deferred by explicit Stage 0 scope; do not populate real identifiers.
- **Required before milestone:** BEFORE INTERNAL PILOT
- **Stage 2 evidence:** Provider refresh tokens and pending PKCE verifiers now use authenticated Fernet encryption with an external key and versioned envelope. Ciphertext corruption/wrong-key/plaintext-mutation tests pass. DL/SSN columns and access policy are unchanged; this HIGH item remains OPEN.
- **Independent Stage 2 audit evidence:** Independent Google audit: actual PostgreSQL ciphertext, wrong-key/corruption, secret-bearing provider errors, SDK logger namespaces, public schemas and browser storage are tested. Calendar lists now select only assignee UUID/name, avoiding unnecessary sensitive profile hydration. Existing plaintext DL/SSN and profile authorization policy are unchanged.
- **Status:** OPEN

## TD-012: Deployment / credentials / origins

- **Severity:** MEDIUM
- **Area:** Deployment / credentials / origins
- **Description:** Compose still defaults to local sample credentials and HTTP. Stage 1 adds a production cookie configuration gate, exact trusted origins, CSRF checks and bounded login/onboarding rates. Managed credentials, TLS termination, host policy and a comprehensive request-rate policy remain deployment work.
- **Why it matters:** An accidental network deployment or untrusted local browser context increases access and denial-of-service risk. CORS absence is not authentication; CSRF must be designed with future cookie sessions.
- **Evidence:** compose.yaml, core/config.py, main.py, next.config.ts and .env.example; no permissive CORS middleware found.
- **Recommended remediation:** Add a production configuration gate, unique managed credentials, TLS termination, allowed hosts/origins, session-aware CSRF controls and bounded request rates. Keep current loopback-only isolation for this prototype.
- **Required before milestone:** BEFORE INTERNAL PILOT
- **Stage 2 evidence:** Google configuration fails closed when enabled without a valid encryption key/client/redirect configuration; callback origin is validated and demo creation/assignment is blocked in production. Existing TLS, managed credentials and deployment policy are still required. Compose environment values must be protected by the operator.
- **Independent Stage 2 audit evidence:** Independent Google audit: production fake-provider/missing-key gates, manager authorization, exact origins and mutation CSRF remain enforced. Real cross-site browser navigation exposed the Strict-cookie callback failure; protected OAuth start now reissues the same session as Lax without extending lifetime or removing HttpOnly/Secure. The two-loopback-site browser regression passes. Separate Google lock connections require deployment PostgreSQL capacity budgeting; the audit stack is loopback-only and fake-only. No production credentials/TLS policy has been supplied.
- **Status:** OPEN

## TD-013: Concurrent profile editing

- **Severity:** MEDIUM
- **Area:** Concurrent profile editing
- **Description:** PATCH is serialized but last writer wins; it has no expected version condition. updated_at uses ORM onupdate rather than a database trigger.
- **Why it matters:** Two operators can overwrite changes. Raw SQL writers can leave the delete version unchanged; the deletion version also excludes dependent binding/assignment changes.
- **Evidence:** TechnicianUpdate, update_technician and Timestamps; deletion now checks only the profile version.
- **Recommended remediation:** Define the record-version boundary, use conditional updates/ETags for edits, and require every sanctioned writer to advance that version. Consider a database-owned monotonic version if alternate writers are introduced.
- **Required before milestone:** BEFORE INTERNAL PILOT
- **Independent Stage 2 audit evidence:** Independent Google audit: destructive Google account replacement now binds confirmation to a digest of calendar identity/name/exclusions and active assignments, revalidated at start and callback. This narrowly fixes replacement impact; general concurrent profile editing and deletion version boundaries remain OPEN.
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
- **Stage 2 evidence:** New Google source/identity, connection status/credential, account identity and current-connection constraints are database enforced; raw uniqueness and migration constraint tests cover them. Existing Telegram/GPS gaps remain unchanged and OPEN; no claim is made that Stage 2 closes this historical blocker.
- **Independent Stage 2 audit evidence:** Independent Google audit: direct deployed unique constraints were removed temporarily and corresponding tests failed; constraints were restored and drift checked. OAuth manager/session ownership remains enforced in the authenticated service; independent FKs do not constitute a composite manager/session constraint for arbitrary SQL writers. Historical Telegram/GPS policy gaps are unchanged.
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
- **Independent Stage 2 audit evidence:** Independent Google audit: scripts/audit_google_performance.py now profiles 10/50/250/1000 calendars with four assignment-history rows per technician. Calendar list projection reduces 1000-row query count from 10 to 2 and avoids profile/history hydration; technician lists still load history (10 queries at 1000), dashboard still downloads full lists, and response bytes grow linearly. Identical rescans deliberately write one last_seen_at per calendar and one scan audit event; 1000 rows is measured, not an unlimited scale guarantee. Browser search/filter/layout checks cover the same four sizes. The final loaded production run measured 1000-row render/filter check wall times of 732/2081 ms (including Playwright assertions while backend verification ran); smaller prior samples were faster. DOM/list virtualization or pagination should follow a defined scale target, not an assumed constant-time UI.
- **Status:** OPEN

## TD-016: Durability / operations

- **Severity:** MEDIUM
- **Area:** Durability / operations
- **Description:** A named PostgreSQL volume is the only durability mechanism; backup restoration and recovery targets are not defined.
- **Why it matters:** Volume loss or operator error can permanently remove data and audit evidence.
- **Evidence:** compose.yaml and infrastructure; no backup/restore runbook or automated restore verification.
- **Recommended remediation:** Define RPO/RTO, encrypted off-host backups, retention, restore drills and deployment rollback. Pilot data must remain disposable until an appropriate backup process exists.
- **Required before milestone:** BEFORE PRODUCTION
- **Stage 2 evidence:** Encrypted Google credentials make protected key recovery part of backup/restore. The runbook describes coordinated DB/key backups and refuses destructive downgrade with provider data. An automated restore drill and defined recovery targets are still absent.
- **Independent Stage 2 audit evidence:** Independent Google audit: supported downgrade/re-upgrade preserves catalog/history, while provider-data destructive downgrade rolls back atomically. Recovery must coordinate protected database and external encryption-key backups; restoring either alone cannot establish usable authorization. No backup infrastructure or recovery drill was added.
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
- **Stage 2 evidence:** Google network calls have bounded connect/read timeouts, closed error codes, full Retry-After deadlines, safe audits, query redaction and no SQL transaction across external calls. Global deadlines, correlation/alerts, and ingress log policy remain OPEN.
- **Independent Stage 2 audit evidence:** Independent Google audit: Google advisory ownership now uses separate NullPool connections, freeing transaction-pool capacity; actual two-owner/small-pool and no-idle-transaction tests pass. Token refresh serializes with lifecycle; cancelled worker-thread calls retain the enclosing guard until the bounded call finishes. Retry headers include token endpoint, quota 403, HTTP-date ceiling and finite extreme deadlines. Individual connect/read timeouts and 1000-page cap are not an overall request deadline; stalled pagination, SDK retries, repeated cancellation/shutdown and database/lock waits still require deployment budgets. Status exposes current state, last success/error and persisted retry; last failure time requires audit lookup, and scan-in-progress is not persisted.
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
- **Stage 2 evidence:** The complete calendar connection/assignment/exclusion workflow passes Chromium browser tests; existing four-width layout and automated accessibility checks still pass. Manual screen-reader and cross-browser acceptance remains OPEN.
- **Independent Stage 2 audit evidence:** Independent Google audit: malicious-looking HTML/Markdown/RTL/emoji calendar metadata is rendered as text, bounded layout is browser-tested, and stale assignment conflict recovery is covered. Cross-browser, assistive-technology and zoom acceptance remain unperformed.
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

## TD-025: Google credential rotation, revocation and recovery operations

- **Severity:** MEDIUM
- **Area:** Provider credential operations
- **Description:** Refresh tokens are encrypted and disconnect/switch revoke best-effort after local deletion. There is no durable revocation outbox or automated in-place key re-encryption. A crash after local deletion can leave the remote grant valid; a wrong/lost key requires protected recovery or deliberate reconnect.
- **Why it matters:** Operators need a tested credential incident and recovery procedure before pilot data or real grants are accepted.
- **Evidence:** SecretCipher, Google lifecycle advisory guard, generation checks, corruption tests, revocation-failure tests, and GOOGLE_CALENDAR_INTEGRATION.md. Same-account reconnect deliberately avoids project-wide revocation of the new token.
- **Recommended remediation:** Approve and rehearse the documented manual stop/disconnect/rotate/reconnect procedure and secure key backup. Add a durable, encrypted revoke workflow and managed rotation when real deployments require unattended recovery; preserve Google's project-wide revocation semantics.
- **Required before milestone:** BEFORE INTERNAL PILOT
- **Independent Stage 2 audit evidence:** Independent Google audit: reconnect without a new token now decrypts and refreshes the old grant and verifies its primary account identity; revoked/corrupt/cross-account reuse is rejected. Rotated scan credentials are encrypted and committed before pagination, serialized against reconnect/disconnect. Revocation HTTP 400 is success only for invalid_token. The v1 prefix identifies envelope format, not a key ID; changing the sole key makes old credentials and pending verifiers unreadable until the original key is restored or accounts reconnected. External exchange/rotation cannot be atomic with PostgreSQL: a crash or commit failure can still orphan a grant, and a crash/revocation/audit-write failure after local commit requires operator recovery. Python immutable token strings are short-lived but cannot promise cryptographic memory zeroization. These operational limitations remain OPEN.
- **Status:** OPEN

## TD-026: Google request budgets and OAuth-attempt retention

- **Severity:** MEDIUM
- **Area:** Provider quota and storage operations
- **Description:** Scan concurrency is bounded and provider Retry-After is persisted; permanent authorization failures stop scans until reconnect. Authenticated managers can still start many OAuth attempts or perform many successful sequential scans. Consumed/expired attempt metadata has no pruning policy.
- **Why it matters:** Trusted-manager misuse or a compromised session could exhaust Google quota or increase database storage. Encrypted expired verifiers may persist until a new same-session start or session deletion.
- **Evidence:** OAuth start invalidates prior same-session attempts; scan guard rejects overlapping requests; Google failure/backoff regressions pass. No per-manager OAuth or successful-scan budget is configured.
- **Recommended remediation:** Before shared pilot use, establish per-manager/global OAuth and scan budgets and a safe attempt-retention policy. Keep single-use state and replay protection intact; use sanitized quota observations.
- **Required before milestone:** BEFORE INTERNAL PILOT
- **Independent Stage 2 audit evidence:** Independent Google audit: same/different snapshot scans, page-three failure, looping/malformed continuation, conflicting duplicate IDs and the 1000-page cap are exercised. Quota 403 and token-endpoint 429 now preserve retry semantics across provider recreation. Successful scans/OAuth starts still lack per-manager/global quotas; lifecycle waiters may open transient dedicated connections, so DB connection and request admission limits remain necessary. Expired verifier pruning remains absent.
- **Status:** OPEN

## TD-027: Google OAuth and CalendarList live sandbox acceptance

- **Severity:** MEDIUM
- **Area:** External-provider acceptance
- **Description:** All automated tests use fake providers or synthetic HTTP responses. Actual consent screens, consent/project configuration, test-account refresh lifetime, primary CalendarList identity behavior, revocation, and hidden/shared-calendar visibility have not been exercised with Google.
- **Why it matters:** Fake tests prove application logic but cannot establish Google account/project configuration correctness.
- **Evidence:** GOOGLE_CALENDAR_INTEGRATION.md contains a dedicated TEST-account runbook and official references. Backend and Playwright guards prohibit live Google calls. No real Google account/calendar was contacted.
- **Recommended remediation:** Perform and record that manual runbook with dedicated test accounts/project; verify narrow scope and sanitize evidence. Approve consent-screen and deployment settings before any operational account is connected.
- **Required before milestone:** BEFORE INTERNAL PILOT
- **Independent Stage 2 audit evidence:** Independent Google audit: expanded fake transport/PostgreSQL/browser tests and ten mutation experiments do not replace real consent, primary identity, refresh lifetime or project-wide revocation acceptance. No accounts.google.com, oauth2.googleapis.com, www.googleapis.com or real account/API was contacted. Dedicated TEST acceptance remains explicitly manual and OPEN.
- **Status:** OPEN

## Stage 3 evidence (existing debt IDs retained)

No new debt ID is needed and no existing item is resolved by Stage 3. The counts above remain unchanged.

- **TD-015, LATER SCALE:** Day reads are bounded to 100 pages/10,000 events/8 MB; UI wraps and scrolls.
  Large event-day pagination/virtualization and optional durable caching require measured operational
  demand. No local event mirror is created merely to anticipate scale.
- **TD-017, BEFORE INTERNAL PILOT:** Event network I/O stays outside SQL transactions. The provider has
  per-call timeouts and a 45-second pagination budget checked between reads; this is not a hard
  end-to-end deadline across lifecycle waiting/current blocking I/O. Admission/shutdown and correlated
  provider metrics still need operational policy.
- **TD-025, BEFORE INTERNAL PILOT:** Scope upgrades preserve encryption and verify omitted-token
  capability. Rotated event refresh grants commit before pagination. Provider rotation/DB commit
  cannot be atomic; key rotation, crash recovery and durable revocation remain open.
- **TD-026, BEFORE INTERNAL PILOT:** One event read per technician at a time plus UI deduplication
  suppresses overlapping requests. This does not impose cross-technician/manager quotas or bound all
  lifecycle waiters. Establish request budgets and attempt retention before shared use.
- **TD-027, BEFORE INTERNAL PILOT:** Extend dedicated Google TEST acceptance to incremental event
  consent/partial grants, recurring exceptions, calendar ACL/private events, provider timezone/DST,
  pagination and refresh. Automated tests use fakes only; the runbook is not executed automatically.
- **TD-010/011/014:** Durable audit retention, sensitive technician-field encryption and pre-existing
  Telegram/GPS database invariants remain open. Stage 3 does not persist event PII; API responses are
  no-store and logs exclude event content. Overdue TD-014 remains explicitly unclosed.

Internal-pilot blockers remain TD-010/011/012/013/014/017/018/022/023/025/026/027.
Production additionally requires TD-016/019/020. TD-015/024 remain LATER SCALE.

## Independent Stage 3 quality audit

Evidence: [AUDIT_STAGE3_CALENDAR_EVENTS.md](AUDIT_STAGE3_CALENDAR_EVENTS.md).
No new ID and no closure; 27 entries, 10 RESOLVED / 17 OPEN remain accurate.

| Existing obligation      | Stage 3 audit disposition                                                                                                                                                                                                                                                                                       |
| ------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| TD-010 / TD-011          | OPEN: durable deletion accountability and sensitive profile-field protection remain HIGH. Event no-store/log-redaction does not resolve profile storage.                                                                                                                                                        |
| TD-012 / TD-013 / TD-014 | OPEN: deployment approval, optimistic profile editing and pre-existing provider-state invariants are unchanged. TD-014 remains overdue.                                                                                                                                                                         |
| TD-015                   | PARTIAL remediation, status OPEN: 500-job projection cap fails explicitly; actual Chromium renders 500 jobs without horizontal overflow. Broader list scaling and measured future cache/privacy policy remain later-scale work, not authorization to add an event mirror.                                       |
| TD-017                   | PARTIAL remediation, status OPEN: safe event outcome codes now distinguish success/empty/stale/rate/invalid data; unexpected 500s retain privacy headers. Six slow reads leave the transaction pool available. Hard end-to-end deadlines, lifecycle admission, shutdown and operational monitoring remain open. |
| TD-018 / TD-022 / TD-023 | OPEN: external images, Telegram live membership acceptance and bot abuse/retention are not addressed by event reads.                                                                                                                                                                                            |
| TD-025                   | OPEN: concurrent upgrade/disconnect/replacement and event fetch pass, but refresh/DB atomicity, key recovery and durable revocation remain operational obligations.                                                                                                                                             |
| TD-026                   | PARTIAL remediation, status OPEN: per-technician refresh coalescing and bounded event projection are covered. Global/per-manager quota admission and expired attempt retention remain absent.                                                                                                                   |
| TD-027                   | OPEN: fake transport/browser tests and official documentation review do not replace dedicated Google TEST consent, ACL/private-event, recurrence and DST acceptance. No live acceptance was performed.                                                                                                          |
| TD-016 / TD-019 / TD-020 | OPEN: additional production durability, runtime-contract and accessibility obligations remain.                                                                                                                                                                                                                  |
| TD-024                   | OPEN: Telegram display metadata freshness remains later-scale work.                                                                                                                                                                                                                                             |

All twelve listed pilot blockers remain blockers. Production additionally requires TD-016/019/020.
The fixed audit defects are documented in the audit report; they do not create unresolved debt IDs.

## Stage 4 debt disposition

No existing obligation is closed by schedule delivery. The original twelve pilot
blockers remain TD-010/011/012/013/014/017/018/022/023/025/026/027; TD-014 remains
explicitly overdue. Production additionally requires TD-016/019/020. TD-015/024
remain later-scale items. New Stage 4 obligations are the two concrete items below.
Current totals: 29 entries, 10 RESOLVED, 19 OPEN; open severities 0 CRITICAL,
2 HIGH, 14 MEDIUM, 3 LOW. Historical stage totals above describe their own stages.

| ID     | Severity | Area                                        | Required Before       | Status |
| ------ | -------- | ------------------------------------------- | --------------------- | ------ |
| TD-028 | MEDIUM   | Schedule delivery dedicated TEST acceptance | BEFORE INTERNAL PILOT | OPEN   |
| TD-029 | MEDIUM   | Schedule payload keys and worker operations | BEFORE INTERNAL PILOT | OPEN   |

### TD-028 - Combined schedule acceptance

Official docs, fake transport, PostgreSQL concurrency tests, and browser tests do
not replace the dedicated Google TEST + Telegram TEST acceptance runbook in
SCHEDULE_DELIVERY.md. Validate actual membership changes, message HTML/limits,
callbacks, late acknowledgements, local-time automatic delivery and uncertainty
recovery using only the owner's test account/group and fake jobs. Record acceptance
before pilot. No real-provider acceptance was executed during implementation.

### TD-029 - Payload key and separate worker operations

Before pilot, own secret-store provisioning, backup/recovery and reviewed key
rotation for SCHEDULE_PAYLOAD_ENCRYPTION_KEY; monitor schedule_worker_states,
backlogs, expired claims, ambiguity and the seven-day ciphertext purge. A stopped
worker delays purging; durable DB backups need matching retention controls.
Multiple workers are claim-safe, but operational alerting, rotation automation,
and measured worker capacity remain deployment obligations. Historical metadata
and callback abuse/retention are also covered by existing TD-023, not hidden as
new feature scope.

Stage 4 re-evaluation of existing blockers: TD-010/011 remain HIGH (accountability
and profile encryption); TD-012 remains deployment/origin/credential approval;
TD-013 remains profile optimistic concurrency; TD-014's old Telegram/GPS state
invariants are unchanged. TD-017 gains safe dispatch result codes and heartbeat
rows but retains hard deadline/admission/monitoring work. TD-018 external image
handling is unchanged. TD-022 remains live Telegram acceptance; TD-023 remains
abuse and metadata retention. TD-025 remains Google key/revoke/crash operations;
TD-026 retains global request admission and attempt retention; TD-027 remains real
Google sandbox acceptance. The new workflow is production-shaped, not pilot or
production approval. Future features are not added as debt.

## Independent Stage 4 reliability audit disposition

No new debt ID and no closed obligation: **29 entries, 10 RESOLVED, 19 OPEN**;
open severities remain 0 CRITICAL, 2 HIGH, 14 MEDIUM, 3 LOW.

- **TD-028: OPEN.** Official Telegram documentation, hard-death probes, concurrent
  fake-provider delivery, and browser checks do not substitute for combined dedicated
  TEST Google/Telegram acceptance. No such acceptance was performed.
- **TD-029: PARTIAL remediation, status OPEN.** Database-clock periodic heartbeats,
  stale-worker operator health, bounded shutdown, immutable receipts, fallback
  provenance, recovery of expired retired-bot work, and guarded rollback are implemented. New definitive failures purge
  unnecessary ciphertext immediately; existing legacy payloads retain their seven-day
  cleanup. Secret-store provisioning, key rotation/recovery exercises, fleet capacity,
  alert routing, metadata/backup retention, and ambiguous-outcome review ownership
  remain pilot requirements. A whole-evening outage cannot reconstruct a historical
  missed-decision row the next morning; external uptime/queue monitoring must detect it.
- **TD-017/026: PARTIAL remediation, status OPEN.** Five paused sends leave a two-slot
  transaction pool responsive. Scheduling and delivery progress independently. The
  measured due-decision cost is linear (23N + 1 SQL statements); every eligible
  technician still needs an authoritative provider projection. Global request admission,
  queue-age alerts, and deployment-scale timing remain open.
- **TD-010/011: OPEN, HIGH.** Immutable Stage 4 receipts do not resolve deletion audit
  retention or plaintext sensitive technician profile fields.
- **TD-012/013/014/018/022/023/025/027: OPEN.** Deployment/origin approvals, optimistic
  profile editing, legacy provider invariants (TD-014 overdue), external profile images,
  real Telegram membership acceptance, abuse/metadata retention, Google credential
  operations, and live Google acceptance remain unchanged.
- **TD-016/019/020: OPEN, additional production gates.** Backup/restore durability,
  runtime contracts, and accessibility acceptance remain unfulfilled.
- **TD-015/024: OPEN, LATER SCALE.** Broader list scaling and Telegram display metadata
  freshness remain later-scale obligations.

All fourteen pilot blockers remain TD-010/011/012/013/014/017/018/022/023/025/026/027/
028/029; production additionally requires TD-016/019/020. Neither pilot nor production
is approved. Provider-side exactly-once/idempotent sendMessage is unavailable to this
workflow: uncertainty is terminal and only confirmed manager resend may create a new
attempt. This is an explicit operating constraint within TD-028/029, not a promised
future product feature.
