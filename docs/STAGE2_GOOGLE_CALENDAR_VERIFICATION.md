# Stage 2 Google Calendar verification

Starting branch: `codex/stage1-telegram-quality-audit`. Starting HEAD: `37c779127e955d1e505cabea8ed89f66cfe04e8f`, verified clean before branching. Implementation branch: `codex/stage2-google-calendar`. Intended commit: `feat: add Google Calendar discovery and assignment`. No push is authorized or performed. The final commit hash is reported in the task response; this document is part of that commit.

## Scope and implementation

Manager OAuth connection, encrypted offline credentials, complete CalendarList discovery, local availability, assignments/history, exclusion/restore, disconnect/reconnect, deliberate account switching, manager UI and audit are implemented. Events, jobs, schedules, periodic polling, dispatch, accounting, GPS and Sheets remain outside Stage 2. See [the integration runbook](GOOGLE_CALENDAR_INTEGRATION.md) for architecture, exact official references, endpoints and manual acceptance.

- Official `google-auth-oauthlib==1.4.1`, `google-auth==2.58.0` and `cryptography==50.0.1` are pinned with transitive dependencies in requirements.lock.
- Scope is only `calendar.calendarlist.readonly`. The library handles S256 PKCE; state is random, hashed, expiring, single-use and bound to the authenticated manager/session. Completion revalidates session activity and connection generation.
- Fernet `v1:` envelopes encrypt refresh tokens and pending verifiers. Access tokens remain in memory. Authorization codes, client secrets and encryption keys are absent from PostgreSQL models/public responses. Configuration errors suppress raw inputs.
- A primary CalendarList ID establishes opaque account identity without an extra identity scope. One current connection is DB-enforced; same-account reconnect can retain an omitted refresh token, while different-account replacement requires explicit confirmation.
- All provider pages finish before reconciliation. The provider test fetches 100 + 100 + 37 entries. Repeated scans reuse UUIDs; title changes update metadata; missing calendars become unavailable; partial scans cannot mark unseen records unavailable.
- Exclusion is a durable local flag. Assigned exclusion checks the expected assignee, unassigns atomically and preserves history. Rescans retain exclusion; Restore clears it deliberately. No Google calendar delete operation exists.
- Both active assignment indexes remain intact. Assignment/reassignment/unassignment/exclusion/reconciliation serialize through a transaction advisory lock. A deleted target technician rolls back a failed calendar transfer.
- Disconnect deletes the local encrypted credential first, preserves catalog/assignments, then attempts revoke. Lifecycle coordination prevents an old revocation racing a new reconnect. Switching account revokes the replaced credential best-effort; same-account reconnect avoids project-wide revocation of the new token.
- Cards and detail show unavailable warnings; detail/add flows filter ineligible choices. The Calendars page adds connection actions, search/filter, assignment changes, exclusion confirmation, and restore. Mutation controls lock while pending and preserve errors for recovery.

## Verification gate

All required gates below passed on the final implementation before commit.

| Check                            | Result / evidence                                                                                                                                           |
| -------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Full backend PostgreSQL          | 278 passed (272.52 seconds), final source                                                                                                                   |
| Google-focused suite             | 59 passed within the final full run; 57 also passed standalone before the two added scope cases                                                             |
| Stage 0 regression               | 86 passed: API 33, Stage 0 audit 38, auth 15 (within full run)                                                                                              |
| Telegram full/focused regression | 133 passed: onboarding 28, completion 42, worker 25, focused quality audit 38 (within full run)                                                             |
| Concurrency selection            | 22 passed, 256 deselected; includes Google and existing Telegram races                                                                                      |
| Frontend                         | 55 passed across 5 files                                                                                                                                    |
| Development Playwright           | 11 passed (3.0 minutes), final development source                                                                                                           |
| Production-image Playwright      | 11 passed (2.3 minutes), final production images                                                                                                            |
| Production build                 | PASS: Next production app, standalone API/web Docker images                                                                                                 |
| Strict TypeScript / ESLint       | PASS                                                                                                                                                        |
| Ruff / Python formatting         | PASS; 86 files checked                                                                                                                                      |
| Prettier                         | PASS across all matched project files                                                                                                                       |
| Contract snapshot                | PASS; OpenAPI matches running app                                                                                                                           |
| Deterministic generation         | PASS; OpenAPI and generated TypeScript SHA-256 unchanged on regeneration                                                                                    |
| Alembic                          | PASS; fresh and populated upgrade, supported downgrade/re-upgrade, one head, zero detected schema drift in native checks and the final running Docker image |
| Provider-data downgrade safety   | PASS; downgrade refuses with Google data and leaves catalog/assignment history intact                                                                       |
| Compose / startup                | PASS; isolated DB/API/web startup and health                                                                                                                |
| Secret scan / diff whitespace    | PASS; no findings; final scan repeated after report formatting                                                                                              |
| Temporary mutations              | Five protections broken temporarily; every targeted regression failed; source restored byte-for-byte                                                        |

The disposable native PostgreSQL database is `technician_hub_test` on loopback 5439. Production-image verification uses a separate Compose project `technician-hub-stage2-google`, ports 3005/8005/5442, APP_ENV=test and fake providers. Tests/migrations using a given database are sequential. The original user application/Telegram containers are not reset or replaced. Dedicated verification containers are stopped after completion.

Local ignored evidence is under `.local/stage2-*.log`; browser screenshots are under `apps/web/test-results/{development,production}`. Logs are not committed. Production screenshots at 1920/1440/1366/1024 widths passed the existing overflow/accessibility checks; the 1920 Calendars image was visually inspected. Long calendar names truncate with their complete title available, and long technician names remain inside the table.

## Adversarial and mutation evidence

The Google tests cover state hashing, expiration, replay, duplicate callbacks, duplicate parameters, denial/missing code, wrong session and different manager, session revocation during exchange, PKCE/offline/scope construction, absent key, corrupted ciphertext/wrong key, incremental scope changes, omission of refresh token on reconnect, deliberate account replacement, provider-ID collisions across accounts, and direct DB uniqueness constraints.

They also exercise pagination/237 entries, repeated-page tokens, malformed metadata/body, page-two failure, rename/add/missing-calendar reconciliation, persistent exclusions, explicit restore, assigned removal confirmation, stale assignee, deletion during transfer, competing assignments, two scans, disconnect during scan, permanent auth/scope failures, timeout/5xx/429, retry recovery and Retry-After over one day, revocation failure, safe provider exceptions, route authorization and CSRF, production demo restrictions, and callback query redaction before access logging.

| Temporary mutation                                 | Targeted regression                | Outcome |
| -------------------------------------------------- | ---------------------------------- | ------- |
| Remove session binding                             | wrong-manager-session callback     | KILLED  |
| Return plaintext from SecretCipher.encrypt         | encrypted state/credential test    | KILLED  |
| Clear exclusion during reconciliation              | exclusion/rescan/history test      | KILLED  |
| Stop after first CalendarList page                 | 237-calendar pagination test       | KILLED  |
| Mark unavailable after a transient/partial failure | page-two failure preserves catalog | KILLED  |

The mutation runner initially could not find its final multiline target because of CRLF normalization; it changed no source for that attempt. The target was corrected, the fifth regression failed as intended, and every modified file was restored by a finally block and byte checksum. Mutation scripts and logs remain ignored, outside the commit.

## Final self-review and fixes

No unresolved CRITICAL/HIGH finding was identified in the new Stage 2 implementation. Existing HIGH debt TD-010 and TD-011 remains open and blocks a real-data pilot. Review covered OAuth ownership/replay/PKCE, credential serialization, callback logging, scope handling, lock ordering, generation races, scan atomicity, assignment/exclusion history, fake-provider guards, schema rollback, and frontend stale/pending state.

Review fixes included server-side production demo eligibility (including profile/create assignment), preserving long Retry-After deadlines, revoking replaced-account credentials without revoking same-account refresh grants, rejecting ambiguous empty provider bodies, suppressing configuration input in validation errors, handling the official library's incremental-scope warning with required-scope verification, and reading callback result through Next query state without synchronous effect state changes. The migration explicitly adds CHECK constraints omitted by Alembic autogeneration and refuses destructive downgrade after provider adoption.

Audit events contain action, actor, target UUID, outcome and time, without secret payloads. Models and response schemas were reviewed for authorization codes/access tokens/client secrets/keys; production browser assertions check status responses and browser storage. Automated backend transport blocks Google domains and browser tests block non-loopback network. Synthetic test literals are deliberately fake; no real credential was used. Git-visible secret patterns include Google access/refresh/client-secret formats, private keys, session cookies and Telegram credentials. Generated bundles and runtime logs were reviewed separately for synthetic secret exposure.

## Debt and acceptance limits

No existing debt item is closed by Stage 2. TD-010 audit retention/append-only policy and TD-011 plaintext DL/SSN remain HIGH and OPEN. TD-014's older Telegram/GPS database gaps remain overdue; the new Google schema has its own supported invariants. Existing deployment, concurrent-profile edits, backup/restore, observability, external-image, runtime-contract, accessibility and Telegram acceptance/abuse obligations remain as documented.

New OPEN MEDIUM items: TD-025 key rotation/revocation/recovery operations; TD-026 Google request budgets and OAuth-attempt retention; TD-027 dedicated Google sandbox acceptance. The register now has 27 entries: 10 RESOLVED, 17 OPEN; unresolved severity counts CRITICAL 0, HIGH 2, MEDIUM 12, LOW 3.

Before an internal pilot, resolve or explicitly satisfy the register's pilot requirements, including secure deployment, audit/personal-data policy, operator credential recovery, request budgets and dedicated provider acceptance. Before production, additionally complete tested DB/key restore, production runtime/cross-browser/accessibility controls and all earlier blockers. This stage does not claim production readiness.

[GOOGLE_CALENDAR_INTEGRATION.md](GOOGLE_CALENDAR_INTEGRATION.md) provides the exact later manual TEST-account procedure: configure a dedicated project/OAuth client and redirect, enable Calendar API, supply protected environment/key, connect, scan, verify names, assign a fictional technician, disconnect/preserve, reconnect/recover, and test exclusion/account switching. That live acceptance was not performed. Official documentation was read; no real Google account/calendar or live Google API was contacted by implementation verification.
