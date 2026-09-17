# Telegram onboarding completion verification

Starting branch: `codex/stage1-telegram-onboarding`. Starting clean HEAD: `14d20737360c77f030e8c07e8678d650195c956f`. Final commit subject: `feat: complete Telegram technician onboarding`. This report belongs to that commit; use `git log -1` for its hash. No push is authorized or performed.

## Existing implementation and scope

The [pre-change inventory](TELEGRAM_COMPLETION_INVENTORY.md) was written before code edits. Existing authentication, CSRF/origin protection, invitations, manager review, row/advisory locks, binding generations, unique identities, separate long-poll worker, outbox, fake provider, UI and regression tests were extended. No alternate onboarding service or public test endpoint was introduced. Calendar synchronization, schedule delivery, reports, expenses, accounting and GPS remain outside this change.

## Architecture and security results

New PRIVATE_TELEGRAM invitations bind automatically from a trusted private `/start` update. New WORK_GROUP invitations bind only from a group/supergroup command sent by the exact previously linked private user. Anonymous senders, bots, channels and mismatched purposes are rejected. Bot membership/send permission is verified; ordinary membership is sufficient. Canonical technician names remain authoritative; Telegram names, usernames and group titles are metadata.

The existing invitation table retains hash-only 256-bit random credentials, 900-second configurable server-enforced expiration, purpose/technician/bot/generation scope, revocation and one-use consumption. Creation returns a credential once; status/list APIs expose neither raw token nor digest. Replacing an open invitation atomically revokes it. Failed automatic setup consumes the credential; recovery requires a new invitation.

Technician row locks serialize issuance, claim and revocation. Technician advisory guards coordinate claims with deletion, identity replacement and in-flight sends. Identity advisory locks and PostgreSQL unique columns prevent one user or group binding to two profiles, including simultaneous claims. Binding activation, invitation closure, audit and outbox insertion share one transaction. Provider checks happen outside SQL transactions, followed by locked actor/generation rechecks. Duplicate Telegram update IDs remain deduplicated.

Private and group disconnect are independent manager-confirmed actions. Removing/replacing private identity preserves the group reservation but suspends its delivery until explicit revalidation; a new person never inherits an old group's delivery authority. Old tokens and queued stale work are invalidated. Unrelated integration state is preserved.

The existing manager capability/session/CSRF protections apply to create, revoke, status, disconnect and review endpoints. Telegram claims use the invitation capability and trusted provider update, never a public fake-update API. Audits record invitation creation/replacement/revocation, connection/disconnection and meaningful rejected attempts with safe action, actor, subject, timestamp and outcome fields. Tokens and raw payloads are omitted.

Worker logs contain structured state/error codes; configuration and provider errors are sanitized. Missing real credentials fail before constructing a Bot client. Unknown private users receive manager-link guidance without profile creation or identity enumeration. Success is sent through the durable outbox; uncertain provider delivery is not retried blindly. Connected `/start` and ordinary private messages provide a concise home response.

## UI and platform semantics

The existing profile layout now creates an invitation with one Connect click, displays a second-by-second countdown, local QR, open/copy/setup-instructions/cancel actions, and polls at about two seconds while pending. Terminal states, errors and expiration stop the invitation poll and clear displayed credentials. Hidden-page pause, unmount cancellation, stale-response suppression and duplicate-submit guards are covered. Connection success appears without reload. Username/name is primary; technical IDs are collapsible. A separate work-group dialog and independent disconnect confirmations complete the browser path.

Official Telegram documentation was checked before implementation: [deep links](https://core.telegram.org/bots/features#deep-linking), [bot links](https://core.telegram.org/api/links#bot-links), [privacy-mode commands](https://core.telegram.org/bots/faq#what-messages-will-my-bot-get), [getChatMember](https://core.telegram.org/bots/api#getchatmember) and [updates](https://core.telegram.org/bots/api#update). Private `start` and group `startgroup` carry up to 64 base64url characters; this implementation uses 43. Group selection delivers an addressed Start command. The dialog supplies a scoped-command fallback when the bot is already present or an administrator must add it. No admin permission is requested automatically.

Third-party membership queries/events are not generally available to an ordinary-member bot. Trusted command sender proves presence at claim time, not continuous future presence. This limitation and per-client live acceptance are TD-022; future sensitive group delivery requires a deliberate policy decision.

## Migration evidence

New revision `e7b310920001` follows `d6c2f8a14001`; integrated migrations were not edited. It translates PRIVATE_ACCOUNT invitation/outbox values to PRIVATE_TELEGRAM and adds the server-owned automatic flag. Existing rows become false to preserve their original manager-review authority; new rows default true. Legacy review tests seed that old policy explicitly rather than changing product defaults.

Validation passed for a fresh database, populated Stage 0 and Stage 1 upgrade paths, a populated reconciliation-head fixture containing a manager, pending invitation and queued delivery, downgrade/re-upgrade, one Alembic head, and no schema drift. Operational upgrade instructions require stopping the old worker, backup, migration, and coordinated deployment of matching code.

## Verification results

All automated Telegram behavior used fake providers; an autouse backend guard rejects real-adapter network operations. Browser claims use the existing guarded stdin harness against explicitly isolated test databases. No real Telegram account or technician was contacted, and no live credentials were requested or used.

| Check                                                                 | Result                                                                    |
| --------------------------------------------------------------------- | ------------------------------------------------------------------------- |
| Full backend, final code                                              | 181 passed, including 42 completion cases                                 |
| Explicit PostgreSQL concurrency selection                             | 10 passed; also included in full suite                                    |
| Explicit Stage 0 audit backend regressions                            | 38 passed; also included in full suite                                    |
| Full frontend                                                         | 36 passed                                                                 |
| Development Playwright                                                | 10 passed, including Stage 0 audit, lifecycle and Telegram critical paths |
| Production Playwright                                                 | 10 passed on standalone production web/API with fake Telegram             |
| Production Next build                                                 | Passed in Docker build                                                    |
| Strict TypeScript and ESLint                                          | Passed                                                                    |
| Ruff lint and formatting                                              | Passed                                                                    |
| Prettier formatting                                                   | Passed                                                                    |
| Generated OpenAPI and deterministic TypeScript regeneration           | Passed                                                                    |
| Alembic upgrades, roundtrips, populated preservation, one head, drift | Passed                                                                    |
| Compose configuration, API/web Docker build                           | Passed                                                                    |
| Isolated Docker startup and API/web/database health                   | Passed                                                                    |
| Git whitespace and secret-pattern scan                                | Passed; zero secret findings                                              |

Ignored local evidence is under `.local/onboarding-*.log`; those logs are not committed. Production verification used project `technician-hub-onboarding-completion` on loopback ports 3005/8005/5442. Native backend/migration/development browser verification used a separate disposable database on 5439. The user's original application database was not reset. Task-created verification services are stopped after validation.

Adversarial coverage includes token replay, expiration, revocation, replacement, deleted/inactive technicians, context/purpose swap, cross-profile invitation operations, account/group uniqueness, simultaneous claims and issuance, revoke/claim races, identity changes after provider verification, injected activation rollback, provider failures, unknown users, malformed envelopes/nested fields, huge/forwarded payloads, missing fields, forged sender structures, authentication failures and secret-free worker logs. Browser coverage includes automatic private/group success, independent disconnect, terminal credential cleanup, countdown, cancellation, duplicate submissions and failed-poll recovery.

## Focused self-audit

Reviewed the new token lifecycle, claim/replace/disconnect locking, authorization, transport trust boundary, provider error handling, migration policy, logs, stale UI responses and test gaps. No remaining CRITICAL or HIGH issue was identified in the new onboarding work. This does not close pre-existing project security debt.

Concrete corrections made during implementation/review:

- Reused atomic activation under existing technician/send guards and identity locks; rechecked group actor after network verification.
- Preserved old invitation review authority instead of silently upgrading already-issued credentials.
- Rejected malformed/oversized/forwarded updates safely and sanitized worker errors/logs.
- Required explicit CONNECTED status as well as an identifier when reporting an approved connection; added a regression test.
- Cleared credentials on terminal/error states and prevented stale polling results from restoring them.
- Added transaction-failure, concurrency, no-live-provider, missing-secret and log-privacy coverage.

## Debt and manual acceptance

[TECH_DEBT.md](TECH_DEBT.md) retains all prior entries: 22 total, 10 RESOLVED, 12 OPEN. Open severities are CRITICAL 0, HIGH 2, MEDIUM 8, LOW 2. New: TD-022 MEDIUM, Telegram membership visibility/live acceptance. Resolved by this completion: none. TD-014 and TD-017 have partial improvements documented but remain OPEN.

Internal-pilot blockers remain TD-010 (audit retention/accountability), TD-011 (sensitive data protection), TD-012 (deployment), TD-013 (concurrent editing), TD-014 (provider state invariants), TD-017 (observability/timeouts), TD-018 (external profile images), and TD-022 (Telegram acceptance/membership policy). TD-014 retains its original overdue BEFORE STAGE 1 milestone.

The [onboarding runbook](TELEGRAM_ONBOARDING.md#manual-sandbox-verification--not-run-automatically) contains exact safe manual commands. Use a dedicated TEST bot, fictional technician, your own test account and isolated group; store its token only in an ignored secret file; set expected identity and real mode deliberately; run only one poller; verify private/group success, actor mismatch, replay, expiration, revocation, permission loss and disconnect/reconnect; stop the worker and restore disabled mode. No manual live check was performed automatically.
