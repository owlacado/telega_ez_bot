# Independent Stage 5 Work Report quality audit

Resumed 2026-09-18 on `codex/stage5-work-reports-quality-audit` at
`10cb547b854b5e02fe6804f5ce2f55d2035ed045`. Existing uncommitted audit changes were
preserved and reviewed; this completes that audit rather than restarting it.
The separate manager CLI commit remains in history. No normal database reset,
real provider acceptance, customer-data access, push, or Stage 6 work occurred.

## Manager provisioning context

Commit `10cb547` (`fix: restore manager CLI provisioning`) resolved safe CLI error
reporting and added actual-entrypoint tests. The observed rejected password was
shorter than 14 characters; rejection happened before hashing/insertion. Username
`manager` is valid; the policy is 14–128 characters without composition rules.
Docker was not the cause. Earlier manager disappearance remains unproven.
Synthetic persistence/login evidence and instructions remain in
[Manager CLI provisioning](MANAGER_CLI_PROVISIONING.md). Normal development may
still have no manager; this audit does not create one or request its password.

## Findings and disposition

No CRITICAL finding. One HIGH, six MEDIUM, and one LOW implementation findings
were remediated. Existing deployment limitations below remain open.

| Finding                                                                     | Severity | Fix and evidence                                                                                                                    |
| --------------------------------------------------------------------------- | -------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| Equivalent recurring instants produced distinct occurrence identities       | HIGH     | Normalize original start to aware UTC before hashing; safely migrate derived historical keys; collision and preserved-history tests |
| Form expiry depended on process clocks and lock timing                      | MEDIUM   | Use PostgreSQL clock_timestamp after ownership locks for issuance/authorization; skew and expiry-during-lock-wait tests             |
| Revision gaps and unpointed future revisions could be inserted directly     | MEDIUM   | Deferred sequence triggers validate contiguous 1..current plus existing exact-current FK and immutable history                      |
| Non-submitted forms could contain partial submitted markers                 | MEDIUM   | Require all report/hash/time markers together only in SUBMITTED state                                                               |
| Forced-zero outcomes left a stale zero when returning to paid payment       | MEDIUM   | Clear amount when leaving ESTIMATE/CANCEL; require fresh explicit input; component and four-width browser coverage                  |
| Development effect replay launched competing form-open reads                | MEDIUM   | Share the component's pending open promise; ignore results after effect cleanup; retain explicit retry on genuine failure           |
| New integrity migration doubled a CHECK constraint name and broke downgrade | MEDIUM   | Wrap the full name with Alembic op.f; actual fresh/populated/round-trip validator now passes                                        |
| Oversized request chunk was copied before checking the body bound           | LOW      | Check combined length before extending the bounded buffer; 50 MB request regression                                                 |

## Architecture and legacy parity

Trusted private Telegram command -> hashed TechnicianFormSession -> Stage 3
calendar projection -> opaque job selection -> frozen server snapshot -> one
transaction inserting WorkReport and immutable revision, marking the session,
and writing a metadata-only audit -> durable browser receipt. Manager read routes
join only the report's current revision. No accounting, report editing, Google
writes, or external confirmation dependency is introduced.

The existing [legacy inventory](LEGACY_WORK_REPORT_INVENTORY.md) remains the parity
source: paid amount, payment/outcome, closer, maintenance-plan flag, optional
comments, and explicit review counts are retained. Group entry, correction workflow,
and accounting formulas remain outside this stage.

## Capability threat model and privacy

The private command verifies user/chat identity, non-bot/non-anonymous actor,
active technician and eligible bot binding. The session records technician,
issuing Telegram user/bot, binding generation, WORK_REPORT purpose, expiry and
SHA-256 of a random 32-byte capability. Every form operation rechecks current
technician/binding eligibility under technician -> binding -> session locks.

A copied valid bearer link **is transferable**: a second browser without manager
cookies or Telegram browser identity can submit using it. This is explicitly
proven by a regression, not represented as per-request Telegram actor proof.
Generation changes, revocation and inactivation reject old links. Origin checks
limit cross-origin browser use but do not authenticate the bearer holder.
TD-030 retains dedicated TEST acceptance and deployment threat-model approval.

The credential is a URL fragment and Authorization header, not a server URL/query,
localStorage entry or manager API field. Fragment persistence permits refresh and
also means deliberate sharing/browser history remain credential-handling risks.
No-store/no-referrer headers, literal text rendering, no third-party form assets,
and safe error codes limit accidental disclosure. Raw payloads, tokens/hashes,
addresses and provider exception bodies do not belong in application logs/audits.
The streamed 32 KiB application buffer rejects duplicate JSON keys and oversized
input before domain processing; this is not a claim that every upstream network
layer buffers at most 32 KiB. Admission/rate budgets remain TD-012/017/023/026.
There are no production form-issuance or provider-injection test endpoints.

## Identity and migration safety

One canonical report is unique on technician, calendar and occurrence. Recurring
identity uses parent event ID plus original occurrence instant normalized to UTC;
08:00-04:00 and 12:00Z identify the same occurrence. Different instants remain
separate. Nonrecurring events retain event-ID identity; calendar scopes remain
separate. Current choices and previously cached selected jobs are canonicalized
from their server facts before lookup/insertion.

Chain: audited Stage 4 `d4e509170002` -> Stage 5 `e5f509180001` -> integrity
`e5f509180002` -> canonical occurrences `e5f509180003`. Older audited migrations
are unchanged. Integrity upgrade fails on inconsistent revision history rather
than inventing repairs. Session constraints validate existing rows. The initial resumed round-trip caught
a doubled naming-convention prefix in the uncommitted integrity migration. Using
op.f for its explicit CHECK name fixed both upgrade/downgrade; only the disposable
test copies of that malformed constraint were renamed before rerunning the real validator.

Canonical migration obtains exclusive report/revision locks, computes all target
identities and checks collisions before writes. It changes only derived occurrence
keys. Immutable revisions, financial amounts, reviews, payment and historical
snapshots remain byte-for-byte unchanged. A collision raises
WORK_REPORT_OCCURRENCE_COLLISION and rolls back; no winner selection, merge or
deletion occurs. Invalid historical timestamps fail safely. The identity trigger
is disabled only inside transactional migration DDL and re-enabled before commit;
failures restore trigger/key state. Populated downgrade is refused, including a
return to old code that could recreate duplicate identities. Empty downgrade and
re-upgrade remain supported. Operators must stop old application writers during
rollout; the migration lock does not make old code compatible with new identity rules.

## Expiry, idempotency and concurrency

Clock comparisons follow row-lock acquisition; a session expiring while waiting
cannot submit. Submitted receipts can replay after TTL only while identity and
binding remain eligible. Same normalized payload returns the same durable receipt;
changed replay conflicts without changing financial history. A second session for
one occurrence cannot create revision 2. A lost HTTP response does not undo commit.

Fifty-way tests cover same/different sessions and same/conflicting payloads, checking
final report/revision counts and a single winner. Lifecycle tests cover deactivation,
delete and rebind winning the lock, and submission winning before deletion. Manager
reads never observe half-committed reports. Real PostgreSQL constraints separately
reject duplicates, missing/gapped/future revisions, orphan revisions, inconsistent
form markers, invalid financial values and history edits.

Selection uses authoritative Stage 3 projection and opaque IDs, never browser
technician/event/calendar facts. Reassignment before selection rejects; after
selection, the frozen job/date survives outage, assignment removal, midnight,
month/year/DST transitions. This deliberate historical-snapshot policy does not
allow a new binding or inactive technician to submit. No provider I/O occurs inside
the money transaction or after it as a required success step.

## Financial integrity and retained history

Money is Decimal with NUMERIC(12,2), not binary float. Strict bounds reject float,
nonfinite, exponent, negative, overprecision and oversized input. ESTIMATE and
CANCEL force 0.00 in validation and are independently constrained in PostgreSQL.
Categories remain CASH, ZELLE, CHECK, CREDIT_CARD, VENMO, SUPER, ESTIMATE, CANCEL;
CASH_APP aliases CREDIT_CARD. Reviews remain integer counts 0–100 for GOOGLE,
GROUPON, FACEBOOK; closer remains MYSELF/CALL_CENTER. No accounting meaning added.

Report and revision updates/deletes are guarded. The deferred exact-current FK
and contiguous-sequence triggers prevent impossible revision combinations. Latest
selectors join the pointer once, so historical revisions cannot double-count reads.
Reports block technician and calendar deletion through RESTRICT; deactivation and
calendar lifecycle changes retain history and manager access. Form metadata and
abandoned snapshots need retention policy, not an unaudited financial-history purge.

## Frontend and development failure investigation

The preserved mobile payment fix clears forced zero when switching back to a paid
method. Double taps are synchronously guarded and a lost-response retry reuses the
same payload. Manager navigation discards late previous-technician results and
closes stale details. Synthetic long text/XSS probes cover widths 320/375/390/430.

The reported development job-unavailable failure reproduced on a cleanly started
dev server. React StrictMode effect replay called form-open twice; aborting the
first browser request does not cancel the server's calendar read. The shared Stage 3
nonwaiting per-technician read guard can return BUSY to the second request. A new
StrictMode component regression failed before the fix (two calls) and passed after
sharing the in-flight promise (one call). Effect cleanup still suppresses stale UI
updates. All three controlled post-fix browser repetitions passed (48.9 seconds total);
full development and production results are recorded below. Initial repeat
failures left a synthetic binding after timeout prevented fixture teardown; only
the isolated test database was reset through its guarded fixture before rerun.

## Performance and retention

Existing 10/100/1,000/10,000-report evidence measured seven SQL queries and roughly
28–44 ms for latest-report reads, returning at most 20. The read selector did not
change during resume. The required complete regression suite includes this bounded
query assertion; no separate capacity benchmark was added. These workstation timings
are not a production SLA. Fifty concurrent submissions remain database-serialized
per technician rather than relying on process-local locks.

The 1,000-issued-session probe leaves only five OPEN but retains old metadata.
That verifies active-form bounding, **not** retention cleanup. TD-031 remains OPEN
for expiration cleanup, snapshot/metadata retention, anonymization, backups and
privileged archive policy. No broad cleanup architecture was added.

## Mutation evidence

Sixteen isolated experiments use disposable PostgreSQL on 5445, with source bytes
restored in finally and DB mutations restored by a guarded test plugin. Local runners,
mutants and outputs stay ignored in .local. They are not production/test-hook code.

| Mutation                        | Detector                                   |
| ------------------------------- | ------------------------------------------ |
| Allow expired form              | expired capability rejection               |
| Accept client technician facts  | server-fact/strict input rejection         |
| Accept client event facts       | spoof/bounds rejection                     |
| Ignore binding generation       | binding dimension checks                   |
| Drop canonical uniqueness       | direct PostgreSQL duplicate test           |
| ESTIMATE nonzero                | financial category test                    |
| CANCEL nonzero                  | financial category test                    |
| Convert money through float     | Decimal conversion spy                     |
| Mutable revision                | direct immutable SQL regression            |
| Changed retry updates report    | changed replay conflict/history regression |
| Technician report FK CASCADE    | RESTRICT metadata assertion                |
| Join every revision             | latest-pointer-only regression             |
| Log full report                 | synthetic privacy canaries                 |
| Return raw capability           | form API privacy assertion                 |
| Accept manager without bearer   | credential separation assertion            |
| Remove privacy response headers | error/no-referrer assertion                |

## Final verification

| Gate                                                   | Result                                                                                                                 |
| ------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------- |
| Complete PostgreSQL backend                            | 1,031 passed, 2 POSIX-only skips, 3 upstream PTB deprecation warnings; 603.89 seconds                                  |
| Focused Work Reports, concurrency, audit and migration | 174 passed in 109.57 seconds; also included in final full suite                                                        |
| Actual Linux hidden-password CLI terminal checks       | 2 passed; native Windows suite skips these two POSIX-only tests                                                        |
| Complete frontend                                      | 110 passed, eight files                                                                                                |
| Development Playwright                                 | 26 passed, 3.9 minutes                                                                                                 |
| Production-image Playwright                            | 26 passed, 3.4 minutes                                                                                                 |
| Previously failing development case                    | 3/3 controlled post-fix repetitions passed                                                                             |
| Mutation safety experiments                            | 16/16 detected; source bytes and DB protections restored                                                               |
| Native production build, strict TypeScript, ESLint     | Passed                                                                                                                 |
| Ruff and Python/Prettier formatting                    | Passed                                                                                                                 |
| Generated contracts                                    | OpenAPI matches; regenerated OpenAPI/types byte-identical                                                              |
| Migration validation                                   | Fresh, populated historical paths, guarded rollback and empty round-trip passed; one head e5f509180003; no drift       |
| Docker                                                 | Compose config and final API/web image builds passed; fake-only isolated startup/API health passed                     |
| Worker safety                                          | Both disabled entrypoints exit without provider initialization                                                         |
| Secret/privacy scan                                    | 241 Git-visible files; 63 retained artifacts/bundles plus two container logs; zero findings                            |
| Visual checks                                          | Production mobile and manager screenshots reviewed; literal synthetic markup, readable fields, no capability displayed |
| Git whitespace                                         | Passed                                                                                                                 |

Tests used isolated technician_hub_test databases on loopback 5445 (backend and
mutations), 5437 (development browser), and 5443 (production-image browser). Suites
sharing a database ran sequentially. Linux TTY checks used the isolated production
test database before browser tests. Normal development containers/volume were not
migrated, reset, seeded or rebuilt in place. API/web tags were built, then applied
only to the test stack; exact audited service/migration hashes matched its image.
Upstream PTB and test-runner warning counts are included in the backend result;
the Linux TTY run had a harmless unwritable pytest-cache warning in its nonroot
container. The historical pre-canonicalization 1,022 result is not the final gate.
Ignored .local helpers and evidence are excluded from Git and Docker build context. Running API/web image filesystem checks also confirmed
that local evidence and environment files were absent.

## Debt and rollout disposition

No debt ID added or closed. TD-030 remains OPEN: no dedicated live TEST acceptance
or bearer-threat approval occurred. TD-031 remains OPEN: measurement and stronger
history integrity do not implement retention policy. 31 total, 10 RESOLVED,
21 OPEN; open severities 0 CRITICAL, 2 HIGH, 16 MEDIUM, 3 LOW.

Pilot blockers remain TD-010/011/012/013/014/017/018/022/023/025/026/027/028/029/030/031.
Production additionally requires TD-016/019/020. TD-015/024 remain later-scale;
TD-014 remains overdue. Green local tests do not authorize pilot/production rollout.
Normal PostgreSQL volume technician-hub_postgres_data was not reset or deleted;
no real Google/Telegram/customer data was contacted and Stage 6 was not started.

The Stage 5 production-browser and mutation database stacks were stopped after verification; all local evidence was preserved.
