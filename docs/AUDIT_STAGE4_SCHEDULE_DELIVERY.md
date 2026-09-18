# Independent Stage 4 schedule delivery audit

Audit date: 2026-09-17 (America/Los_Angeles). Starting branch:
`codex/stage4-schedule-delivery`; clean HEAD
`a84ea1eaf7b95d144c5f43136993868fa9af41ac` (`feat: add durable technician schedule delivery`).
Audit branch: `codex/stage4-schedule-delivery-quality-audit`. Original history and
migration `d4e509170001` are unchanged. No push or live-provider acceptance.

## Disposition

**Source changes and portable PostgreSQL verification are complete only to the
extent recorded below. Docker image verification is BLOCKED, not passed.** Docker
Desktop repeatedly failed before its Linux engine started, with an inaccessible
`dockerInference` runtime socket; the owner confirmed the same failure when starting
Desktop from Windows. No factory reset, container deletion, volume deletion, or
business database access was performed. A failed transient runtime directory was
preserved under `run.stage4-audit-preserved`; no database/image data was moved.

Official portable PostgreSQL 18.6 binaries were downloaded from EDB, linked by
[PostgreSQL's Windows downloads](https://www.postgresql.org/download/windows/),
and run without installation or a system service. New clusters under ignored
`.local/pg-audit-data` and `.local/pg-audit-e2e-data` listened on loopback ports
5439 and 5443. These contained only `technician_hub_test` fixtures. Development
and supplementary native production browser runs used fake Google/Telegram only.
Native production evidence does not replace a production-image run.

## Findings and fixes

No CRITICAL finding. Two HIGH findings fixed:

| ID     | Severity | Finding                                                                                                                                                                                      | Remediation / regression                                                                                                                                                                                                                 |
| ------ | -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| S4-A01 | HIGH     | One expired head row caused `claim` to return no work, ending the worker drain. An expired backlog could consume successive minute-long cycles until otherwise valid schedules also expired. | Bounded expired-row cleanup plus a live-deadline selection predicate; expired rows cannot hide ready work. `test_expired_head_does_not_hide_ready_work`.                                                                                 |
| S4-A02 | HIGH     | Original Stage 4 downgrade silently dropped all dispatch and automatic-decision history.                                                                                                     | Additive `d4e509170002` refuses populated rollback before removing any protection; original migration untouched. Migration validator proves refusal and preserved legacy rows/ciphertext.                                                |
| S4-A03 | MEDIUM   | Group-to-private fallback overwrote destination and cleared its reason on success.                                                                                                           | Persist requested destination and closed fallback reason separately from actual destination; expose safe metadata in history/UI. Legacy requested destination stays unknown.                                                             |
| S4-A04 | MEDIUM   | Definitively FAILED dispatches retained encrypted customer data despite no ordinary retry path.                                                                                              | New FAILED transitions purge payload atomically. Explicit resend rebuilds current content. Existing legacy payloads retain their original seven-day cleanup; migration does not erase them.                                              |
| S4-A05 | MEDIUM   | Terminal status was immutable, but actual chat/message receipt, sent/finished timestamps, error, attempts, and acknowledged history could be rewritten through raw SQL.                      | Additional receipt trigger protects terminal fields and completed acknowledgement state/time; positive message-ID constraint and provenance checks.                                                                                      |
| S4-A06 | MEDIUM   | Slow sequential automatic evaluation delayed the queue drain; heartbeat updates occurred only around the entire cycle; shutdown ignored stop while inside the cycle.                         | Independent scheduler/delivery tasks, periodic database-clock heartbeat, stale operator health command, and 40-second active-cycle shutdown grace. Each worker still sends sequentially, at most 20 per cycle.                           |
| S4-A07 | MEDIUM   | Lifecycle updates use the technician row lock, while send preparation and acknowledgement eligibility reads did not share that row-lock linearization point.                                 | Lock technician before reading binding eligibility in both paths; preserve global-calendar-then-technician lock order and recheck lease time after waits; existing advisory guards continue to serialize manager rebind/profile changes. |
| S4-A08 | LOW      | Canonically equivalent Unicode/whitespace/empty locations could produce different fingerprints.                                                                                              | Normalize new projection text to NFC and collapsed whitespace, treating empty optional location as absent, before rendering and hashing. Existing immutable v1 payload parsing stays byte-compatible.                                    |
| S4-A10 | MEDIUM   | Expired dispatches for a retired bot were excluded from recovery and could retain payloads or block normal sends indefinitely.                                                               | Recover expired leases and deadlines across bot identities; retain bot-scoped live claims. Two retired-bot regressions verify cancellation or ambiguity with no send.                                                                    |
| S4-A09 | LOW      | The safe HTML bound counts escaped markup as UTF-16 units and can reject content that Telegram itself would accept.                                                                          | Retained intentionally; tests prove 4095/4096/4097 boundaries, no truncation/splitting. Documented conservative product limit.                                                                                                           |

The initial proposal to purge every legacy FAILED/CANCELLED ciphertext during
migration was rejected by automatic approval review as irreversible data removal.
The implemented migration preserves those bytes and uses the existing retention
cleanup instead. This avoids an unreviewed historical data purge.

## Architecture and trust boundaries

- `service.create_dispatch`: sole manual, automatic, and confirmed-resend enqueue.
  It obtains Stage 3's authoritative projection, checks submitted date/fingerprint,
  renders the size bound, then rechecks source identity/date under Google mutation
  and technician guards before encrypting and committing an immutable dispatch.
- `domain`: versioned sorted canonical JSON, SHA-256 fingerprint, HTML-safe message,
  dedicated authenticated encryption, and hashed 32-byte acknowledgement capability.
  Descriptions, provider event IDs, notes, and fetch timestamps are excluded.
- `ScheduleDispatch`: durable snapshot identity, content ciphertext, destination-era
  identity/generations, claim UUID/lease, provider marker, retry deadline, receipt,
  acknowledgement metadata, and resend parent. Partial unique indexes enforce one
  active dispatch per technician/date and one automatic dispatch per date. One child
  per resend parent prevents uncontrolled duplicate confirmations.
- `scheduler.evaluate`: calendar-local evening decisions under per-technician
  session advisory guards; reuses Stage 3 target-date and projection logic. Decision
  creation and delivery are separate. A scheduler crash cannot replace stored content.
- `delivery`: SKIP LOCKED claim/recovery, eligibility/membership inspection, durable
  attempt marker, provider call outside transaction-pool connections, owner-checked
  finalization, and bounded expired-payload purge.
- `worker`: opt-in separate process; no FastAPI loop and no second getUpdates poller.
  Identity/webhook checks precede work. Multiple schedule workers are intentional.
- `acknowledgements` and trusted Telegram update processing: hash lookup plus current
  and dispatch-era actor/bot/generation/chat/message checks; one row-locked transition
  and one audit event. The button token alone is insufficient.
- `router`/DTOs/UI: existing manager session, Origin, and CSRF middleware; latest-20
  metadata only, no-store, explicit queued/uncertain/acknowledged distinctions, keyed
  technician panels, abortable reads, bounded polling, confirmed current-content resend.
- `health`: independent database, schedule-worker, and onboarding-worker status.
  Stale threshold 120 seconds; heartbeat every 15 seconds. API liveness is separate.

## Official Telegram semantics

Rechecked the current [official Bot API](https://core.telegram.org/bots/api), including
[sendMessage](https://core.telegram.org/bots/api#sendmessage),
[HTML](https://core.telegram.org/bots/api#html-style),
[callback queries](https://core.telegram.org/bots/api#callbackquery),
[inline buttons](https://core.telegram.org/bots/api#inlinekeyboardbutton), and
[response parameters](https://core.telegram.org/bots/api#responseparameters).
Successful sends return a Message; text limits apply after entity parsing, callback
payloads are byte-bounded, callback answers clear client progress, message IDs are
chat-scoped, and response parameters can carry migration IDs or retry delays.
The ordinary send workflow has no application-supplied idempotency key. Treating a
lost response as uncertain is this application's conservative inference, not a
Telegram promise of exactly-once delivery or a documented timeout recovery guarantee.

Adapter-defined Forbidden/chat-not-found responses are definite rejection classes.
Only those group-send rejections permit private fallback. Unknown exceptions,
network errors/timeouts, provider-unavailable, or malformed success IDs are uncertain.
Contradictory fakes must not label a possibly accepted request a definite rejection;
raw/unknown post-attempt transport failures remain AMBIGUOUS. Migration events
invalidate/revalidate group generations; queued sends and old callbacks cannot use a
new unrelated destination. BigInteger chat IDs and paired chat/message validation
avoid a global-message-ID assumption.

## State machine and crash matrix

`PENDING -> PROCESSING -> SENT | FAILED | AMBIGUOUS | CANCELLED`.
A committed definite 429 rejection may return PROCESSING to PENDING with persisted
availability, cleared provider marker, and bounded attempt budget. A stale unmarked
claim may also return to PENDING. No terminal state returns to active state.
Confirmed resend creates a separate immutable child and fetches current content.

| Window                                        | Durable state on death                        | Recovery / provider invocation evidence                                                     |
| --------------------------------------------- | --------------------------------------------- | ------------------------------------------------------------------------------------------- |
| A: before claim                               | PENDING                                       | One safe invocation after restart.                                                          |
| B: after claim, before marker                 | PROCESSING, unmarked                          | Expire/reclaim; one safe invocation after restart.                                          |
| C: after marker, before HTTP                  | PROCESSING, marked                            | AMBIGUOUS; zero provider calls and no retry. Conservative false uncertainty is intentional. |
| D: in-flight HTTP                             | PROCESSING, marked                            | AMBIGUOUS; one recorded invocation, no second invocation.                                   |
| E: success known in provider probe            | PROCESSING, marked                            | AMBIGUOUS; one invocation, no fallback/retry.                                               |
| F: before SENT commit                         | PROCESSING, marked after transaction rollback | AMBIGUOUS; one invocation.                                                                  |
| G: after SENT commit                          | SENT, ciphertext NULL                         | Remains SENT; no retry.                                                                     |
| H: before success/purge transaction completes | PROCESSING, marked after rollback             | AMBIGUOUS. There is no independent durable SENT-before-purge state.                         |
| I: after successful purge/commit              | SENT, ciphertext NULL                         | Remains SENT; no retry.                                                                     |

`tests/schedule_crash_probe.py` exits with `os._exit(81)` in a separate process;
its flushed/fsynced ledger stores only invocation counts, never payload/token.
The parent expires claims in PostgreSQL and runs recovery twice. `attempt_count`
means durable potential send attempts: C can increment without HTTP starting.
There is no window where this code begins HTTP before committing the marker.
External acceptance and local receipt commit cannot be atomic; no exactly-once claim.

## Concurrency, lifecycle and privacy evidence

Two, five, and ten workers drain a shared 20-technician population with one provider
invocation per dispatch, unique actual destinations, and no remaining claims.
Ten concurrent claimers are also measured at 20/50/250 populations. Five paused
sends with a two-connection transaction pool leave SELECT 1, API health, and manager
history responsive. Dedicated session advisory connections remain outside that pool;
provider calls hold no SQL transaction. Queue cleanup/recovery is bounded to 100 rows
per pass and live work is independently selectable. Expired history is recovered
across retired bot identities; live claims remain restricted to the configured bot.

Wrong/stale claim owners cannot finalize SENT, FAILED, or AMBIGUOUS. Lease authority
uses `clock_timestamp()` for selection, preparation, and ownership comparison, not
browser time or Python local time. Membership checks are pre-send inspections, not
attempts. Rebinding private identity cancels old queued content; group changes permit
only safe fallback to the same dispatch-era private identity after eligibility checks.
Lifecycle changes after the committed marker may be concurrent with provider I/O;
that unavoidable boundary must not be described as a guaranteed recall of a send.

Authoritative fetch races cover assignment removal, scope loss, disconnect, exclusion,
unavailability, deactivation, and deletion. Stale previews and arbitrary frontend jobs,
addresses, times, names, and removed-job fields cannot authorize content. Delivery
uses stored approved content even after fake Google events change. Canonicalization
checks cover Unicode, whitespace, null/empty fields, rendered changes, ordering, and
exact post-escape size. Legacy v1 snapshots remain readable, but newly normalized
content can have a different fingerprint from a visually equivalent legacy snapshot;
this is not a cross-version fingerprint migration. No-jobs content includes its target date and unique fingerprint.

Raw SQL constraints are challenged with missing receipt fields, impossible ack state,
message IDs on pending rows, active claims on cancellation, missing active payload,
invalid fingerprint/count/resend/ack pairs, and invalid fallback combinations.
Receipt mutation and payload replacement are rejected. Ciphertext is authenticated;
wrong keys, corrupt ciphertext, unsupported envelopes, invalid decrypted shapes,
and missing enabled-delivery keys fail closed. Only safe operational
metadata is exposed. New FAILED/CANCELLED and SENT transitions purge immediately;
AMBIGUOUS retains encrypted content at most seven days while cleanup is running.
Concurrent purge/history/resend/delivery preserves original terminal outcome and the
new child's required payload.

Twenty concurrent valid callbacks create exactly one acknowledgement audit. Wrong
actor, bot/anonymous actor, wrong chat/message, rebind, and expiry reject safely.
Expiry leaves SENT awaiting confirmation. Existing trusted-bot parser and fake-mode
startup guards remain; there is no production callback simulation endpoint. History
ignores an arbitrary huge query limit and returns at most twenty safe records.
Anonymous, forged, inactive, and logged-out sessions cannot read/toggle/send/resend;
mutation Origin/CSRF failures reject. Unknown provider exceptions are normalized and
safe log code tests cover schedule/address/token/chat material.

## Automatic delivery and frontend

Calendar timezone tests cover New York, Chicago, Denver, Los Angeles, and Phoenix
on DST and year-boundary dates. Boundaries 19:59, 20:00, 20:07, 22:59, 23:00, 23:01,
00:30, and morning are explicit. Stage 3's target function handles Friday/Saturday/
Sunday and month/year transitions. A restart inside the window can evaluate due work;
next-morning stale catch-up is forbidden. Whole-window absence does not retrospectively
create a missing MISSED row; monitoring remains TD-029. Saturday MISSED is terminal
for the Monday target even on Sunday, as documented.

Manual-first suppression (including changed fingerprints), automatic-first coalescing,
concurrent scheduling, and resend serialization retain one logical delivery. A definite
manual failure can permit the first automatic dispatch; ambiguous manual delivery
cannot. Auto setting and active identity are rechecked on enqueue and pre-send.

UI shows queued after POST, SENT only from durable status, and uncertainty with a
separate duplicate-risk confirmation. Resend explicitly sends current preview content.
The active poll loop waits for each result, stops/aborts on unmount/entity change,
uses 3-second active and 30-second ack intervals, and stops after network failure or
ten minutes. A failed read exposes manual refresh. Actual fallback history includes
requested/actual destination and reason, with no raw chat IDs.

## Performance and burst control

Portable PostgreSQL measurements on this workstation (fake providers; no production
capacity claim):

| Due technicians | Decision SQL | Decision seconds | Ten-claim SQL | Ten-claim seconds | History SQL |
| --------------- | ------------ | ---------------- | ------------- | ----------------- | ----------- |
| 20              | 461          | 3.534            | 50            | 0.170             | 6           |
| 50              | 1151         | 9.517            | 50            | 0.087             | 6           |
| 250             | 5751         | 47.870           | 50            | 0.079             | 6           |

The decision path is linear, `23N+1`, with per-technician authoritative projection
and state checks, not quadratic growth. It intentionally retains per-technician I/O;
there is no bulk Google request contract to substitute. The benchmark includes a
pre-existing manual dispatch per due technician, so decisions end SUPPRESSED after
revalidation. This measures the due/suppression path, not a forecast for 250 remote
sends. Each worker has one sequential outbound delivery lane, at most twenty sends
per cycle; fleet size still requires operational admission/capacity limits (TD-026/029).
History is bounded; same-day resend-chain lookup remains linear in retained daily
history (existing scaling/retention debt), not an unbounded public history response.

## Mutation evidence

All sixteen experiments are run against real disposable PostgreSQL, using application
assertions or database guards as appropriate. Runner/logs remain ignored in `.local`;
production bytes are restored by SHA-256 equality in `finally`. Crash probes are
committed regression infrastructure, not production mutations.

| Mutation                              | Detection                                        |
| ------------------------------------- | ------------------------------------------------ |
| Automatic AMBIGUOUS retry             | Provider outcome/terminal-state regression       |
| Timeout private fallback              | Single-invocation uncertainty regression         |
| Remove owner finalization check       | Wrong-owner regression                           |
| Remove row claim exclusivity          | Concurrent ten-claim uniqueness regression       |
| Remove fingerprint revalidation       | Stale-preview regression                         |
| Accept arbitrary frontend content     | Frontend authority/schema regression             |
| Store plaintext snapshot              | Cipher envelope/database/privacy regression      |
| Allow wrong acknowledgement actor     | Actor-context replay regression                  |
| Remove chat/message checks            | Context replay regression                        |
| Allow duplicate PENDING send          | Duplicate enqueue/database uniqueness regression |
| Allow manual plus automatic duplicate | Manual suppression regression                    |
| Use server timezone                   | Independent five-zone matrix                     |
| Permit next-morning catch-up          | Morning boundary matrix                          |
| Remove HTML escaping                  | Attacker-controlled rendered-text regression     |
| Delivery worker re-fetches Google     | Immutable approved-snapshot regression           |
| Expose raw acknowledgement capability | History privacy regression                       |

## Verification ledger

- Independent Stage 4 audit regressions: 223 passed (208 core audit and 15 edge cases).
- Full backend: 838 passed in 426.64 seconds; three upstream Telegram retry-after
  deprecation warnings. Stage 4 total: 281 passed, including 58 original tests.
- Frontend: 103 passed across 7 files.
- Development Playwright: 21 passed.
- Native production Playwright: 21 passed; final schedule-flow rerun after lock-order
  correction: 1 passed. Supplementary only.
- Production-image Playwright, Docker image build/startup/health: BLOCKED by Docker.
- Native production build, TypeScript, ESLint, Ruff/format, generated contract match,
  Compose configuration, and diff checks: passed.
- Alembic: complete historical chain, fresh and populated upgrades, supported empty
  downgrade/re-upgrade, preserved legacy ciphertext, guarded populated rollback,
  one head `d4e509170002`, zero drift.
- Sixteen safety mutations detected; exact production bytes restored.
- Privacy scan: 53 retained text artifacts, 19 browser JavaScript files, and
  217 source files checked; no remaining detected secrets. Two screenshots visually
  reviewed. Synthetic token-shaped test IDs in two JUnit artifacts and synthetic
  negative-test PostgreSQL diagnostics were redacted before retention. Docker image
  filesystem inspection remains blocked. Both isolated PostgreSQL clusters and audit
  API/web processes were stopped after verification.

## Debt and release gates

No new debt ID and no existing closure: 29 entries, 10 RESOLVED, 19 OPEN; 0 CRITICAL,
2 HIGH, 14 MEDIUM, 3 LOW open. TD-029 and TD-017/026 have partial remediation, not
closed operational obligations. All fourteen pilot blockers remain TD-010/011/012/
013/014/017/018/022/023/025/026/027/028/029. Production additionally requires
TD-016/019/020. TD-015/024 remain later-scale. Existing TD-014 remains overdue.

TD-028 live combined TEST acceptance was not performed and is not authorized by
this audit. No real Google API/account, Telegram bot/user/group, technician, or
business data was contacted. Public documentation and portable database software
were downloaded only. No Stage 5, Reports, Expenses, Contracts, Accounting, or GPS
work was begun. Nothing was pushed. Container validation remains an explicit audit
limitation and must be rerun after Docker Desktop is repaired.
