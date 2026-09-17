# Stage 1 Telegram quality audit

Audit baseline: clean `codex/stage1-telegram-onboarding`, HEAD `c480fe2246436305803c1de2980eec923bf6dd99`. Audit branch: `codex/stage1-telegram-quality-audit`. Independent review of the implementation, not reliance on its prior verification report. No live Telegram calls or next-stage features are authorized.

## Architecture map recorded before source changes

- Manager HTTP requests pass origin/session/CSRF middleware; only active Manager accounts exist. No dispatcher/technician web role is implemented. Telegram router handles status, invitations, revoke/review/retry, disconnect and fixed test messages.
- TelegramInvitation stores a unique SHA-256 digest of a 32-byte random bearer credential, purpose, technician/bot scope, expiry, generations and lifecycle timestamps. A partial unique index permits one open invitation per technician/purpose. Existing invitations retain manual review; new ones activate automatically.
- TelegramBinding stores unique private/group identities, explicit status, availability, generations and bounded profile metadata. Technician row locks and identity transaction locks serialize claims; session advisory guards coordinate claim/disconnect/delete with outbound sends.
- The opt-in real adapter owns a Bot client and authenticated long polling; parsed updates are minimal TrustedEvent values. No public claim/update simulation route exists. Playwright uses a local stdin script guarded to the test database.
- Worker deduplicates update IDs transactionally, commits processing before advancing the polling offset, and sends noncritical replies best effort. Claims commit binding, invitation closure, audit and outbox atomically.
- Outbox claims with SKIP LOCKED and PROCESSING state, checks current binding/generations, then sends outside SQL transactions under a technician advisory guard. Restart changes uncertain PROCESSING sends to UNKNOWN; explicit rate-limit rejection permits bounded retry.
- Lifecycle updates preserve identities while changing availability; group-to-supergroup migration reserves the new ID and requires revalidation. Ordinary bot membership cannot prove continuous third-party membership.
- Frontend keeps returned credentials in component memory, generates QR locally, polls status, clears terminal credentials and shows confirmation dialogs. Navigation, delayed mutations, repeated modal lifecycle and stale responses require independent tests.
- Generated OpenAPI/TypeScript expose response shapes, not credentials. Alembic head e7b310920001 follows reconciliation d6c2f8a14001. Debt TD-010 through TD-022 includes existing audit-retention, data protection, deployment, provider invariants, observability and membership limitations.

## Findings and targeted fixes

Severity reflects the current onboarding workload, not hypothetical future schedule delivery. New findings: CRITICAL 0, HIGH 1 (fixed), MEDIUM 7 (six fixed, one deferred), LOW 3 (two fixed, one deferred). Existing HIGH TD-010/TD-011 remain explicit pilot blockers outside this Telegram-only correction scope.

| Finding                                                   | Severity | Evidence / consequence                                                                                                                                                                                                    | Resolution                                                                                                                                                                                                                             |
| --------------------------------------------------------- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Q-01: Stale polling offset after a quiet week             | HIGH     | Telegram may choose a lower random update ID after at least a week. Sending the old high offset can acknowledge unseen updates, including onboarding or membership changes. New PostgreSQL regression failed on baseline. | Worker omits an offset when its preceding processed record is missing or at least six days old, then persists the new event's offset. No webhook deletion or negative-offset backlog purge.                                            |
| Q-02: Advisory waiters starve the connection pool         | MEDIUM   | With two pooled connections, one owner and several waiting requests, the owner could not obtain the second connection needed to finish. The independent test reproduced QueuePool timeout.                                | Waiters use nonblocking lock acquisition and return connections between attempts. The owner alone retains its advisory connection; waiting sleeps hold no connection, transaction or lock.                                             |
| Q-03: Missing lifecycle chat ID matches NULL binding      | MEDIUM   | A malformed group membership update with no chat ID selected an unbound group and changed its availability. Baseline regression failed.                                                                                   | Validate lifecycle chat ID, sign/context, member ID and status before lookup. No incomplete event can search for an identity using NULL.                                                                                               |
| Q-04: Polling Retry-After shortened to 60 seconds         | MEDIUM   | A provider rejection requesting 300 seconds caused retries at 60 seconds. Baseline fake-provider test failed.                                                                                                             | Honor the requested delay through one hour, interruptibly; longer delays fail visibly without early retry. Exponential retry count remains bounded.                                                                                    |
| Q-05: Ordinary-member bot send rights assumed             | MEDIUM   | ChatMemberMember has no can_send_messages field; the adapter defaulted it to true, ignoring default group permissions.                                                                                                    | Check getChat permissions for the bot as an ordinary member; missing/denied permission fails closed. Three local stub tests cover allowed, denied and absent permission. No admin escalation.                                          |
| Q-06: Chat-not-found left availability usable             | MEDIUM   | A permanent known chat-not-found rejection failed the outbox item but left the destination AVAILABLE. Baseline regression failed.                                                                                         | Map the exact known response to CHAT_UNAVAILABLE, preserve the reserved identity and mark delivery unavailable. Unknown descriptions remain REQUEST_REJECTED; no raw provider text reaches users.                                      |
| Q-07: Automatic group recovery suggested admin escalation | MEDIUM   | Shared legacy error guidance told automatic invite users to restore an administrator role and retry legacy checks.                                                                                                        | Automatic guidance now requests ordinary send access and a new credential; frontend regression checks the alert and absence of legacy retry.                                                                                           |
| Q-08: Provider error type accepted arbitrary text         | LOW      | Real adapter already sanitized SDK errors, but another provider could put a deep link in ProviderError.code, which worker logs/persistence trusted. Injected failure demonstrated leakage and oversized-column failure.   | Closed safe-code allowlist maps unknown text to PROCESSING_FAILED before logging/persistence. Both injected-code and SDK error-string attacks are tested. This was a provider-boundary defense gap, not an observed real-adapter leak. |
| Q-09: Late issuance continued after profile unmount       | LOW      | The asynchronous issuance completion could initiate another status request after unmount. Page identity was already keyed, limiting cross-profile impact.                                                                 | Discard late issuance results and skip post-operation refresh on unmounted instances. Test navigates to another profile after delayed completion.                                                                                      |
| Q-10: Inbound response abuse / event retention            | MEDIUM   | No per-sender/global response budget; every update creates a deduplication record.                                                                                                                                        | New TD-023, BEFORE INTERNAL PILOT. No speculative rate-limit subsystem added.                                                                                                                                                          |
| Q-11: Metadata freshness                                  | LOW      | Username/title changes do not update claim-time display metadata automatically. IDs remain authoritative.                                                                                                                 | New TD-024, LATER SCALE. No identity or routing impact.                                                                                                                                                                                |

Five initial independent regressions failed on the unmodified implementation; the separate pooled-lock experiment also failed before its fix. All pass after corrections. Default send permissions were identified through source/official API review and local adapter stubs. Frontend regressions cover recovery guidance, post-unmount completion, timer cleanup and hostile plain-text metadata.

## Attack surface, authorization and trust boundaries

Reviewed manager HTTP endpoints, session middleware, the separate polling worker, real/fake providers, parser, claims, lifecycle, outbox, database, frontend memory/clipboard and generated contracts. Public API paths are health/login only. Authenticated documentation is not a capability bypass. There is no HTTP route accepting Telegram updates, arbitrary sender IDs, group IDs or simulated claims. The production route allowlist and strict extra-field rejection are tested. The stdin browser harness requires a loopback technician_hub_test database, imports only a fake provider, and is not a web endpoint; application fake mode is prohibited in production settings.

Only active Manager web accounts exist. There is no ordinary-user, technician, dispatcher or separate admin role to bypass; adding such roles later requires an explicit policy. The independent authorization matrix exercises all private/group issue and replacement, revoke, review/retry, disconnect, status and runtime operations with anonymous, inactive, expired, missing-CSRF and untrusted-origin requests. Existing permitted-manager paths remain functional. Middleware checks occur before handler input validation or writes.

Mutation requests require an exact allowed Origin and session-bound CSRF header. Login requires trusted Origin and the custom application header. Cross-origin OPTIONS is rejected; no permissive CORS configuration is installed. Cookies are HttpOnly, SameSite=Lax, and must be Secure outside local test/development; expiry, logout and revocation are covered by auth tests. The production test image uses deliberately isolated test-mode credentials and loopback HTTP; it is not evidence of production TLS provisioning. TD-012 remains open for deployment policy.

## Token lifecycle and hashing invariants

Source inspection confirms secrets.token_urlsafe(32), 256 random bits, 43 unpadded base64url characters and a full 64-character lowercase SHA-256 digest. Password-style slow hashing is unnecessary for random high-entropy credentials; computational preimage resistance is the claim, not a mathematical impossibility of reversal. PostgreSQL digest uniqueness is a collision backstop. The 1,000-token format test checks length, decoding, alphabet and observed uniqueness, not a statistical proof of cryptographic entropy.

Tokens are technician/purpose/bot/generation scoped, expire server-side, and are atomically consumed. Revoke, replacement, deletion, inactivity and replay tests establish unusability. Existing one-open-invitation partial uniqueness limits live capabilities. Raw credentials are returned only in the creation link/fallback; no raw token column, status/list/detail field, audit payload or contract literal exists. Contract schemas describe a creation link, not a stored credential. Hashes are omitted from public response models. Tokens are not normalized before hashing; case and exact token bytes matter. Command framing whitespace is parsed separately; extra payload parameters, appended characters and zero-width suffixes are rejected. Digest lookup need not be constant-time to withstand guessing a 256-bit random token; no practical identity enumeration path was found. Invalid responses disclose no technician existence.

The private link remains a bearer capability: first valid holder connects. Private delivery to the intended person is an operational requirement, not an identity proof derived from name/username. A group capability additionally requires the exact already-linked private actor before provider calls and again under the technician lock. Forwarded/anonymous/bot/wrong-context commands are rejected. Canonical technician names are never replaced with Telegram metadata.

## Official Telegram semantics and limitations

Rechecked [deep linking](https://core.telegram.org/bots/features#deep-linking), [Bot API updates](https://core.telegram.org/bots/api#update), [getChatMember](https://core.telegram.org/bots/api#getchatmember), [ChatFullInfo](https://core.telegram.org/bots/api#chatfullinfo), [ChatMemberMember](https://core.telegram.org/bots/api#chatmembermember), [Message migration fields](https://core.telegram.org/bots/api#message), and [ResponseParameters](https://core.telegram.org/bots/api#responseparameters).

Private start and group startgroup carry base64url payloads of at most 64 characters; generated 43-character tokens need no additional URL escaping. Configured usernames reject path/query/fragment injection. Links contain exactly one intended parameter. Telegram client handling of externally edited duplicate URL parameters is outside the server trust boundary: only a validated payload from the authenticated update can claim. Missing/extra/malformed payloads cannot bind.

Onboarding proves the linked actor's presence through their nonanonymous group command and verifies the bot's membership/send permissions. A regular bot cannot reliably receive every third-party departure or query another user's current membership. Bot removal/private blocking is observable through my_chat_member when delivered, and outbound forbidden/known chat-not-found failures suspend availability. An account deletion may only be discovered through subsequent access failure; the application does not infer deletion or erase the identity. Permission changes can race provider checks; a failed confirmation never undoes the committed binding. CONNECTED means an established identity relationship, while availability controls delivery and the UI says Linked but unavailable when suspended. It does not certify the current entire group audience. TD-022 therefore remains open, with live acceptance and explicit policy required before pilot or sensitive future delivery.

Basic-group to supergroup migration can change the signed numeric chat ID. Both migrate_to_chat_id and migrate_from_chat_id are parsed; the lifecycle handler serializes destination ownership, preserves the previous identity on conflict, otherwise reserves the new one, increments generation, cancels stale work and requires revalidation. Existing migration/conflict and stale-lifecycle tests pass. Rename/username changes do not change routing; display freshness is TD-024.

## Concurrency and actual database state

The independent A-J PostgreSQL race matrix verifies outcomes and persisted bindings, invitation closure, one-open-invitation keys, identity uniqueness and atomic confirmation counts:

| Scenario                                  | Result                                                                             |
| ----------------------------------------- | ---------------------------------------------------------------------------------- |
| A: one token, different users             | Exactly one connection                                                             |
| B: one token, same user, distinct updates | One logical connection and confirmation                                            |
| C: revoke versus claim                    | Serialized winner; revoked token cannot later bind                                 |
| D: replacement versus claim               | Replacement revokes old credential or receives stale-generation conflict           |
| E: deletion versus claim                  | No surviving binding, invitation or outbox after successful deletion               |
| F: same user, different technicians       | Only one technician owns the user                                                  |
| G: same group, different technicians      | Only one technician owns the group                                                 |
| H: private disconnect versus reconnect    | Successful disconnect invalidates claim, or committed claim makes disconnect stale |
| I: group disconnect versus group claim    | Same generation-protected winner rule                                              |
| J: two replacement invitations            | One open invitation; the existing binding is preserved                             |

Tests use independent PostgreSQL sessions and bounded asyncio waits. They establish the tested schedules, not an exhaustive proof of every interleaving. Existing paused-provider tests additionally prove generation/actor rechecks after external verification and deletion waiting for an in-flight send. New pooled-engine testing catches a blind spot in the older NullPool fixture.

The live PostgreSQL schema has unique user/group columns, unique digest, the open-invitation partial index, purpose/status enum CHECKs and cascading technician FKs. Direct invalid SQL proves uniqueness and enum enforcement. Direct SQL also proves the existing TD-014 gap: CONNECTED can coexist with a null identifier, and some availability/generation combinations are not constrained. Application services protect normal paths, but the full state/repair policy is still required before the next stage. No old migration was modified and no new migration was required for these localized fixes.

## Transactions, outbox and crash recovery

No SQL transaction spans provider membership checks, polling or send calls. The dedicated session advisory guard intentionally spans a send so disconnect/replacement/deletion cannot change its destination halfway through. Lock waiters now relinquish pooled connections. Retry sleeps retain only the singleton polling ownership lock, never technician locks or SQL transactions. This singleton guard is deliberate; it prevents another poller taking over during backoff.

| Crash boundary                                | Persisted result and restart behavior                                  |
| --------------------------------------------- | ---------------------------------------------------------------------- |
| Before claim transaction                      | No binding change; a valid unexpired token can still claim             |
| During transaction                            | Binding, invitation, audit, dedupe and outbox roll back together       |
| After claim commit, before offset update      | Dedupe prevents a second activation; queued confirmation survives      |
| Before outbox job is claimed                  | QUEUED work may send on restart                                        |
| After PROCESSING, before or during send       | Restart conservatively marks UNKNOWN, even if the send had not started |
| Telegram accepted, local result not persisted | UNKNOWN; no blind duplicate send; valid binding remains                |

Injected crash tests cover before-send and after-provider-acceptance/before-local-result persistence, with actual database inspection and fake send counts. Binding remains connected, consumed token remains unusable and UNKNOWN is not automatically retried. This deliberately permits a lost confirmation to avoid inventing delivery certainty. SENT means provider acceptance, not recipient reading. Only explicit rate-limit rejection is automatically retried, with bounded attempts and available_at scheduling. Fixed test messages are separately manager-confirmed. No schedule workflow was introduced.

## Worker, provider failure and operations

Real mode requires configured expected identity and a token supplied through a secret environment/file; missing credentials fail before constructing a network client. Startup checks getMe identity and refuses an existing webhook without deleting it. A PostgreSQL singleton lock prevents concurrent local pollers; Telegram polling conflicts fail visibly rather than taking over. Worker shutdown closes provider resources and records status; interruptible retry waits honor stop requests. API/web do not run the worker implicitly.

Connect/pool timeouts are 5 seconds, normal read/write 10 seconds, polling read 35 seconds with a 25-second long poll. Read/network failures are conservative NETWORK_UNCERTAIN; permanent authorization/invalid-token/conflict failures are not blindly retried. Known chat-not-found uses CHAT_UNAVAILABLE, other bad requests use REQUEST_REJECTED. Unknown provider error strings are reduced to PROCESSING_FAILED. Delivery 429 retries are limited to three attempts and a 600-second accepted delay; poll retries have five waits and honor Retry-After up to one hour. Longer requested waits stop instead of violating provider timing. Heartbeat age exposes unavailable workers; central alerts and DB/request deadlines remain TD-017.

## Audit, logging, frontend and privacy

Audit actions include actor, target UUID, timestamps and bounded safe outcome codes. Worker claim events identify the worker and originating manager capability; Telegram candidate identity is retained on the invitation, not copied as an arbitrary audit payload. Target IDs deliberately have no cascading technician FK, so audit events and technician.deleted survive deletion; manager deletion can null actor attribution. Retention/append-only guarantees and durable operator attribution remain TD-010, not resolved merely because events exist. Existing sensitive profile encryption debt TD-011 is unchanged and remains a pilot blocker.

The adapter suppresses Telegram/HTTP library logs and converts SDK exceptions before reporting them. Worker exceptions avoid raw payloads and secret URLs; SQL parameters are hidden in application engines. Tests inject deep links, random invitation values, bot-token-shaped strings, IDs and malformed provider descriptions. The positive tests show sanitized codes only. Negative mutation logs intentionally capture synthetic credentials to prove detection; they are ignored local test artifacts, never production secrets or committed files.

UI polling is one effect-owned timeout chain, paused when hidden, aborted on cleanup, and stopped on terminal invitation/error states. Sequence numbers suppress stale responses; mutation submission uses a synchronous guard. Independent fake-timer tests cover repeated close/reopen and unmount, and delayed issuance cannot restore a prior profile's credential. Profile navigation is keyed by identity. Automatic recovery instructions preserve minimum privileges. React escapes Unicode/hostile metadata as text; names are bounded and never rendered as HTML.

Credentials are held only in component memory and cleared on close, terminal state, expiration, status failure and unmount. No localStorage/sessionStorage, console logging, analytics or application route URL receives them. QR generation is local SVG, tested without remote images. Clipboard history/device sync and deliberately opening Telegram are explicit external exposure boundaries; the runbook now documents them. A closed dialog does not revoke the server token automatically; managers must use Revoke when cancellation is intended.

## Mutation experiments

Six temporary source experiments were run serially against isolated PostgreSQL; every modified file was restored byte-for-byte in a finally block. No mutation source is committed.

| Removed protection                                    | Detecting regression                                       | Result                                                     |
| ----------------------------------------------------- | ---------------------------------------------------------- | ---------------------------------------------------------- |
| Private context/purpose guards at prepare and consume | private_purpose_cannot_bind_other_context                  | Detected                                                   |
| Exact linked group actor at both checks               | group_exact_linked_actor_regular_bot_and_disconnect        | Detected                                                   |
| Consumed/closed/generation replay checks              | private_atomic_connection_metadata_hash_audit_and_home     | Detected                                                   |
| Application identity-conflict rejection               | competing_claims_one_winner_and_account_unique             | Detected; PostgreSQL unique constraint remained a backstop |
| Production route allowlist (added simulation route)   | production_telegram_route_allowlist_and_identity_injection | Detected                                                   |
| Secret-free worker logging (added payload log)        | worker_logs_codes_without_invitation_or_profile_data       | Detected                                                   |

These are targeted mutation experiments, not a comprehensive mutation score. The uniqueness experiment removed the application check, not the deployed unique constraint; direct SQL separately proves the latter.

## Debt review and deployment boundaries

No pre-existing item is declared resolved. TD-010 audit retention and TD-011 plaintext sensitive data remain HIGH; TD-012 deployment, TD-013 concurrent profile edits, TD-014 database state invariants, TD-017 observability/deadlines, TD-018 external profile images and TD-022 membership/live acceptance remain open. This audit improves portions of TD-014/017 evidence without closing their wider scope. TD-013 and TD-018 are not Telegram-specific and were not rewritten.

New TD-023 covers inbound response abuse/event retention before internal pilot; TD-024 covers metadata freshness at later scale. Totals: 24 entries, 10 resolved, 14 open; open CRITICAL 0, HIGH 2, MEDIUM 9, LOW 3. BEFORE NEXT STAGE: TD-014 (original BEFORE STAGE 1 obligation remains overdue). BEFORE INTERNAL PILOT: TD-010, TD-011, TD-012, TD-013, TD-017, TD-018, TD-022, TD-023, plus overdue TD-014. Additional BEFORE PRODUCTION: TD-016, TD-019, TD-020. LATER SCALE: TD-015 and TD-024.

The [manual acceptance runbook](TELEGRAM_ONBOARDING.md) requires a dedicated TEST bot, fictional technician, own test account and isolated group; explicitly enable the separate worker only for that manual acceptance and disable it afterward. No real Telegram account/group or technician was contacted in this audit. Official public documentation was browsed; authenticated Telegram APIs were not called.

## Verification and performance evidence

All required quality gates passed on the final implementation. Local evidence uses ignored .local/quality-audit-*.log files. Native checks use disposable loopback database 5439; production-image checks use a separate Compose project technician-hub-telegram-quality-audit on 3005/8005/5442. No original application database was reset. No functional integration stage was started.

| Verification                                              | Final result                                                                              |
| --------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| Full backend PostgreSQL suite                             | 219 passed (128.58 seconds)                                                               |
| Focused Telegram suites                                   | 133 passed, including 38 new independent audit cases                                      |
| PostgreSQL concurrency selection                          | 20 passed, including A-J and pooled connection contention                                 |
| Explicit Stage 0 audit regressions                        | 38 passed; also included in full suite                                                    |
| Full frontend                                             | 40 passed                                                                                 |
| Development Playwright                                    | 10 passed (2.0 minutes)                                                                   |
| Production-image Playwright                               | 10 passed (1.8 minutes), including private/group claim and independent disconnect         |
| Production frontend build                                 | Passed via Docker Next standalone build                                                   |
| TypeScript / ESLint / Ruff / formatting                   | Passed                                                                                    |
| Generated OpenAPI + deterministic TypeScript regeneration | Passed; unchanged contracts                                                               |
| Alembic fresh/populated upgrades and supported roundtrips | Passed; invitation history and bindings preserved                                         |
| Schema drift / migration head                             | No drift; single unchanged e7b310920001 head                                              |
| Compose normal/worker-profile configuration               | Passed; worker profile was not started                                                    |
| Docker API/web build and isolated startup                 | Passed; API/database/web healthy, API health JSON OK, web HTTP 200                        |
| Secret scan                                               | 157 Git-visible files, zero findings; isolated runtime credential-pattern scan also clean |
| Temporary source mutations                                | All six detected and reverted                                                             |
| Git diff whitespace                                       | Passed                                                                                    |

The full backend suite was repeated after the final adapter correction; the last production image was rebuilt and its full browser suite rerun. No test depended on live Telegram credentials. Harmless Node NO_COLOR/FORCE_COLOR warnings appeared in browser logs; no test failed because of them.

Measured query counts include manager-session authentication. Four samples per endpoint/size, with one cold and three warm requests; local wall time is diagnostic, not an SLA:

| Technicians | List queries / warm median | Detail queries / warm median | Telegram status queries / warm median | List response bytes |
| ----------- | -------------------------- | ---------------------------- | ------------------------------------- | ------------------- |
| 10          | 6 / 14.58 ms               | 6 / 14.06 ms                 | 9 / 16.96 ms                          | 4,291               |
| 50          | 6 / 18.13 ms               | 6 / 13.51 ms                 | 9 / 16.81 ms                          | 21,451              |
| 250         | 6 / 36.44 ms               | 6 / 14.46 ms                 | 9 / 17.84 ms                          | 107,251             |

Calendar-list queries remained six at every size; dashboard attention uses technician/calendar lists and computes missing connections locally. No per-technician invitation/binding N+1 was observed. Status loads two latest invitations and at most ten outbox rows; it does not load unbounded audit history. List payload and assignment-history volume still grow, so TD-015 remains open. The profiling script now seeds bindings and pending invitations, and retains its destructive-test-database guard.

Before committing, temporary mutation code was absent from tracked source, integrated migrations were unchanged, and only the targeted implementation/tests/runbook/debt/report/profiling files were staged. Final commit subject is `chore: audit Telegram onboarding security`; retrieve the full hash with `git log -1`. Audit verification services are stopped afterward; original application services and databases remain untouched. Nothing is pushed.
