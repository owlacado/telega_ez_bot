# Stage 3 calendar events verification

Starting branch: `codex/stage2-google-calendar-quality-audit`.
Starting HEAD: `253071c8059c711e080c0e564b1253f6a7d0ebc7`, clean.
Implementation branch: `codex/stage3-calendar-events`.
Commit message: `feat: add technician calendar event views`. No push.

## Scope and architecture reviewed

Verified the official Events.list, event resource, recurrence, timezone, narrow scope and incremental
OAuth documentation before implementation; links and exact rules are in STAGE3_CALENDAR_EVENTS.md.
Audited state/PKCE/session/account protections are retained. Only an optional same-account event upgrade
is added. granted_scopes remains canonical capability state; the attempt flag binds requested intent.
Provider operations remain read-only. No event table, background sync, Telegram schedule delivery,
acknowledgment, accounting, event editing or Stage 4 work was added.

Both manager-authorized projections fetch a bounded calendar-local day, reject incomplete provider
results and recheck lifecycle/assignment/session after I/O. The shared filter and structured schedule
projection handle title-only exclusions, exact 08:00–22:00 starts, all-day/provider cancellations,
numbering/tie-breaks, unnumbered jobs and cleaned preview titles. Date windows cover DST and the next
workday skips Sunday only. Browser timezone never changes operational display times.

## Self-audit findings and fixes

No unresolved CRITICAL or HIGH findings remain in the Stage 3 change. Existing HIGH debt remains open.
The final review covered scope reduction/reconnect, provider parse/error boundaries, database snapshots,
PII/logging, pagination consistency, date/DST, frontend request identity and assignment races.

- **MEDIUM, fixed:** Full title filtering must precede display truncation. A cancellation keyword after
  500 characters now excludes the job while the returned display title remains bounded.
- **MEDIUM, fixed:** Discovery refresh must persist reduced granted scopes even without token rotation.
  Event capability no longer remains advertised after refresh explicitly reports its removal.
- **MEDIUM, fixed:** An explicitly empty refreshed scope set is rejected rather than treated as an
  omitted scope response and replaced by requested defaults.
- **MEDIUM, fixed:** Active/cancelled copies of the same ID across pages fail the complete fetch; a
  cancelled tombstone cannot silently leave an active job in the result.
- **LOW, fixed in test infrastructure:** Existing Stage 0 browser expectations referenced the removed
  placeholder and disabled send button; they now verify persisted assignment and enabled preview.
- **LOW, fixed in test infrastructure:** Repeated full browser runs accumulated login rate counters.
  The existing private CLI now resets counters during per-test bootstrap only after its loopback,
  disposable-database guard. Production login limits/routes are unchanged. Test passwords are still
  cleared before failure artifacts; no production test route or provider injection endpoint was added.

The initial Stage 2 regression run found three provider test doubles needing the new optional scope
argument; only their call signatures changed, not security assertions. Final regressions are below.

## Regression coverage

Backend tests exercise real PostgreSQL assignments and session state, fake providers and synthetic
requests responses. Live Google transport is forbidden by autouse test guards; browser requests are
restricted to loopback hosts. Coverage includes:

- Scope absence, partial upgrade, wrong account, new/omitted refresh tokens, retained-token capability,
  replay, expiry and preservation of Calendar discovery; existing Stage 2 security regressions remain.
- Three event pages, empty continued page, recurrence metadata, identical/conflicting IDs, conflicting
  cancelled status, repeated/malformed tokens, partial provider failure and payload/page caps.
- All explicit excluded title variants; description keywords retained; 07:59/08:00/21:59/22:00/22:01;
  all-day and cancelled events; full title before truncation; numbering, ties, unnumbered jobs and cleanup.
- Eastern/Pacific spring/fall 23/25-hour windows, normal days, offset/explicit timezone parsing,
  ambiguous or nonexistent offset-free times, preserved 08:00 display and all seven next-day rules.
- Missing start/end, reversed duration, bad timezone, oversized text, control/Unicode/script-looking
  data, unsafe links and 401/403-scope/403-ACL/403-quota/429/5xx/network errors.
- Unavailable/reassigned/deleted technician, disconnect, generation upgrade and revoked session during
  fetch. Final responses discard stale jobs. Concurrent second read is BUSY; no idle SQL transaction
  exists while the provider is blocked.
- Anonymous access, no-calendar/scope/unavailable/reauth states, privacy-minimal error/log context,
  valid empty results, on-demand Today/preview and calendar-local target dates.

Frontend covers state distinctions, loading/refresh, literal long content, cleaned versus raw titles,
weekend labels, modal lifecycle, Strict Mode deduplication, duplicate refresh, aborted transport that
still resolves, old success after newer failure, old failure after newer success and close/reopen.
Production screenshots of Today and preview were visually inspected: readable wall-clock jobs, bounded
text, optional notes, explicit date/zone and read-only preview without a Send button.

## Mutation experiments

All ten temporary breaks were detected. Every altered source file was restored byte-for-byte in a
finally block, and no mutation code is committed. Private logs remain under .local/stage3-mutation-*.

| Mutation                             | Detecting test                               | Result |
| ------------------------------------ | -------------------------------------------- | ------ |
| Remove event-scope preflight         | preflight scope state and zero event calls   | KILLED |
| Disable title exclusions             | all explicit title variants                  | KILLED |
| Filter description too               | valid title with cancellation notes          | KILLED |
| Remove early cutoff                  | exact work-window boundary cases             | KILLED |
| Stop after first page                | three-page recurring/empty-page fetch        | KILLED |
| Return partial data on later failure | later-page network failure                   | KILLED |
| Use browser-local display time       | 08:00 calendar time under Pacific browser TZ | KILLED |
| Accept stale technician response     | navigation old-success/old-failure tests     | KILLED |
| Choose Sunday after Saturday         | seven-weekday date table                     | KILLED |
| Allow cancelled provider event       | cancelled event with valid title/times       | KILLED |

## Final quality gate

| Gate                                | Result                                                                                                                    |
| ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| Full PostgreSQL backend             | 454 passed, 492.89 seconds; 3 existing PTB deprecation warnings                                                           |
| Stage 0/auth regressions            | 86 passed within full suite                                                                                               |
| Telegram regressions                | 133 passed within full suite                                                                                              |
| Stage 2 Google/security regressions | 128 passed; standalone final run 82.25 seconds                                                                            |
| Stage 3 event suite                 | 107 passed; standalone final run 30.90 seconds                                                                            |
| Focused concurrency                 | 45 passed, 409 deselected, 51.72 seconds; includes Stage 3 lifecycle and request deduplication                            |
| Timezone/DST/date selection         | 21 passed, 86 deselected, 4.55 seconds                                                                                    |
| Frontend full suite                 | 82 passed across 6 files                                                                                                  |
| Development Playwright              | 16 passed, 4.9 minutes                                                                                                    |
| Production-image Playwright         | 16 passed, 3.4 minutes                                                                                                    |
| Native production build             | PASS                                                                                                                      |
| Strict TypeScript / ESLint          | PASS                                                                                                                      |
| Ruff / Python format                | PASS; 97 files                                                                                                            |
| Prettier / Git whitespace           | PASS                                                                                                                      |
| Contract determinism                | Two regenerations byte-identical; snapshot check PASS                                                                     |
| Migrations / schema drift           | Fresh/historical/populated/downgrade safety PASS; one head c3e410a20917; native and actual image drift zero               |
| Docker Compose / builds / startup   | PASS; final API/web images and healthy isolated DB/API/web                                                                |
| Git-visible secret scan             | 191 files, zero findings                                                                                                  |
| Runtime/browser artifact scan       | 22 static/log text files and 19 actual production browser bundles, zero credential/key/code/injected-private-data markers |
| Mutations                           | All 10 killed; source restored byte-for-byte                                                                              |

The first production browser run exposed the obsolete placeholder expectation; the next repeated run
hit existing login throttling. Both causes were corrected in isolated test infrastructure before the
final full 16-test pass. Production auth behavior was not relaxed. UTF-8 event metadata cases explicitly
retain emoji/Arabic text and are covered by the standalone final event/frontend runs.

## Migration and operations

New head c3e410a20917 adds only the OAuth-attempt request_event_access boolean with false default.
Fresh upgrade, historical Stage 0/1 upgrades, populated Stage 2 preservation, destructive downgrade
refusal, supported rollback/re-upgrade and schema drift all pass. An actual pending event-upgrade
attempt loses its verifier and is consumed on downgrade; a normal attempt remains intact. Re-upgrade
preserves those results. No event PII table exists.

Native backend tests use dedicated loopback PostgreSQL port 5439. Development browser tests use a
separate disposable database on 5443; production images use isolated Compose project
technician-hub-stage3-calendar-events on 3005/8005/5442. APP_ENV=test and fake providers are used.
The original user stack is not reset or replaced. All dedicated test containers are stopped at completion.
Successful reads add no business audit events. Event content never goes in operation logs. Default
Python logger configuration controls whether safe INFO context is emitted; this is not a new metrics
or alerting platform. External pagination snapshot guarantees, global admission budgets, atomic
provider-token/DB commit, key recovery and live sandbox acceptance remain documented limitations.

## Technical debt and manual acceptance

No new IDs and no newly resolved items: 27 total, 10 resolved, 17 open; unresolved severity
0 CRITICAL / 2 HIGH / 12 MEDIUM / 3 LOW. Stage 3 evidence updates TD-015/017/025/026/027 and records the
unchanged TD-010/011/014 obligations. Internal-pilot blockers remain
TD-010/011/012/013/014/017/018/022/023/025/026/027; production additionally requires TD-016/019/020.
TD-015/024 remain LATER SCALE. Overdue TD-014 is explicitly not closed by event projections.

GOOGLE_CALENDAR_INTEGRATION.md contains the dedicated TEST-account event/recurrence/DST runbook.
It was not executed against Google. Only official documentation was accessed; no Google API/business
calendar/account was contacted. No schedule message was sent and no Stage 4 delivery was implemented.
Commit hash and final clean Git status are reported in the task response after all gates pass.
