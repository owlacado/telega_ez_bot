# Independent Stage 3 calendar event audit

## Baseline and architecture map (recorded before implementation edits)

Starting branch: `codex/stage3-calendar-events`; clean HEAD:
`65583c47f401bf881eae24f269e69a61f7ad5e88`.
Audit branch: `codex/stage3-calendar-events-quality-audit`. No history rewrite or push.

- Google OAuth start/callback reuse hashed, session-bound, single-use attempts,
  PKCE, encrypted refresh credentials, generation checks and lifecycle locking.
  Event upgrade requests CalendarList read plus Events read; actual grants determine capability.
- `GoogleCalendarProvider.list_events` is the external read boundary. It expands
  recurrence, paginates, bounds bytes/pages/events/time, and rejects inconsistent results.
- `normalization.py` parses provider timestamps and optional metadata into frozen DTOs.
  `domain.py` computes calendar-local date windows, title-only exclusions, start-time
  work hours, numeric ordering, and separate preview titles.
- `calendar_events/service.py` brackets network work with authorized SQL snapshots;
  dedicated advisory locks serialize refresh lifecycle and per-technician reads.
  A fresh assignment/connection/date comparison discards obsolete results.
- Today and Next Schedule GET routes share this service. Auth middleware checks active
  manager sessions; response middleware applies no-store, nosniff and no-referrer.
- `useSchedule` uses request identity/version and AbortController. `calendar-jobs.tsx`
  renders explicit wall-clock strings as React text. Preview mounts a separate reader.
- OpenAPI exports `ScheduleRead` and bounded projected DTO fields to generated TypeScript.
  Events are not stored in tables, outboxes or durable frontend caches.

Trust boundaries: browser/session to API; SQL authoritative lifecycle state to short-lived
provider credentials; untrusted Google payload to validated DTO; DTO to calendar-local
projection; authenticated response to plain-text browser rendering. Event content must
not enter operational logs or audit metadata. Existing pilot/production debt remains
open unless new evidence establishes closure.

## Findings and localized fixes

No new CRITICAL issue. One HIGH, four MEDIUM and two LOW findings were reproduced and fixed:

| ID     | Severity | Defect and result                                                                                                                                                                                                                                                                                    |
| ------ | -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| S3-A01 | HIGH     | A cancelled recurrence tombstone with a different event ID bypassed instance conflict checks. Active and cancelled representations of the same parent/original instant now reject the complete fetch, in either page order.                                                                          |
| S3-A02 | MEDIUM   | Python ISO parsing accepted compact timestamps, second-resolution/out-of-range offsets, compact updated timestamps, and simultaneous date/dateTime; incomplete recurrence metadata could bypass instance identity. Strict date/RFC3339 shape and paired recurrence metadata now fail conservatively. |
| S3-A03 | MEDIUM   | The transport allowed 10,000 events to become thousands of browser jobs. Projection now permits at most 500 jobs; excess returns REQUEST_LIMIT and zero jobs, never a truncated success. The transport's broader pre-filter limits remain.                                                           |
| S3-A04 | MEDIUM   | Preflight reads were not logged; success/empty and provider errors were conflated, and an exception could be logged READY. One outer diagnostic boundary now records explicit safe outcomes. Invalid JSON is classified as invalid data rather than a network failure.                               |
| S3-A05 | MEDIUM   | Unexpected 500 responses bypassed the response-header middleware. Calendar-event routes now return a sanitized 500 through the existing no-store/nosniff/no-referrer path without logging exception text. Other route behavior is unchanged.                                                         |
| S3-A06 | LOW      | Nested parenthetical notes left outer fragments; adjacent words could be joined. Linear balanced-group cleanup preserves unmatched text and separates remaining words. The frozen provider DTO remains unchanged.                                                                                    |
| S3-A07 | LOW      | Preview labels ignored the actual returned target. Labels now name that target weekday, including Friday, Saturday and Monday.                                                                                                                                                                       |

Initial independent reproductions: 15 failures / 2 passes against the baseline.
The subsequent unexpected-500 test failed on both routes before its fix.
All of these cases pass after remediation. Existing HIGH debt TD-010/011 is unrelated
and remains unresolved; this audit is not an internal-pilot approval.

## Official provider semantics

Rechecked public documentation on 2026-09-17; no authentication or Calendar API calls were made.
[Events.list](https://developers.google.com/workspace/calendar/api/v3/reference/events/list)
confirms that timeMin excludes events ending at/before the lower instant and timeMax
excludes events starting at/after the upper instant. Query offsets are mandatory.
The implementation uses singleEvents, start-time ordering, no deleted items, an explicit
calendar zone, and follows continuation tokens even after empty pages. These assumptions match.

The [event resource](https://developers.google.com/workspace/calendar/api/v3/reference/events)
defines originalStartTime as the recurring instance's identity even when moved, and
allows offset-free dateTime only with an explicit timezone. The
[recurrence guide](https://developers.google.com/workspace/calendar/api/guides/recurringevents)
explains expanded instances and exceptions. This motivated checking cancelled tombstones
against the same parent/original-time identity as active occurrences. Missing optional
nonrecurring metadata remains supported; contradictory or incomplete recurrence metadata
fails the whole response.

[Incremental authorization](https://developers.google.com/identity/protocols/oauth2/web-server#incrementalAuth)
supports requesting additional scopes in context with include_granted_scopes. Requested
capability is not treated as proof of a returned grant. No event-write scope was added.

## OAuth, authorization and lifecycle

- Existing hashed state, PKCE, single use, expiry, manager/session binding, same-account
  verification and generation protection remain intact. Calendar-list-only access survives
  failed, empty or reduced event upgrades. Omitted refresh-token reuse independently verifies
  the old grant and account; callback and refreshed scopes are intersected.
- Incremental upgrade tests include disconnect/replacement of an outstanding attempt,
  a paused exchange competing with disconnect/replacement, and upgrade completing during an
  event fetch. Stale generations cannot overwrite the completed upgrade; in-flight event
  results are discarded after the generation change. No cross-account credential reuse occurs.
- Both routes enforce active manager sessions. Independent HTTP checks cover anonymous,
  inactive, logged-out, missing technician, invalid UUID and authorized requests. Managers
  share the product's manager capability; no separate technician-scoped manager role exists.
- The final HTTP response, not merely DB state, is asserted for Calendar A to Calendar B
  reassignment through the actual assignment API. A private A sentinel never appears in the
  response. Exclusion, unavailable calendar, technician deletion, disconnect, expiry,
  deactivation and event-scope removal similarly prevent old jobs from being returned.
- Scope loss leaves discovery capability intact. Refresh rotation is persisted before event
  reads. Post-I/O identity/date/session checks still occur after projection and before return.
  The application cannot promise a transactional Google snapshot across multiple pages.

## Time, dates, filters and recurrence

The assigned calendar's IANA zone defines operational date and display. Offset-bearing
provider timestamps are authoritative instants, even when event.timeZone differs; they are
projected into the assigned calendar's view. Offset-free timestamps require an explicit,
valid event zone and reject ambiguous/nonexistent local times. There is no server-zone fallback.
Browser code renders display_start_time directly. Date-only labels use explicit UTC formatting;
retry/fetched instants are shown as ISO strings, not used to calculate schedule time.

The independent DST matrix verifies exact UTC request endpoints and 08:00 projection on
normal, spring-forward and fall-back dates for New York, Chicago, Denver, Los Angeles and
Phoenix. Independent local midnights produce 23/25 hours in DST zones and 24 in Phoenix.
Next-day midnight is excluded; yesterday's overlapping jobs are not today's start-date jobs.
Chromium verifies New York/Los Angeles, Denver/New York, and Los Angeles/UTC calendar/browser
pairs, in both Today and Preview, using actual Python normalization/projection output.

Title filtering remains explicit, case-insensitive, whole-word and title-only. Every listed
cancel/reschedule/fake/redo variant is tested with punctuation and Unicode whitespace.
Redondo Beach and Faker Street remain. Description, location, attendees and arbitrary notes
cannot remove a valid titled job. Cancellation-policy wording intentionally matches cancellation.
Provider cancelled status excludes even valid numbered titles; tombstones may lack start/end.
All-day and recurring all-day reminders remain excluded.

Start policy is exact: 07:59:59 out, 08:00 in, 21:59:59 in, 22:00 in, 22:00:01 out.
A 21:30 start ending after 22:00 stays. Numeric 1/2/10 ordering, leading whitespace,
unnumbered start/ID tie-breaks, retained duplicate numbers and one stable warning are covered.
Preview removes balanced parenthetical groups and case-insensitive didnt/didn't/didn’t buy;
Today keeps the near-raw title. Unmatched parentheses remain literal. Neither mutates the source DTO.

All seven next-day rules remain shared, including Friday to Saturday, Saturday to Monday,
Sunday to Monday, December 31 2022 to January 2 2023, and month-boundary weekends.
Both endpoints use the same provider, normalization, filter, work window and ordering.

## Completeness, errors and bounded work

A malformed item, conflicting normalized event/instance, looping/malformed continuation,
request-budget exhaustion or failed final page fails the whole schedule. No valid prefix is
presented as complete. This conservative policy is intentional: quietly skipping a possibly
important job is worse than asking the manager to retry or repair provider data.

Transport limits remain 100 pages, 10,000 distinct active events, 8 MB total streamed bodies,
5/15-second connect/read timeouts and a 45-second elapsed pagination budget checked between
reads. The 500-job projection limit is deliberately far above a technician's plausible day;
500 is accepted and 501 fails with zero jobs. Text fields remain bounded at 500/1000/4000
characters for summary/location/description. Synthetic 500-job output measured below 3.5 MB
for ASCII maximum projected notes/location. Limits are characters, not a promise of that byte
size for every Unicode input; the provider's total-byte limit also applies to real transport.

Identical IDs and equivalent-offset recurrence identity deduplicate. Conflicting contents or
active/cancelled statuses fail, including across different IDs for the same recurring instance.
Moved occurrences retain original identity and use actual start for day/filter/order. Repeated
page tokens, empty continued pages, three-page traversal and final-page errors are tested.

401 requires reauth; explicit insufficient-permission 403 requires event scope; ACL 403/404
means unavailable; quota 403/429 preserves rate limiting; network/5xx are temporary; invalid
JSON/shape is invalid data. None is represented as an empty successful day. Persisted retry
is honored without sleeping on a SQL transaction. Six paused cross-technician reads allowed
another SQL acquisition within two seconds and health remained responsive, with zero idle
transactions. Dedicated advisory owners still consume DB connections; unlimited lifecycle
waiters and hard end-to-end deadlines remain TD-017/026, not silently declared solved.

## Privacy, frontend and contracts

Event PII sentinels appear only in the authorized response, not captured operational logs or
serialized audit rows. No event mirror, queue, cache table or event-content audit is added.
Credentials/state/raw payload do not enter ScheduleRead. Event reads use internal IDs, count,
duration and safe outcome codes: SUCCESS, NO_JOBS, NO_CALENDAR, CALENDAR_UNAVAILABLE,
EVENT_SCOPE_REQUIRED, REAUTH_REQUIRED, RATE_LIMITED, TEMPORARY_PROVIDER_FAILURE,
STALE_ASSIGNMENT and INVALID_PROVIDER_DATA, plus bounded operational failure codes.

Both routes retain no-store, nosniff and no-referrer on success and 401/404/422/500 paths;
provider state errors use the same protected path. Browser fetch uses no-store; there is no
service worker. Unsafe links are inert or cause conservative normalization failure; only exact
HTTPS calendar.google.com is clickable and target=_blank uses noopener noreferrer.
Script/image/HTML-entity/Markdown payloads stay React text. Controls including bidi overrides
are removed by normalization; ordinary Unicode/emoji and readable whitespace remain.
The real 500-job browser test retains wrapping, scrolling and no page-wide horizontal overflow.

Today and Preview request tests cover slow A, navigation to B, B success/failure, then A
completion. Old content cannot overwrite B or recover an obsolete success after B fails.
Refresh hides prior data, permits retry after failure and coalesces triple clicks; Strict Mode
issues one intended initial read. Unmount/close aborts, and completions are ignored even when
mock transport ignores cancellation. Preview identity is keyed by technician and assignment.

Fake provider selection is guarded by test environment/local test DB configuration; the CLI
harness has its own destructive-test guard. No production event injection, fake-scope grant,
auth bypass or new test endpoint was added. Browser timezone fixtures call pure Python and
fulfill local browser requests. OpenAPI/TypeScript fields and nullability are unchanged;
date labels and wall-clock strings remain separate from machine-readable provider instants.

## Performance

30 iterations per case, local Windows environment; concurrent test/build activity makes these
indicative measurements, not a service-level guarantee. No network or DB is included.

| Input                                 | Jobs after filter | Median ms |  p95 ms |
| ------------------------------------- | ----------------: | --------: | ------: |
| 0 jobs                                |                 0 |     0.002 |   0.014 |
| 5 jobs                                |                 5 |     0.170 |   0.422 |
| 20 jobs                               |                20 |     0.671 |   1.532 |
| 100 events before filtering           |                50 |     2.573 |   3.684 |
| 20 descriptions of 100,000 characters |                20 |   146.102 | 156.795 |

## Mutation evidence

All ten required meaningful mutations were killed by assertions, not collection errors:

| Temporary change                                               | Detecting regression                          |
| -------------------------------------------------------------- | --------------------------------------------- |
| Browser-local job time                                         | Visible wall-clock component assertion        |
| Remove final assignment recheck                                | A-to-B final HTTP response race               |
| Description keywords exclude jobs                              | Description-only keyword regression           |
| Remove provider cancelled filter and domain cancellation guard | Valid-looking cancelled title                 |
| Stop after first page                                          | Three-page/empty-page recurring fetch         |
| Return partial data after final-page transport failure         | No-partial pagination regression              |
| Saturday targets Sunday                                        | Seven actual-date weekday cases               |
| Allow stale A completion                                       | Today and Preview A/B rendered content tests  |
| Remove persisted event-scope preflight                         | Scope-only capability/provider-call assertion |
| Remove route and middleware no-store                           | Authorized/error response header matrix       |

Each experiment restores original bytes in finally and verifies SHA-256 equality. Temporary
runners/logs stay ignored under .local and are not committed. The no-store mutation was repeated
after the unexpected-500 fix to cover the final header implementation.

## Technical debt and release gates

No new debt ID and no existing obligation closed. TD-015 now has a measured/bounded daily
rendering path; TD-017 has safe event outcome diagnostics and free transaction-pool evidence;
TD-026 retains global admission/quota obligations. These are partial remediation, still OPEN.
TD-027 dedicated Google TEST acceptance remains manual; synthetic browser/HTTP tests cannot
prove real consent/project settings, ACL/private visibility or Google recurrence behavior.

Pilot blockers remain TD-010/011/012/013/014/017/018/022/023/025/026/027. TD-014 is overdue.
Production additionally requires TD-016/019/020; TD-015/024 remain later-scale obligations.
Counts stay 27 total, 10 RESOLVED, 17 OPEN (0 critical, 2 high, 12 medium, 3 low unresolved).

## Verification results

Final verification (isolated local PostgreSQL/fake providers):

| Gate                                                 | Result                                                                                                  |
| ---------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| Full backend                                         | 557 passed, 235.68 seconds; no failures or warnings in final run                                        |
| Stage 0/API/auth                                     | 86 passed within full suite (38 independent Stage 0 audit regressions)                                  |
| Telegram full / focused                              | 133 in full suite; 18 selected lifecycle/privacy regressions passed                                     |
| Stage 2 Google/security                              | 128 passed within full suite                                                                            |
| Stage 3 original / independent                       | 107 + 103 = 210 passed; final separate focused rerun: 210 passed in 49.88 seconds                       |
| Incremental/OAuth/refresh selection                  | 52 passed                                                                                               |
| Timezone/DST/date/work-window selection              | 54 passed                                                                                               |
| Concurrency/lifecycle/pool selection                 | 75 passed                                                                                               |
| Privacy/redaction/auth-cache selection               | 24 passed                                                                                               |
| Filtering/pagination/recurrence/size selection       | 37 passed                                                                                               |
| Frontend Vitest                                      | 90 passed across 6 files                                                                                |
| Chromium development                                 | 20 passed, final rerun 3.1 minutes                                                                      |
| Chromium production images                           | 20 passed, final rerun 2.7 minutes                                                                      |
| Native production build / strict TypeScript / ESLint | PASS                                                                                                    |
| Ruff / Ruff format                                   | PASS, 98 Python files                                                                                   |
| Prettier / git diff whitespace                       | PASS                                                                                                    |
| OpenAPI and generated TypeScript                     | byte-identical on repeated generation; live application schema matches                                  |
| Alembic                                              | fresh/populated historical upgrades, guarded downgrade/re-upgrade, zero schema drift; head c3e410a20917 |
| Compose / images / isolated health                   | PASS; API rebuilt after final parser fix, final image drift check passed                                |
| Source secret scan                                   | 194 Git-visible files, zero findings                                                                    |
| Runtime/browser/local static artifact scan           | 22 text files, zero credential/key/code/PII markers                                                     |
| Actual production browser bundles                    | 19 files, zero credential markers                                                                       |
| Required mutations                                   | 10/10 killed; originals restored byte-for-byte; final no-store retest killed                            |

The full backend XML provides per-file counts. Focused selections were run separately;
the final full suite includes the additional malformed offset/updated regressions. Private
logs and synthetic screenshots are ignored under .local and apps/web/test-results. Today
and Preview screenshots were also visually inspected for readable time/title/date output.
Earlier runs showed only the existing PTB retry-after deprecation; the final full run used
PTB_TIMEDELTA=1 and passed without that warning.

Reproduction: use the repository test-only database guard, `.venv/Scripts/python -m pytest
apps/api/tests -q`, `npm test`, and `npm run test:e2e` in development and with E2E_BASE_URL
pointing at an isolated built-image stack. See the existing runbook for test credentials,
Compose and migration-validator commands. No private environment file or mutation runner
is part of this commit.

No Stage 4, Telegram delivery, schedule
sending or other new product stage was implemented. Only fake provider infrastructure was
used; public Google documentation was read as explicitly requested, but no Google account,
OAuth/token endpoint, Calendar API, business calendar or real Telegram user/group was contacted.

Disposable audit services were stopped after verification; the original application stack was not modified.
