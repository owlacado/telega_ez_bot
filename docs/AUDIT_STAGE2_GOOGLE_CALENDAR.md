# Stage 2 Google Calendar independent quality audit

## Baseline and pre-change architecture map

Audit began on 2026-09-17 from clean `codex/stage2-google-calendar`, commit
`be8b713a0d5c9659038bc96d1cecdf27808bcafb`. Work is isolated on
`codex/stage2-google-calendar-quality-audit`; no push or live Google access is authorized.
This map was recorded before implementation changes.

- Manager cookie authentication, exact-origin/CSRF middleware protect mutations. The callback is an authenticated GET; outer middleware captures its query then removes it from the ASGI scope before downstream logging. Responses redirect to a fixed, code-free calendar URL.
- OAuth attempts persist SHA-256 state, manager/session IDs, ten-minute expiry, encrypted PKCE verifier, expected connection/generation and CONNECT/RECONNECT/SWITCH intent. A row lock burns state and clears its verifier before exchange. Completion revalidates the manager session and connection generation.
- SecretCipher uses authenticated Fernet with a `v1:` format prefix and one externally configured key. CalendarConnection holds encrypted refresh credentials, provider-primary-calendar account identity, generic display label, generation, current/status flags, scopes, scan and backoff metadata. Partial unique index permits one current account.
- GoogleCalendarProvider is the only external HTTP boundary: official OAuth/PKCE library, token exchange/refresh/revoke, and bounded-page CalendarList reads. FakeCalendarProvider is restricted by startup configuration to an isolated test database. No calendar event, calendar deletion or credential-injection HTTP route exists.
- Session advisory guards serialize lifecycle work and reject overlapping scans. Their owners retain one AUTOCOMMIT connection across provider I/O; waiters return connections. Provider calls occur outside SQL transactions. A transaction advisory lock serializes calendar mutations; generation checks reject stale scans after lifecycle changes.
- Complete normalized provider results reconcile by `(connection UUID, provider calendar ID)` in one transaction. Missing rows become unavailable, never deleted. Exclusion timestamps/actors and assignments survive scans, rename and reconnect. Account switching makes old calendars unavailable, clears old credentials, activates the new account, then attempts remote revocation.
- CalendarAssignment records historical assignments, with two partial unique indexes for active technician/calendar ownership. Assignment changes lock technician/calendar rows; exclusions detach atomically. Technician deletion cascades assignment history; calendar deletion retains inactive name snapshots with nullable calendar FK.
- Safe audit events record manager, target, action, timestamp and outcome. Provider errors use closed codes. Connection/account identifiers and encrypted secrets are excluded from public schemas; authorization URLs are intentionally returned only to the initiating manager.
- Connection panel obtains status and launches OAuth/scan/disconnect; calendar table manages assignment/exclusion with expected owner; technician detail offers only eligible calendars. useResource aborts obsolete GETs and isolates URL identities. Mutation pending refs prevent double submission; conflict refresh and redirect-result freshness need adversarial checks.
- Migration `0a542f68aa75` extends the audited Stage 1 head, preserves local/demo rows, adds provider identities/constraints and refuses downgrade before destructive DDL when provider data exists. TECH_DEBT contains 27 entries (10 resolved, 17 open), including credential operations TD-025, quotas/retention TD-026 and unperformed live acceptance TD-027.

## Audit evidence and findings

The audit found **0 CRITICAL, 2 HIGH, 9 MEDIUM and 2 LOW** Stage 2 findings.
The findings below are fixed; pre-existing operational debt is not represented as resolved.
Tests use real disposable PostgreSQL and fake/synthetic provider transports only.
No Stage 3 functionality, live Google acceptance, or push is included.

| ID    | Severity | Finding, evidence and final behavior                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| ----- | -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| G-A01 | HIGH     | SDK log suppression disabled existing loggers but did not stop a newly created child from forwarding secret-bearing messages. Synthetic late SDK loggers reproduced the leak. Google/OAuth/HTTP logger roots now discard propagation and handlers; existing children are disabled. Tests cover five logger namespaces and secret-bearing provider exceptions. Operator log reconfiguration must preserve this boundary.                                                                                                                                                                      |
| G-A02 | MEDIUM   | Same-account reconnect accepted any nonempty stored credential when no new token arrived, including corrupt/revoked values. It now decrypts, refreshes, checks scope and verifies the retained grant's primary identity before reporting connected. Different-account reuse is rejected.                                                                                                                                                                                                                                                                                                     |
| G-A03 | MEDIUM   | A refresh rotation followed by page-three failure lost the new credential. Rotated credentials now commit encrypted before listing; catalog reconciliation still waits for all pages. Refresh serializes with reconnect/disconnect to prevent concurrent credential replacement. External rotation plus local commit cannot be perfectly atomic (TD-025).                                                                                                                                                                                                                                    |
| G-A04 | MEDIUM   | Connection generation alone did not detect changed catalog/assignment impact during account-switch confirmation. A digest of calendar identity/name/exclusions and active assignment identity is frozen in the dialog and persisted on the attempt, then checked at start and completion. Changed impact fails closed.                                                                                                                                                                                                                                                                       |
| G-A05 | MEDIUM   | Two Google advisory owners exhausted a two-slot transaction pool, causing even status/auth reads to fail. Dedicated unpooled Google lock connections leave SQL pool capacity available; waiters release connections between attempts. PostgreSQL total connection/admission budgets remain operational debt.                                                                                                                                                                                                                                                                                 |
| G-A06 | MEDIUM   | Quota HTTP 403 was treated as revoked scope; token refresh lost Retry-After and allowed redirects; HTTP-date retry rounded down; huge delays became PostgreSQL infinity and broke later comparisons. Closed quota mapping, no token redirects, preserved retry headers, upward date rounding and a finite year-9999 deadline fix these cases. The UI displays the retry date and time, including multi-day delays.                                                                                                                                                                           |
| G-A07 | MEDIUM   | Cancelling asyncio.to_thread could unwind lifecycle ownership while synchronous HTTP still ran. The adapter shields worker calls and waits for completion before propagating a cancellation. Per-call timeouts remain; overall request/shutdown budgets are TD-017.                                                                                                                                                                                                                                                                                                                          |
| G-A08 | MEDIUM   | Every revocation HTTP 400 was reported as success, hiding provider/configuration failures. Only invalid_token is idempotent success; other failures are safely audited after local removal.                                                                                                                                                                                                                                                                                                                                                                                                  |
| G-A09 | MEDIUM   | Profile assignment errors did not refetch authoritative state; URL-only success markers could describe a stale account; old mutation completion could notify a page already left. Recovery now refreshes profile/catalog, clears deleted identities, ignores unmounted completion and relies on server status for OAuth success. Confirmation snapshots and pending mutation controls are covered. A final regression reproduced controls unlocking between a successful OAuth start and navigation; controls now stay locked until navigation.                                              |
| G-A10 | LOW      | Repeating an unchanged table assignment added inactive/active history; repeated unassign/restore/exclude emitted noisy audit events. These operations now preserve existing identity/history without additional events when no state changes.                                                                                                                                                                                                                                                                                                                                                |
| G-A11 | MEDIUM   | Calendar list queries hydrated entire assigned technician profiles and relationship histories. Measurements with 1000 calendars/four history rows per technician showed 10 queries and unnecessary sensitive-column loading. A UUID/name projection uses two queries including authentication; general unpaginated technician/history growth remains TD-015.                                                                                                                                                                                                                                 |
| G-A12 | HIGH     | SameSite=Strict manager cookies were withheld on a real cross-site OAuth callback; same-site fake flows concealed this. A localhost consent page returning to 127.0.0.1 reproduced failed connection before the fix and succeeds after it. Protected OAuth start now reissues the same authenticated session as SameSite=Lax with remaining lifetime, HttpOnly and configured Secure. State/session binding and exact-Origin/CSRF mutation checks remain mandatory. Ordinary login keeps its prior policy; existing sessions are upgraded when starting OAuth without requiring a new login. |
| G-A13 | LOW      | An accumulated-login-throttle failure exposed an ephemeral test password in a Playwright error-context snapshot. The account was automatically deleted and artifacts were Git/Docker-ignored. The browser fixture now clears the serialized password before login-outcome assertions and again during teardown; a controlled throttle failure verifies the captured snapshot has no password value; final successful runs replace those failure artifacts. This was synthetic test data, not a real account credential.                                                                      |

The initial adversarial run captured failures before fixes in ignored local logs. Additional
regressions cover the fixes and races discovered during review. One new browser check used
an incorrect exact-label locator for the Filter control; it was corrected to the observed
combobox role. That failure was test infrastructure, not a hidden application failure. Repeated browser runs also reached the unchanged cumulative login throttle; only disposable rate_buckets were reset between independent runs. The cross-site callback failure was a real product defect, separately reproduced and fixed.

## Security and lifecycle evidence

- State is generated by secrets.token_urlsafe(32), persisted only as SHA-256, expires in ten minutes, and is locked/consumed before provider exchange. Replays after successful and failed exchange, duplicate/reversed callbacks, malformed/duplicate parameters, provider denial, missing code and expired state fail. New same-session attempts burn older attempts.
- OAuth start reissues the existing manager cookie as SameSite=Lax for the cross-site top-level callback, preserving remaining expiry, HttpOnly and configured Secure. Backend cookie assertions and a real two-loopback-site browser navigation verify this behavior. Normal mutation Origin/CSRF requirements are unchanged.
- Manager and initiating session are checked independently. Another manager, another session, logout/login, expired/revoked session and inactive manager cannot bind an account. Completion rechecks live session validity after external work. Invalid unauthenticated callbacks redirect safely and never attribute completion to a new user. Managers restart OAuth after signing in again.
- PKCE uses the installed official library's 128-character random verifier and S256. Tests compute the SHA-256/base64url challenge independently, compare different verifiers, verify encrypted attempt storage and clearing after consumption. Neither raw verifier nor state hash is in public schemas.
- Authorization code stays in request-local state only; middleware removes the query from downstream ASGI scope/access logging and returns a fixed 303 to the code-free calendar URL. Browser query cleanup removes the result marker. Logs/audit/API error envelopes receive closed codes rather than provider exception text.
- Actual PostgreSQL credential values are versioned Fernet ciphertext. Tests decrypt with the configured key, reject plaintext mutation, malformed/corrupt/version-mismatched values and wrong/missing keys. Startup rejects enabled production OAuth without a valid key. No plaintext fallback exists.
- Same-account new tokens replace encrypted credentials; omitted tokens now require verified usable old grants. Different-account omitted tokens cannot reuse the old account. Zero/multiple primary identities reject activation. A commit failure after exchange rolls back local catalog/account replacement and leaves state burned; revocation failure after commit preserves the newly committed account and emits a safe failure event.
- Account identity comes from the single primary CalendarList ID, not a user-supplied label/email. A generic manager-visible label is stored/displayed. Identical provider calendar IDs under different connection/account contexts produce distinct local UUIDs; returning to an old account recovers its own catalog and exclusions.
- Fake Google requires APP_ENV=test and an approved isolated test database. Tests exercise production/development/remote-host rejection; there is no raw-token/calendar-injection HTTP route. The private CLI harness is guarded separately. Existing exact-origin, authenticated manager and mutation CSRF controls remain in force; callback GET does not disable global protections.
- Public OpenAPI/generated contracts expose only intended operational metadata and the initiating manager's authorization URL. Callback is omitted from OpenAPI; tokens, ciphertext, verifier, state hash and client secrets are absent. Contract regeneration is deterministic.

## Reconciliation, concurrency and history

The provider collects every page before reconciliation. Empty first page plus continuation,
identical duplicates, conflicting duplicate metadata, malformed/empty/oversized/repeated
continuations and the 1000-page cap are tested. Conflicting duplicates or any incomplete
fetch reject the snapshot. Page ordering and names can change without changing identity.
Page 1 and page 2 followed by a failed page 3 preserve the complete pre-scan catalog.
An injected reconciliation failure after a flush rolls back all catalog changes.

A structurally complete Google pagination sequence is not guaranteed to be a provider
snapshot. A calendar moved between pages could appear missing without an obvious protocol
failure. Local absence therefore means UNAVAILABLE, never deletion; later reappearance
restores the same UUID and visible assignment. This external limitation is explicit in
the runbook rather than an invented provider guarantee.

Real PostgreSQL races cover same/different snapshot scans; scan versus disconnect,
reconnect, switch, exclusion, restore and assignment; competing technician/calendar
assignments; reassignment versus unassignment/exclusion/unavailability/deletion/removal.
Tests inspect final rows and active uniqueness, not only HTTP responses. Pending OAuth after disconnect cannot reactivate credentials; a disconnect waiting behind a completed reconnect rejects its old confirmation, then succeeds when confirmed for the new generation. Two sessions switching concurrently activate only one account. Old-generation
scans cannot resurrect disconnected/replaced catalogs. Simultaneous scans receive a
conflict; catalog/assignment mutations serialize through a short transaction advisory lock.
Network barriers verify no idle SQL transaction during provider work, and constrained-pool
tests verify lock ownership cannot consume the transaction pool.

Deployed partial unique indexes enforce one active calendar per technician and one active
technician per calendar. A composite unique constraint enforces provider identity within a
connection. FK/CHECK constraints preserve active assignment and provider source identities.
Tests insert invalid rows; schema mutation experiments remove each unique protection and
prove the tests fail. OAuth manager/session FKs exist independently; application callbacks
perform ownership matching (arbitrary SQL writer policy remains TD-014).

Exclusions survive repeated scans, rename, reconnect and account separation. Ordinary API
assignment cannot bypass exclusion/unavailability. Removing an assigned calendar detaches
atomically; restore is explicit. Provider absence/disconnect retains active assignment and
shows unavailable warnings. Exclusion preserves inactive history; explicit technician
deletion cascades that technician's assignment history by existing policy. Historical
calendar_name snapshots are not rewritten on rename. Durable audit retention remains TD-010.

Disconnect clears encrypted local credentials before best-effort revoke; catalog,
exclusions and assignments remain. Timeout/failed revoke does not restore local access.
Permanent credential/scope failures enter REAUTH_REQUIRED; subsequent scans stop before
provider calls. Seconds/date/malformed/extreme Retry-After and persisted deadlines survive
provider recreation; expired deadlines permit recovery. Raw credentials are request-local
immutable Python strings, not guaranteed zeroizable memory.

## Frontend and metadata

Pending refs serialize scan and assignment controls; status/catalog GETs abort old requests
and isolate URL identities. Tests deliver old success after newer failure and old failure
after newer success, navigate away during a scan, and rapidly change assignment. Failed
assignment now refetches both resources, including external exclusion/disappearance and
technician deletion. Table mutations already refresh catalog/technicians on conflict.
Server impact/generation checks prevent a stale warning from replacing a changed account.

Calendar metadata containing long text, Unicode, emoji, RTL, HTML/script-looking strings,
Markdown links and control characters is normalized and rendered as plain text. Backend
titles are bounded to 150 characters and controls removed; React rendering creates no
script/javascript link. Browser checks measure/filter 10/50/250/1000 synthetic calendars
and verify no horizontal page overflow. Provider IDs remain identity; display text is not
trusted routing or executable markup. Screen-reader/cross-browser acceptance is TD-020.

## Migration, operations and debt

Baseline migration 0a542f68aa75 preserves Stage 1 data and refuses destructive downgrade
before dropping provider tables. The additive audit head b2917d804e12 stores the expected
replacement-impact digest. Old pending switches without the digest fail closed. Its
supported downgrade burns pending SWITCH attempts before removing the column; the catalog
and assignment history survive downgrade/re-upgrade. Fresh, audited/populated Stage 1,
populated Stage 2 and destructive-refusal paths are validated; one head and zero drift are
checked natively and in the running production API image.

Status distinguishes CONNECTED, DISCONNECTED, REAUTH_REQUIRED and ERROR with safe error
code, retry time and last success. It does not persist SCAN_IN_PROGRESS or expose a distinct
last-failure timestamp; operators use safe audit events for failure history. No full
observability platform or backup infrastructure was added. Per-request deadlines, admission
limits, quota/attempt retention, durable revocation, correlation/alerting and recovery drills
remain OPEN in TD-017/025/026.

The v1 prefix is an envelope-format version, not key identity. Re-encryption is possible
with the original and replacement keys, but not automated. Replacing/losing the sole key
makes old grants and pending verifiers unreadable until recovery or deliberate reconnect.
Database backups need separately protected matching-key recovery; DB plus key compromise
exposes the grant. These are pilot/production obligations, not claims of completed key
management.

No new debt ID was necessary: existing items already cover the remaining obligations.
TD-010/011 remain HIGH; TD-014 remains BEFORE NEXT STAGE and overdue. TD-025/026/027 remain
OPEN BEFORE INTERNAL PILOT. The register still has 27 entries: 10 RESOLVED, 17 OPEN
(0 CRITICAL, 2 HIGH, 12 MEDIUM, 3 LOW unresolved). No existing item is newly resolved.

Internal-pilot blockers: TD-010, 011, 012, 013, 017, 018, 022, 023, 025, 026, 027, plus the
overdue TD-014. Production additionally requires TD-016, 019 and 020. TD-015 and 024 are
LATER SCALE. Real Google/Telegram acceptance remains manual and was not attempted.

## Mutation experiments

All experiments ran only against disposable loopback PostgreSQL. Source mutations were
restored byte-for-byte in finally blocks; schema mutations were restored after clearing
only disposable test rows. No mutation runner/code is Git-visible.

| Temporary break                                                     | Detecting regression                        | Result |
| ------------------------------------------------------------------- | ------------------------------------------- | ------ |
| Remove OAuth session binding                                        | wrong-manager-session callback              | KILLED |
| Stop state consumption, enabling retry replay after failed exchange | failed-exchange state replay                | KILLED |
| Persist credential/verifier plaintext                               | actual encrypted attempt/credential storage | KILLED |
| Remove provider-calendar uniqueness in PostgreSQL                   | invalid direct provider identity insert     | KILLED |
| Clear exclusion during reconciliation                               | exclude/rescan/history                      | KILLED |
| Mark unseen calendars unavailable after partial pagination failure  | failed page preserves full catalog          | KILLED |
| Drop one-active-calendar-per-technician index                       | invalid direct active assignment            | KILLED |
| Drop one-technician-per-calendar index                              | invalid direct active assignment            | KILLED |
| Permit Google fake mode outside isolated test configuration         | production/development/remote-host startup  | KILLED |
| Reuse old-account token during account switch                       | different-account missing token             | KILLED |

## Performance measurements

The repeatable script uses loopback disposable PostgreSQL, fake provider traffic and four
assignment rows (three historical) per technician. GET times are medians of three local
runs; scans are individual samples, not service-level objectives. Dashboard measurement
is its two list requests combined. SQL counts include authentication, exclude dedicated
advisory-lock connection traffic, and grow in select-in batches rather than per record.
Final data is recorded below. Unchanged scans intentionally write last_seen_at on N rows
and one audit event; there is no per-calendar audit fanout. Catalog reconciliation is O(N).

| Calendars | List ms / queries | Technician list | Detail    | Dashboard   | Search    | Status    | Identical rescan / writes |
| --------- | ----------------- | --------------- | --------- | ----------- | --------- | --------- | ------------------------- |
| 10        | 12.43 / 2         | 18.75 / 6       | 17.56 / 6 | 29.86 / 8   | 17.6 / 6  | 13.12 / 3 | 94.03 / 9 / 10 rows       |
| 50        | 12.75 / 2         | 22.33 / 6       | 19.12 / 6 | 37.76 / 8   | 16.42 / 6 | 12.86 / 3 | 98.76 / 9 / 50 rows       |
| 250       | 19.74 / 2         | 57.42 / 6       | 23.62 / 6 | 77.67 / 8   | 20.67 / 6 | 15.77 / 3 | 120.92 / 9 / 250 rows     |
| 1000      | 38.73 / 2         | 160.7 / 10      | 19.6 / 6  | 211.83 / 12 | 20.17 / 6 | 24.19 / 3 | 184.63 / 9 / 1000 rows    |

At 1000 records the combined dashboard responses contain 858,001 bytes. Calendar list
projection reduced a baseline 10 queries to 2; technician list history loading remains
10 batched queries. The final rescan sample took 184.63 ms for 1000 last_seen_at writes,
plus a single scan audit event. These timings vary with local workload; no premature
pagination/cache rewrite was made. Browser measurements are recorded with the final gate.

## Verification gate

| Gate                                    | Final result                                                                                                                                                                                            |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Full PostgreSQL backend                 | 347 passed, 323.99 seconds; JUnit evidence retained locally                                                                                                                                             |
| Stage 0/auth audit                      | 86 passed within full suite (33 API, 38 audit, 15 auth)                                                                                                                                                 |
| Telegram complete/focused regressions   | 133 passed within full suite (28 onboarding, 42 completion, 25 worker, 38 quality audit)                                                                                                                |
| Google focused                          | 128 passed: 59 original and 69 independent audit cases; standalone final run passed                                                                                                                     |
| OAuth/security selection                | 39 passed, 89 deselected                                                                                                                                                                                |
| Calendar/provider concurrency selection | 38 passed, 309 deselected; final DB invariants checked                                                                                                                                                  |
| Frontend full suite                     | 64 passed across five files                                                                                                                                                                             |
| Development Playwright                  | 13 passed, 3.7 minutes, including cross-site cookie callback                                                                                                                                            |
| Production-image Playwright             | 13 passed, 2.7 minutes, including cross-site cookie callback                                                                                                                                            |
| Browser artifact negative check         | Forced synthetic login throttling fails as intended; password absent in captured error context after fix; counters reset; separate successful cross-site check passed                                   |
| Production frontend build               | PASS on final product source                                                                                                                                                                            |
| Strict TypeScript / ESLint              | PASS, including final fixture changes                                                                                                                                                                   |
| Ruff / Python format                    | PASS; 89 files formatted                                                                                                                                                                                |
| Prettier / diff whitespace              | PASS                                                                                                                                                                                                    |
| Contracts                               | Running OpenAPI matches snapshot; two final regenerations preserve OpenAPI and TypeScript bytes                                                                                                         |
| Migrations                              | Fresh/audited/populated Stage 1 upgrade; supported populated audit-revision downgrade/re-upgrade; destructive Stage 2 refusal preserves catalog/history; one head b2917d804e12, zero native/image drift |
| Docker / startup                        | Final API/web images built; isolated Compose validation and healthy DB/API/web startup passed                                                                                                           |
| Git-visible secret scan                 | 177 files; zero credential-pattern findings                                                                                                                                                             |
| Runtime/browser artifact scan           | 22 local static/log text files and 19 actual image browser bundles; zero configured-key, synthetic credential/code or real-token-shaped markers                                                         |
| Mutation experiments                    | All ten killed; source byte-restored and deployed constraints restored                                                                                                                                  |

The full browser gates verify final application code. The subsequent fixture-only artifact
redaction correction was additionally checked with a successful cross-site flow and a
controlled negative login setup, plus TypeScript/ESLint; no application behavior changed.
The production large-metadata screenshot was visually inspected: text remains literal,
truncation is bounded, assignment controls are disabled for unavailable rows, and the
page does not overflow horizontally.

| Browser size | Production render / search-check ms | Development render / search-check ms |
| ------------ | ----------------------------------- | ------------------------------------ |
| 10           | 189 / 28                            | 366 / 41                             |
| 50           | 141 / 27                            | 472 / 45                             |
| 250          | 200 / 133                           | 1053 / 425                           |
| 1000         | 732 / 2081                          | 1355 / 2326                          |

Browser wall times include navigation, driver interactions and assertions; production
ran alongside backend verification. They are integration-test measurements, not isolated
render benchmarks or promised latency. DOM volume/filter work at 1000 rows remains
meaningful scaling evidence in TD-015. No O(N)-per-row API fetching was introduced.

Final commit is created on the audit branch with message `chore: audit Google Calendar integration`.
The commit hash and clean status are returned in the task's final response. No mutation
experiment, generated key, private log or browser artifact is committed.

Ignored evidence lives under .local/audit-google-*; browser artifacts under
apps/web/test-results/{development,production}. The native database is loopback 5439;
production images use isolated project technician-hub-stage2-google-quality-audit and
ports 3005/8005/5442 with APP_ENV=test and fake providers. The original user application
and Telegram containers were not reset or replaced. Dedicated audit containers are stopped
at completion. No remote push and no real Google service/account contact occurred.
