# Stage 0 audit reconciliation into Stage 1

## Scope and Git decision

This task integrates the complete Stage 0 quality audit without adding Stage 1/2 features. Starting checkout: `C:/HVAC_TECHNICIAN_HUB`, branch `codex/stage1-telegram-onboarding`, clean HEAD `9b2d87c822848efc5dd7f5e7c28c81e6fa81f74b`.

Verified graph before changes:

```text
f10509369879df4ed6e0ab757e0887779f6f7129  Stage 0
|-- 79ff1faf8f7218da32db9d0b07488436656a9292  Stage 0 audit
`-- 239abf5  Stage 1 implementation
    `-- 9b2d87c822848efc5dd7f5e7c28c81e6fa81f74b  Stage 1 runbook
```

`git merge-base --is-ancestor 79ff1fa 9b2d87c` returned 1: Stage 1 did **not** contain the audit. `f105093` is the common ancestor of both lines; neither `79ff1fa` nor `9b2d87c` is an ancestor of the other.

Created backup branch `codex/stage1-before-audit-reconciliation` at the original Stage 1 HEAD. Applied the complete `79ff1fa` with `git cherry-pick --no-commit`, resolved conflicts semantically, and prepared a single commit named `chore: integrate Stage 0 audit fixes` on the existing Stage 1 branch. No existing commit was rewritten and nothing is pushed. The original audit worktree/branch remains intact. Cherry-picking carries the audit changes into the active line; the original audit commit hash does not become a literal ancestor. Stage 0 and both original Stage 1 commits remain ancestors of the reconciliation commit.

## Conflict resolutions

Nine files conflicted:

| File                                        | Resolution                                                                                                                                                                                                                 |
| ------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `apps/api/hub/main.py`                      | Kept Stage 1 engine state, dummy password hash, auth middleware and auth/Telegram routers. Its existing SQL parameter hiding already fulfills the audit requirement.                                                       |
| `apps/api/hub/technicians/router.py`        | Kept Stage 1 technician advisory guards, inactive-connection invalidation and atomic deletion audit. Added expected profile version comparison under row lock before deletion/audit, and response snapshots before commit. |
| `apps/web/src/app/error.tsx`                | Retained a recoverable root boundary with accessible alert and reset button, using the audited error message. Protected workspace routing remains intact.                                                                  |
| `apps/web/src/app/globals.css`              | Retained all Stage 1 login/Telegram styles together with audited text contrast, fieldset reset and long-content wrapping. Fixed the additional GPS heading contrast failure discovered in combined verification.           |
| `apps/web/src/components/profile-panel.tsx` | Kept real Stage 1 TelegramConnections and the sensitive-data warning. Added synchronous mutation guard and disabled fieldset during saves/assignment.                                                                      |
| `docs/ARCHITECTURE.md`                      | Kept complete Stage 1 architecture and documented audit constraints, versioned deletion, transaction snapshots, path-keyed resources and the migration join. Explicitly documented the required deletion-contract change.  |
| `packages/contracts/openapi.json`           | Regenerated from the combined application: all auth/Telegram schemas remain and technician deletion requires expected_updated_at.                                                                                          |
| `packages/contracts/src/schema.d.ts`        | Regenerated from combined OpenAPI, rather than manually selecting either side. Verified deterministic generation.                                                                                                          |
| `scripts/validate_migrations.py`            | Preserved Stage 1 data fixtures and added audited calendar-name verification, both independently installed upgrade paths and manager/audit-event preservation.                                                             |

Existing migration IDs and dependencies are untouched. Added merge revision `d6c2f8a14001` with parents `4344e0e76774` (Stage 1) and `a04e70c92001` (audit). It has no destructive migration body. Fresh databases and existing databases at either head reach one combined head. Audit CHECK constraints intentionally reject invalid legacy data rather than silently repairing it.

## Audit preservation and targeted regression fixes

All audit-added files, tests and fixes are retained. All 34 audit-changed paths remain present (including the Stage 1 protected route move). Backend test functions were compared against their source commits; no original audit or Stage 1 backend test function was removed. Browser tests now use Stage 1's authenticated manager/CSRF fixture; component imports follow the protected route group and mock the real Telegram state read. Stage 1 deletion tests now supply the reviewed profile version. The performance script authenticates a temporary manager while retaining its query-count assertions.

Retained coverage includes stale technician identity and cancelled/stale responses; profile-version deletion and exact confirmation; double-submit protection and failure recovery; direct PostgreSQL constraints, rollback and concurrent mutations; pre-commit response snapshots; locked forms; search token consistency; error boundaries; accessibility, dialog focus and overflow at four viewport sizes.

Three additional failures were reproduced during reconciliation and fixed within existing behavior:

1. **Authenticated database outage returned 500.** Stage 1 auth middleware had its own session outside the audited dependency and caught only SQLAlchemyError. It now also translates OSError into the same sanitized 503. The real connection-refusal regression covers both health and authenticated business requests.
2. **Same-tick Telegram invitation submission ran twice.** React busy state alone did not prevent a second invocation. The existing mutation wrapper now uses a synchronous ref guard, released on success/failure. A test reproduced two calls before the fix and now asserts one plus recovery after rejection.
3. **GPS placeholder heading failed contrast at 3.49:1.** The combined development browser run exposed this remaining low-contrast text. It now uses the audited text color; viewport tests explicitly scroll the heading into view to avoid below-the-fold coverage gaps.

A further integration test verifies a stale deletion produces no successful deletion event, while a confirmed current-version deletion preserves the Stage 1 manager/target/outcome audit record after the technician is gone. Stage 1 worker tests continue to verify pending delivery/deletion coordination.

## Technical debt

`TECH_DEBT.md` preserves all 21 IDs. Of the original 12 OPEN findings, only **TD-009 (authentication/authorization)** is RESOLVED by Stage 1, with active-manager session enforcement, protected reads/mutations/docs, Argon2 credentials, session expiry/revocation and CSRF/origin checks covered by tests. There are now 10 RESOLVED and **11 OPEN** entries.

TD-010 records Stage 1's atomic deletion event but remains OPEN for reason/version, append-only enforcement, retention and access policy. TD-012 records origin/CSRF/configuration/rate-limit progress while retaining deployment requirements. TD-014 records Telegram service state-machine/concurrency protection while retaining missing database invariants. TD-017 records bounded worker retries without claiming complete observability. No debt entry or original milestone was silently removed or moved; TD-014's BEFORE STAGE 1 requirement remains outstanding. The original Stage 0 audit report is retained as historical evidence with a pointer to this reconciliation.

## Verification

Verification uses a dedicated disposable PostgreSQL 18 database on loopback 5439 and a separate production-image Compose project `technician-hub-reconciliation` on web 3004, API 8004 and PostgreSQL 5441. Neither the primary development database nor the original Stage 1 app was reset or migrated. Browser onboarding uses the existing guarded fake transport with generated manager credentials; no real bot or external message is used. The web image is a production Next.js standalone build; the isolated backend uses APP_ENV=test for loopback cookies and the guarded fake provider.

| Check                                                                               | Result                                                                                                                                                                                                                                   |
| ----------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Full backend / PostgreSQL suite: `python -m pytest apps/api/tests -q`               | 139 passed.                                                                                                                                                                                                                              |
| Explicit audit regression rerun: `python -m pytest apps/api/tests/test_audit.py -q` | 38 passed.                                                                                                                                                                                                                               |
| Frontend: `npm test`                                                                | 27 passed across 4 files. Includes audit resource/API/component regressions and Stage 1 Telegram/login tests.                                                                                                                            |
| Development Playwright                                                              | 10 passed in 3.0 minutes after the contrast fix, including all 8 audit browser cases.                                                                                                                                                    |
| Production-image Playwright                                                         | 10 passed in 2.3 minutes on the final rebuilt image, including all 8 audit browser cases.                                                                                                                                                |
| Production frontend build                                                           | `docker compose -p technician-hub-reconciliation build api web` succeeded, including npm ci, next build, strict TypeScript and standalone output. Final CSS rebuild also succeeded and was used by the passing production browser suite. |
| Strict TypeScript / ESLint / Ruff                                                   | Passed (`npm run typecheck`, `npm run lint`, `ruff check apps/api scripts`).                                                                                                                                                             |
| Formatting                                                                          | Prettier and Ruff format checks passed.                                                                                                                                                                                                  |
| OpenAPI / generated TypeScript                                                      | `scripts/check_contracts.py` passed; regeneration produced identical schema.d.ts hash.                                                                                                                                                   |
| Migration validation                                                                | Fresh upgrade/downgrade/upgrade; populated Stage 0 round trip; existing Stage 1 and audited Stage 0 upgrades; manager/audit preservation; Alembic drift check all passed. Single head d6c2f8a14001.                                      |
| Performance                                                                         | Both lists used 6 queries at 10/50/250 records, including authentication. Warm median latency: technicians 24.62/32.44/45.75 ms, calendars 25.78/26.18/57.41 ms in this local run. No growing query count.                               |
| Docker configuration / startup                                                      | Both compose.yaml and compose.e2e.yaml validate. Isolated API/DB health checks pass; API health reports database connected and web returns HTTP 200 through login.                                                                       |
| Git whitespace / secret-pattern scan                                                | Working-tree and staged git diff --check passed. Secret-pattern scan: 151 Git-visible files, zero findings.                                                                                                                              |

The initial development browser run passed 9/10 and failed on the GPS heading contrast described above; no failing assertion was removed or weakened. Node emitted only non-failing color-environment warnings. Test logs and browser screenshots are local ignored artifacts under `.local/reconciliation-*` and `apps/web/test-results/`.

## Final repository state

Active branch remains `codex/stage1-telegram-onboarding`. The reconciliation commit is identifiable by the exact subject `chore: integrate Stage 0 audit fixes`; its finalized SHA is reported in the delivery message (a commit cannot embed its own resulting hash). No push and no local history rewrite. Final checks and clean status are verified after committing. Original audit and Stage 1 backup branches are preserved. The isolated verification containers are stopped after checks; the original Stage 1 development containers remain running and unchanged.
