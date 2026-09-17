# Stage 0 engineering audit

Historical Stage 0 report. Its findings and results are retained as originally audited. For integration into the active Stage 1 branch and current verification, see [AUDIT_RECONCILIATION.md](AUDIT_RECONCILIATION.md); current debt status is in [TECH_DEBT.md](TECH_DEBT.md).

## Repository discrepancy and isolation

On September 17, 2026, the requested repository was clean at `9b2d87c822848efc5dd7f5e7c28c81e6fa81f74b` on `codex/stage1-telegram-onboarding`, not the expected Stage 0 branch. The requested `f10509369879df4ed6e0ab757e0887779f6f7129` exists. This discrepancy was reported before changes.

Audit target: exactly that Stage 0 commit, in `C:/HVAC_TECHNICIAN_HUB/.local/stage0-audit` on `codex/stage0-quality-audit`. The primary Stage 1 checkout and running app are preserved. No Stage 1 code or integrations are added by this audit. Findings apply to the Stage 0 baseline; they are not a claim that the already-existing Stage 1 branch lacks authentication.

Tests use an independent tmpfs PostgreSQL database on loopback port 5439, named `technician_hub_test`. No development database is downgraded or truncated.

## Method and scope

Reviewed every Stage 0 API route, Pydantic input/output schema, ORM model, relationship, initial migration, error handler, generated contract, frontend route, dialog/resource hook, Dockerfile and verification script. Inspected SQL injection/XSS boundaries, URL handling, sensitive fields, local deployment defaults and tracked environment files. Integration modules remain provider-neutral placeholders; no external service calls were added.

Initial regression runs were deliberately made before fixes: 47 backend cases passed and 16 failed, including invalid control characters, missing database checks, null normalization and a deterministic post-commit deletion race. Some failures represented the new version-confirmation contract, not a previously promised feature. Frontend baseline: 9 passed and 5 failed, reproducing stale identity, cancelled-request completion, confirmation reset, pending edit and duplicate-submit defects. An additional real connection-refusal test reproduced HTTP 500 before the database dependency fix.

## Findings and fixes

No CRITICAL finding. Two HIGH defect groups were fixed: stale identity during navigation and unsafe stale/double permanent deletion. High deferred security requirements are authentication/authorization, deletion audit history and sensitive-field protection. They remain intentionally out of scope; see the milestone-specific explanations in TECH_DEBT.md.

MEDIUM fixes cover calendar database constraints, response snapshots captured before releasing mutation locks, control-character validation and nullable license normalization, pending form locking, database/API failure recovery, consistent tokenized name search, text contrast, long-content wrapping, and dialog focus cycling/restoration. LOW debt covers runtime response validation depth and cross-browser/assistive-technology acceptance.

### Database and concurrency

PostgreSQL, not SQLite, is used throughout. Existing PK/FK cascades, nullable unique Telegram IDs, one-binding-per-technician constraints and both partial active-assignment indexes are retained. Added CHECK constraints reject blank calendar names and active assignments with null calendar IDs. Calendar API removal still deactivates history before SET NULL; direct deletion cannot leave an active orphan. No old migration was rewritten.

Concurrent tests cover two calendars assigned to one technician, two technicians claiming one calendar, technician update/delete, assignment/delete, calendar removal/assignment, identical independent technician creates and duplicate Telegram binding inserts. An injected PostgreSQL trigger fails dependent deletion and proves rollback leaves the technician, assignment and GPS binding intact. Snapshot-before-commit tests force another transaction to remove a calendar immediately after commit and verify the successful rename response still returns correctly.

Deletion requires the exact API literal plus a timezone-aware profile version under lock. The browser separately requires ten seconds and exact typed name; changing the displayed identity/version resets both. The timer is not an API security boundary. Failure leaves confirmation recoverable. Profile version checking does not cover independent binding/history changes; TD-013 records that limitation.

### Frontend and accessibility

Coverage includes Dashboard, Technicians, Detail, Calendars, sidebar, all dialogs, missing photos, loading/empty/not-found states, search, stale requests, pending and failed mutations, offline API, malformed JSON and structurally invalid JSON. Generated contracts remain the compile-time source of truth; invalid response shapes reach a recoverable route boundary.

Browser tests use 100-character first and last names and near-maximum calendar names at 1920x1080, 1440x900, 1366x768 and 1024x768. They check document/element overflow, reachable deletion action, forward keyboard cycling, Escape, focus restoration and axe WCAG A/AA rules. The initial audit found contrast ratios as low as 3.28:1 for small sidebar text and 532 pixels of detail-page horizontal overflow. Narrow text-color and wrapping changes preserve the existing layout and visual structure. This is not a full accessibility certification.

### Security review

No actual provider secrets or private .env files were found among tracked Stage 0 files. Committed database credentials are explicitly local sample credentials. Docker published ports bind loopback, runtime containers use non-root users, build contexts exclude .env, and there is no wildcard CORS middleware. SQL queries use bound SQLAlchemy expressions, React escapes displayed text, unsafe image URL schemes are rejected, and remote images load only in the browser with no referrer. These controls do not substitute for authentication or a production deployment policy.

List output omits license/SSN last4; detail output intentionally contains them. Full SSNs and unknown/mass-assignment fields are rejected. Validation and database error responses omit inputs, SQL and traces. SQLAlchemy parameter hiding was enabled as an additional defense. Driver license remains an opaque optional string, not a jurisdiction-specific validated credential. Fictional data only until open security debt is resolved.

### Test quality

The baseline uses real PostgreSQL integration tests and an end-to-end create/edit/assign/delete flow. Those are valuable but missed asynchronous state races, direct database invariants, response-after-commit races, offline driver failures, long content and keyboard restoration. Added tests assert persisted outcomes, visible UI behavior and bounded query counts. Component API mocks are retained for controlled timing/failure and complemented by real browser/API tests. Literal confirmation tests now supply a valid version so they cannot pass only because another required field is absent. Vitest discovery now includes both .test.ts and .test.tsx.

## Verification

Final executed commands and results follow. All destructive migration/performance checks are restricted to the isolated audit test database. Browser and production container checks use separate ports from the original Stage 1 app.

### Completed checks

| Check                                                                    | Result                                                                                                                                                                                              |
| ------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `.venv/Scripts/python -m pytest apps/api/tests -q`                       | 69 passed; includes 36 new audit cases, PostgreSQL concurrency, FK/uniqueness/check constraints and real database refusal                                                                           |
| `npm test`                                                               | 20 passed; baseline was 8. New cases cover resource navigation/cancellation, stale mutation callback, delete reset/double click/retry, pending save, search, photo fallback and malformed responses |
| `scripts/validate_migrations.py`                                         | Fresh upgrade, populated original Stage 0 upgrade/downgrade/upgrade, sentinel preservation, downgrade to base/re-upgrade and two Alembic metadata checks passed; head `a04e70c92001`                |
| `scripts/check_contracts.py` and contract generation                     | OpenAPI matches application; TypeScript regenerated for required deletion version and query validation                                                                                              |
| `ruff check apps/api scripts` and `ruff format --check apps/api scripts` | Passed, 31 Python files formatted                                                                                                                                                                   |
| `npm run lint`, `npm run typecheck`, `npm run format:check`              | Passed                                                                                                                                                                                              |
| `npm exec -w apps/web -- playwright test`                                | 9 passed in development and 9 passed against Docker production; all four viewport sizes and all dialog axe scans passed                                                                             |
| `npm run build`                                                          | Optimized Next.js build passed                                                                                                                                                                      |
| `docker compose -p technician-hub-stage0-audit config --quiet`           | Passed with independent audit ports                                                                                                                                                                 |
| Isolated Compose build and `up -d --wait db api web`                     | Both images built; PostgreSQL and API healthy; web started; direct and proxied `/api/health` both returned connected                                                                                |
| `git diff --check`                                                       | Passed                                                                                                                                                                                              |

The isolated Docker stack uses web 3003, API 8003 and PostgreSQL 5440. Native Playwright uses 3001/8001 and the separate tmpfs test database on 5439. Do not run the baseline `scripts/verify.ps1` unchanged in this side-by-side worktree: it starts the default project's test database on 5437. The audit invoked the equivalent checks explicitly with isolated project/ports. Existing PostgreSQL data and the Stage 1 application on 3000/8000 were not migrated or reset.

### Query profiling

Four requests per endpoint/sample size, one cold and three warm; each technician had one active local calendar. Counts include ORM relationship loading. Measurements are local Windows-to-Docker PostgreSQL / ASGI timings, not production latency guarantees.

| Technicians / calendars | Endpoint    | SQL queries per request | Cold ms | Warm median ms | Response bytes |
| ----------------------- | ----------- | ----------------------- | ------- | -------------- | -------------- |
| 10                      | technicians | 5                       | 129.79  | 19.54          | 4,331          |
| 10                      | calendars   | 5                       | 27.51   | 17.23          | 2,531          |
| 50                      | technicians | 5                       | 85.22   | 22.80          | 21,651         |
| 50                      | calendars   | 5                       | 26.89   | 21.10          | 12,651         |
| 250                     | technicians | 5                       | 102.00  | 36.67          | 108,251        |
| 250                     | calendars   | 5                       | 39.37   | 37.63          | 63,251         |

No per-technician N+1 growth occurred in this dataset. Dashboard loading invokes both list endpoints, so its initial read is approximately ten SQL statements. History endpoints and list payloads remain unbounded; extensive assignment history was not benchmarked. TD-015 records pagination/projection work for later scale.

### Mutation / adversarial evidence

Two temporary source mutations were executed in the isolated audit worktree after ordinary tests passed:

1. Bypass the profile-version comparison: the stale-delete regression failed because a renamed profile was deleted.
2. Change the exact DELETE literal to unrestricted string: both wrong-literal regressions failed because invalid confirmations were accepted.

Both source files were restored byte-for-byte in `finally` blocks. All five affected tests passed after restoration. No mutation is included in the commit. Baseline red-to-green tests, direct raw SQL violations, concurrent transactions, simulated dependent deletion failure and post-commit interleaving provide additional adversarial evidence.

### Remaining boundaries

This audit does not certify production readiness. The twelve OPEN debt items in TECH_DEBT.md include three HIGH security requirements intentionally deferred by Stage 0 scope. Browser accessibility checks do not replace screen-reader/cross-browser testing. Generated contracts are compile-time checks rather than runtime validators. A profile delete version does not cover all relationship history. A migration encountering invalid legacy rows fails validation rather than silently rewriting them; operators must repair such rows deliberately.

The original Stage 1 branch requires a separate reconciliation before adopting these changes: it has its own migration lineage, onboarding contracts and security implementation. This audit has not merged into or modified that branch, and nothing was pushed.

### Browser card rendering

Measured full navigation until all matching cards appeared, with temporary fictional records cleaned afterward. Both builds passed 10, 50 and 250-card checks without horizontal overflow.

| Cards | Development ms / list requests | Docker production ms / list requests |
| ----- | ------------------------------ | ------------------------------------ |
| 10    | 721 / 2                        | 173 / 1                              |
| 50    | 759 / 2                        | 386 / 1                              |
| 250   | 1,679 / 2                      | 668 / 1                              |

Development StrictMode creates one cancelled initial request and one active request; production issues one list fetch. No per-card API request pattern was observed. These timings include browser navigation/rendering and are local observations, not service-level targets.

All nine browser scenarios passed in each environment. Screenshots and traces are local ignored artifacts under `apps/web/test-results/development` and `production`; representative long-name detail and delete screenshots were visually inspected. Dialog tests require the entire deletion button to be in the viewport, check keyboard cycling/Escape and verify focus returns to the opening control. The production stack and disposable test container were stopped after verification; the audit worktree and production volume remain for review/reuse.
