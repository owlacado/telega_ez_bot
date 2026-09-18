# Stage 4 schedule delivery verification

## Baseline and scope

Started clean on `codex/stage3-calendar-events-quality-audit`, exact HEAD
`b1451778d9720fd24709e6eb79452cd0e4c5ed84`; created
`codex/stage4-schedule-delivery`. Historical migrations were preserved. The final
commit is titled `feat: add durable technician schedule delivery`; its actual hash
is reported in the final handoff. No push, live Google/Telegram API call, live
acceptance, business-data access, or Stage 5 development was performed.

Architecture, contracts, failure semantics, configuration, retention and the
manual dedicated TEST runbook are in [SCHEDULE_DELIVERY.md](SCHEDULE_DELIVERY.md).
The existing localhost application and unrelated test database were not used.
Verification used isolated PostgreSQL ports 5439, 5443 and 5442; production-image
web/API ports were 3005/8005 in project `technician-hub-stage4-schedule-delivery`.
Google and Telegram adapters were fake/injected. Official public Telegram docs
were read; this is separate from contacting a live provider account.

## Final gates

| Gate                                                   | Result                                                                                                                |
| ------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------- |
| Full PostgreSQL backend                                | 615 passed in 305.86 seconds                                                                                          |
| Stage 0/API/auth audit regressions                     | 86 passed                                                                                                             |
| Stage 1 Telegram completion/onboarding/worker/security | 133 passed                                                                                                            |
| Stage 2 Google implementation/security                 | 128 passed                                                                                                            |
| Stage 3 events plus independent event audit            | 210 passed                                                                                                            |
| Stage 4 delivery regressions                           | 58 passed in the final full run; standalone 58 passed in 45.87 seconds                                                |
| Frontend                                               | 101 passed across seven files                                                                                         |
| Development Playwright                                 | 21 passed, 3.4 minutes                                                                                                |
| Production-image Playwright                            | 21 passed, 2.9 minutes                                                                                                |
| Mutation checks                                        | All 12 killed; original production bytes restored after every mutation                                                |
| Native production frontend build                       | Passed                                                                                                                |
| TypeScript / ESLint / Ruff / format                    | Passed                                                                                                                |
| OpenAPI and generated TypeScript                       | Schema matched; byte-identical across two generations                                                                 |
| Alembic                                                | Fresh, populated historical paths, Stage 3 rollback/re-upgrade, one head, zero drift passed                           |
| Compose and images                                     | API/web/schedule-worker built; isolated API and DB healthy; web exercised by Playwright                               |
| Worker                                                 | Injected worker initialized, cycled, persisted state and shut down; disabled production image initializes no provider |
| Bot worker                                             | Existing worker regression suite passed; disabled production image initializes no provider                            |
| Repository secret scan                                 | 211 Git-visible files, zero findings                                                                                  |
| Runtime/browser text and actual image JS               | 12 text artifacts and 19 JavaScript files, zero key/capability findings                                               |
| Whitespace                                             | git diff --check passed                                                                                               |

The Stage 4 tests include seven primary concurrency scenarios (competing workers,
concurrent enqueue, claim ownership, concurrent acknowledgement, manual/automatic
suppression, automatic once-only decisions, and a one-connection pool). Twelve
recovery/provider scenarios cover pre/post-marker crashes, stale owners, retries,
provider ambiguity and startup/shutdown. Nine acknowledgement/callback scenarios
cover parsing, actor identity, generation changes, expiry, wrong chat/message,
concurrent repeat callbacks and privacy. Ten automatic/timezone scenarios cover
calendar-local due windows, default OFF, suppression, cancellation, missed windows
and Google failure without an empty false-positive dispatch. These families
overlap; they are not additional tests beyond the 58 Stage 4 cases.

The original Stage 3 weekday/DST/floating-time/filter/recurrence/pagination suite
remains in the 615-test gate. No real network acceptance is inferred from fake
providers. The final browser screenshot was inspected; it shows full-width
history, separate delivery/ack states, automatic control, explicit resend and
uncertain-outcome explanation. A browser geometry assertion prevents recurrence
of the inherited narrow history-column defect.

## Mutation evidence

Each mutation was applied only to ignored local experiments, then tested with a
focused assertion and restored byte-for-byte. No mutation runner is committed.
The intentionally leaking mutation's ignored log was scrubbed of ephemeral test
capabilities after retaining the failure result.

| Mutation                                   | Detecting regression                                                |
| ------------------------------------------ | ------------------------------------------------------------------- |
| Remove fingerprint check                   | Stale preview rejected                                              |
| Accept extra frontend job fields           | Unknown jobs input rejected with 422                                |
| Persist plaintext snapshot                 | Creation/encrypted payload boundary                                 |
| Remove normal SENT duplicate guard         | Same fingerprint cannot be sent normally twice                      |
| Select AMBIGUOUS work for retry            | Unknown provider outcome is never retried; immutable terminal guard |
| Fall back after network uncertainty        | No private fallback on unknown acceptance                           |
| Remove claim-owner comparison              | Wrong owner cannot finalize an active leased claim                  |
| Remove acknowledgement actor checks        | Other group participant cannot acknowledge                          |
| Remove manual/automatic suppression        | Prior manual success suppresses changed-content automatic delivery  |
| Use server/UTC clock directly              | Assigned New York/Los Angeles timezone due windows                  |
| Remove HTML escaping                       | Name/title/location markup remains literal                          |
| Store and expose raw acknowledgement token | Public history cannot contain a callback capability                 |

## Separate self-review and corrections

The final review traced creation, authorization after external reads, immutable
payload boundaries, destination generations, manual/automatic races, claim leases,
pre-provider markers, post-acceptance crash recovery, ownership finalization,
acknowledgement authorization, cleanup and frontend identity changes. No unresolved
CRITICAL/HIGH Stage 4 finding remains. This is a self-review, not an independent
third-party security certification.

Corrections made before final verification:

- HIGH: nested session reads could exhaust a one-connection transaction pool.
  Snapshot reads now accept the existing short transaction; long-lived advisory
  locks use NullPool. A slow Telegram send leaves the sole transaction connection
  free, and concurrent ownership checks remain enforced.
- HIGH: queued work needed source revalidation before delivery. A source-version
  check now cancels assignment/connection/scope/name/status changes without
  replacing the immutable content or calling Google for new jobs.
- MEDIUM: acknowledgement validation now includes dispatch-era and current group
  generation/identity, in addition to the private binding and exact actor/message.
- MEDIUM: queue timestamps initially mixed application and database clocks.
  Availability, leases, attempts and finalization now use database clock time;
  calendar-local scheduling still uses the explicit operational date basis.
- MEDIUM: persisted status combinations and snapshot mutation needed database
  enforcement. Checks, partial uniqueness and an immutable-snapshot trigger now
  protect them, including SENT payload purge and acknowledgement separation.
- LOW: screenshot review found inherited two-column job styles squeezing delivery
  history to one narrow column. The history now uses full-width rows, with a
  browser geometry regression. Obsolete Queued notices clear on terminal status.
- LOW: existing docs still described schedule delivery as unimplemented. Current
  README, architecture and integration docs now describe Stage 4 and its opt-in
  worker; historical stage reports remain historical.

## Debt and operational readiness

No prior debt is closed. The original twelve pilot blockers remain
TD-010/011/012/013/014/017/018/022/023/025/026/027; TD-014 stays overdue.
TD-028 (combined dedicated TEST acceptance) and TD-029 (payload-key and separate
worker operations) are new pilot blockers. Production additionally requires
TD-016/019/020. Totals: 29 entries, 10 resolved, 19 open; 0 critical, 2 high,
14 medium, 3 low unresolved. TD-015/024 remain later-scale work.

Hard end-to-end provider deadlines, aggregate quota admission, deployment
alerting, key rotation/recovery, backups/retention and real TEST acceptance remain
explicit operational obligations. Exactly-once external delivery is not claimed.
A pre-provider marker counts a potentially attempted send even if the process
dies in the tiny interval before the call; uncertain outcomes require explicit
manager confirmation and a new immutable resend. Seven-day payload cleanup
requires a running worker and monitoring. These limitations are documented in
the delivery runbook rather than hidden by automatic retries or live test claims.
