# Stage 1 security and privacy

This is a local-only onboarding implementation, not production security certification. Ports bind to loopback. Do not enter real DL/SSN fields: field encryption remains deferred. A trusted local administrator with database/filesystem access can change data; the app does not claim to defend against a compromised host.

## Manager boundary

Argon2id uses argon2-cffi 25.1.0 with 64 MiB memory, three iterations and parallelism four. Bootstrap accepts hidden interactive passwords only (14–128 characters), creates no default administrator, and has no registration/reset HTTP endpoint. Username normalization is lower-case. Login failure responses do not reveal whether the username exists. Unknown users perform a dummy Argon2 verification. Shared DB throttles enforce 30 attempts per peer and eight per username in fifteen minutes. Because the local Next proxy is one peer, that peer budget is intentionally shared; arbitrary forwarded IP headers are not trusted.

Sessions contain 32 random bytes. Only their SHA-256 digests are stored. Session lifetime defaults to eight hours, is checked server-side on every business request, and is bounded to at most 24 hours. Login rotates an existing cookie session; logout revokes it in PostgreSQL. The CLI can revoke all sessions for a manager. Cookies use HttpOnly, SameSite=Strict and Path=/. Secure is mandatory outside development/test. Local HTTP allows Secure=false only for exact loopback origins; it is an explicit development exception, not suitable for deployment.

Cookie-authenticated mutations require an exact configured Origin and a session-derived HMAC CSRF header. Login additionally requires the custom same-origin application header. Cross-origin preflight is rejected; no wildcard CORS is installed. Health and login are the only public API paths. All technicians/calendars/history/dashboard counts, Telegram state/actions, deletion, docs and OpenAPI require authentication. Unknown input fields are rejected. API responses use no-store and validation errors omit submitted values. Session tokens are never put in localStorage; its only app use is the existing sidebar preference.

## Invitations and trusted transport

Invitations are scoped to a bot, technician UUID, purpose and expected generations. Tokens have 256 bits of entropy, are 43 URL-safe characters and carry no PII. Only a hash is stored. Expiry defaults to fifteen minutes and applies to claiming and legacy approval. Revocation, regeneration, inactive status and deletion are rechecked transactionally. New private invitations are bearer capabilities: the first valid claimant connects automatically. Deliver links privately to the intended person; a misdelivered link can bind the wrong person. Existing invitations retain their original review policy after migration (automatic=false). Another technician's reserved account/group cannot be stolen, including competing claims/approvals.

Only the worker's Bot API transport provides identity updates. There is no browser-supplied user/chat-ID attachment API, public simulation endpoint or unauthenticated bypass. The isolated fake harness checks the exact test database name and loopback host and is never used by ordinary app startup. Real mode checks bot identity and webhook status, uses no takeover helper and never drops pending updates. Expected identity is mandatory. The token stays in ignored local configuration or a read-only worker secret file; it is absent from frontend/public variables and API responses.

The parser retains only required candidate metadata. It rejects bots, wrong contexts, channels, anonymous group senders and private chat/user mismatches. New group claims require the trusted non-anonymous sender to equal the already-linked private account and check the bot itself for membership/send restrictions. No administrator role is requested. Legacy review group checks retain their previous administrator/technician observations. A successful proof must be at most two minutes old at approval. A membership race remains possible after observation; group sends recheck bot access and technician membership when the bot is an administrator. Regular bots cannot reliably observe third-party departure; see TD-022. Availability never silently reassigns identity. Trusted migration conflicts preserve ownership and require explicit revalidation.

## Delivery and deletion

Only fixed onboarding/test content is supported. Managers select an approved private/group destination, confirm, and are rate limited. A browser cannot select an arbitrary ID. Automatic activation reuses the same technician advisory lock as sends, preventing replacement during an in-flight delivery. Queued jobs contain generations and are revalidated against current active bindings. Replacement/disconnect/deactivation cancel incompatible work. Technician-level locks serialize provider sends with manager changes/deletion without holding SQL transactions open over network calls.

Provider acceptance is not proof of reading. There is no exactly-once external-delivery guarantee. Network ambiguity and interrupted sends become UNKNOWN, with no automatic resend. Explicit rate-limit rejections permit bounded retries. Binding activation survives message failure. Already delivered external messages persist after local deletion; a send already in flight is allowed to finish before deletion obtains its serialization lock.

Deleting a technician cascades its binding, invitations/candidate metadata and notification rows. A late update/approval cannot recreate it. Local independent calendars and real provider accounts/groups remain. No real DL/SSN values were seeded during this work.

## Audit and retained data

Audit rows contain event UUID, optional manager UUID, actor kind, action, internal target UUID, time and bounded outcome only. No arbitrary metadata column exists. They record authentication outcomes, invitation/review/conflict actions, connection changes, tests/delivery outcomes and technician deletion. Raw updates, message contents, names/usernames, passwords, session/invitation tokens, DL and SSN are absent. Worker actors are identified by their service role; Telegram actor PII remains only in the candidate/binding while the technician exists.

After technician deletion, audit target UUIDs remain; they are pseudonymous internal references and are **not guaranteed anonymous**. Processed-update rows retain only bot/update IDs, timestamp and outcome; worker rows retain bot ID, offset, heartbeat and sanitized status. These have no technician PII payload. Notification/candidate records are not retained after deletion. Closed candidate records otherwise remain with the profile for review history. Manager records/sessions, hashed rate-limit keys, audit and deduplication records do not yet have scheduled age-based retention. Define retention/backup policies before operational use; backups may retain previously stored data. No claim of full data erasure from backups or external systems is made.

Logging is sanitized: low-level Telegram/HTTP library logs are suppressed because URLs can contain the token. Exceptions are mapped to fixed codes; worker/CLI top-level errors avoid dumping provider errors. No raw start commands, update bodies, cookies or invitation payloads are logged. API and worker SQL engines hide parameters. The Git-visible secret scanner checks common bot/API/private-key/session/link patterns and prints paths/rule names only; it is not a guarantee against every secret format. Browser traces are disabled because traces can capture credentials/links; screenshots use fictional data and stay ignored.

## Reference decisions

Checked current official references during implementation:

- [OWASP password storage](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html): maintained Argon2id rather than custom password hashing.
- [OWASP sessions](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html): random opaque server sessions, HttpOnly/SameSite/Secure policy, rotation, expiration and revocation.
- [OWASP CSRF](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html): explicit token/origin checks rather than relying on hidden buttons or SameSite alone.
- Telegram deep links, getUpdates, getWebhookInfo, getChatMember and Update documentation are linked with exact assumptions in [the onboarding runbook](TELEGRAM_ONBOARDING.md#telegram-assumptions-and-references).

Remaining hardening includes encrypted sensitive fields, comprehensive retention, MFA/recovery, deployment/TLS/network controls, external secret management and broader operational security review. None is presented as delivered in Stage 1.
