# Stage 1 — Secure Telegram onboarding

Implemented on the existing Stage 0 UUID-based architecture. Starting HEAD: `f10509369879df4ed6e0ab757e0887779f6f7129`, clean `codex/stage0-foundation`; work branch: `codex/stage1-telegram-onboarding`.

## Delivered

- Manager CLI bootstrap, Argon2id login, hashed server sessions, expiration/revocation, CSRF/Origin checks, throttling, protected business pages and API.
- Separate private and group invitations, hash-only opaque 256-bit single-use payloads, 15-minute expiry, revoke/regenerate, candidate capture and deliberate manager review.
- Group administrator, bot administrator and technician membership checks; recoverable errors and queued verification retry.
- Atomic unique approved bindings, generations, explicit replacement/disconnect, group suspension after private identity changes, active/deleted lifecycle guards.
- Trusted Telegram transport parser, real async adapter, optional polling worker, persisted offset/deduplication, per-bot exclusive poller, trusted membership/migration updates.
- Durable approval/test notifications with bounded safe retries and visible uncertain outcomes; explicit destination, confirmation and rate limit.
- Upper-left profile integration controls, local SVG QR, link copy, bounded visible-page polling, login/logout. Existing sidebar, cards, 2×2 grid, danger zone and ten-second exact-name deletion remain.
- Minimal audit, cascading candidate/job deletion, migrations, generated contracts, fake-provider PostgreSQL and browser verification.

## Preserved and deferred

Technician/calendar CRUD and assignment history remain. No Google Sheets mapping or manual Telegram ID entry exists. Calendar synchronization, schedule delivery, reports, accounting, expenses, receipts/contracts, GPS, Discord, public deployment, SSO, password recovery and field encryption are outside this stage.

Planned legacy command labels remain **Submit a report**, **Daily report**, **Expenses**, **Receipt**, **Get ID**. Only the last is currently supported, as `/getid` or `Get ID` in a private chat. No Google Forms mapping is used.

There were no dependency upgrades or downgrades to the established stack. Added pinned Argon2 and python-telegram-bot dependencies, their required transitive packages, and qrcode.react. No credentials were requested or discovered. No live Telegram calls were made. `C:\HVAC_TECH_CODEX` and `C:\MotoWatchdogProbe` were not read or modified.

This stage is automatically verified with fakes and local PostgreSQL, not yet live-verified or certified for production security.

## Onboarding completion from 14d2073

Extended the working implementation: new invitations connect automatically; PRIVATE_TELEGRAM and WORK_GROUP are separate credentials; group actor must equal the connected technician and bot administrator rights are unnecessary. Added live countdown, setup instructions, immediate creation, terminal polling stops and secondary technical IDs. Existing pre-upgrade invitations retain manager review, replacement/disconnect, outbox and all audit regressions remain. No calendar synchronization, schedule delivery, reports, accounting or GPS work was added. See TELEGRAM_COMPLETION_INVENTORY.md, TELEGRAM_ONBOARDING.md and TELEGRAM_COMPLETION_VERIFICATION.md for current scope/evidence.
