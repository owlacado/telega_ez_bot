# Telegram technician onboarding

## Manager and technician flow

1. Sign in as a manager, create/open an active technician and select **Connect Telegram**. This creates a purpose-specific private invitation immediately. The dialog displays a live countdown, **Open Telegram**, **Copy link**, **Copy setup instructions**, a locally generated QR code and **Revoke invitation** (cancel). No Telegram ID entry is needed.
2. Send the credential privately to the intended technician. They open it using their own Telegram account and press **Start**. This is a bearer credential: the first valid private claimant connects automatically. A forwarded/stolen private link can connect the wrong person; deliver it only to the intended recipient. Revoke and disconnect immediately if misdelivered. The canonical technician name is never overwritten by Telegram metadata.
3. The worker atomically captures the trusted user ID, connects the binding, consumes/closes the invitation, writes an audit event and queues a short confirmation. The web dialog polls about every two seconds and changes to **Telegram connected** without reload. Username/name is primary; IDs are under **Technical details**.
4. **Connect Work Group** becomes available after private connection. It creates a separate WORK_GROUP credential. The linked technician opens **Add Bot to Group**, chooses an existing group or creates one in Telegram, and sends the Start command from the exact account linked in step 2. The bot needs ordinary membership and permission to send messages; admin rights and disabled privacy mode are not required.
5. If an administrator must add the bot, have them add it first. The linked technician then sends the dialog's scoped `/start@configured_bot payload` fallback in that group. The same fallback handles clients that do not resend Start when the bot is already present. Do not publish it: it contains the invitation credential. Channels, anonymous senders, bots and a different initiating user are rejected. Group titles are metadata, never identity keys.
6. A valid group claim connects automatically, updates the modal and queues a brief group confirmation naming the technician. A group already reserved by another technician cannot be taken. Fixed, manager-confirmed **Test private account / Test work group** behavior is preserved; it is not schedule delivery.

The application does not contact Telegram when creating an invitation. Opening links and starting the separately configured real worker are explicit human actions. Automated verification uses fakes only.

## Credentials, lifetime and concurrency

New purposes are PRIVATE_TELEGRAM and WORK_GROUP. `TELEGRAM_INVITE_SECONDS` defaults to 900 (15 minutes), bounded to 60–3600 seconds. The countdown is informational: backend expiry is rechecked under locks before consumption. Tokens use 32 cryptographically random bytes (256 bits), encoded as 43 base64url characters, with no embedded identity. PostgreSQL stores only their SHA-256 digest, never the token/deep link. API creation returns the link once; state/list endpoints omit both token and hash. UI component memory holds the displayed credential only while useful; success, terminal status, expiry, fetch failure and dialog close clear it. No browser persistence or external QR service is used.

The existing TelegramInvitation model is extended with a server-owned `automatic` flag. Existing rows migrate to false and retain their manager-review policy; newly issued rows default to true. No client input can disable/override that policy. Existing metadata/timestamps encode pending, consumed, approved/claimed, expired, rejected and revoked states; closed rows remain unusable. State output exposes PENDING/CLAIMED for the automatic policy and preserves the old review states for migrated credentials.

One open invitation per technician/purpose is enforced with the existing partial unique index. Issuance serializes on the technician row and atomically revokes a preceding open invitation; replacement is audited. A connected identity requires explicit replacement confirmation, remains connected while waiting, and changes only after a successful claim. Failed replacement does not destroy it.

Claims recheck bot, purpose/chat type, active technician, expiry, revocation, consumption and binding generations in PostgreSQL. Technician advisory locks coordinate claims with in-flight sends and deletion; row locks serialize claim/revoke/replace. Identity advisory locks plus unique columns serialize the same account/group across different technicians. Only one simultaneous claim wins. Binding, invitation closure, audit and confirmation outbox commit together; failure rolls all of them back. Telegram network verification happens outside SQL transactions, followed by generation/actor revalidation. Duplicate Bot API update IDs are persisted and ignored.

Group permission/provider failure consumes the attempted credential into ERROR without binding it. Restore access and generate a new invitation. Failed tokens cannot be replayed; old migrated review credentials keep their existing retry/review path. Arbitrary invalid, expired, wrong-context or used links produce a generic response without exposing technician existence.

## Disconnect and recovery

Disconnect requires manager confirmation and the current binding generation. Group disconnect leaves the private account untouched. Private disconnect removes the private identity and invalidates pending credentials/queued work, but preserves the group reservation and unrelated integrations. The UI shows that partial state as linked but unavailable. After reconnecting private Telegram with a new invitation, explicitly replace/revalidate the group before delivery resumes. A new private account never silently inherits an old group's delivery authorization.

Inactive/deleted technicians cannot claim; deletion cascades invitations and local notifications. Deletion still requires reviewed profile version, exact-name confirmation and the ten-second UI delay. Telegram accounts/groups, independent local calendars and already sent messages remain outside local deletion.

Polling pauses on hidden pages, cancels on unmount and stops the invitation poll on connection, expiry, revocation or error. Explicit retry resumes failed status checks. Outside an invitation dialog, visible-page background refresh is every 15 seconds. Confirmation delivery uses the existing durable outbox: SENT means accepted by Telegram, not read. Uncertain sends become UNKNOWN and are not automatically repeated; explicit rate-limit rejection permits bounded retry. A failed notification does not undo a valid binding. Raw `/start`, ordinary private messages and `/status` show a connected home response or safe guidance to request a manager link. No reports, schedules, expenses or other technician workflows were added.

## Official Telegram semantics and minimum permissions

Verified against official Telegram documentation for this completion:

- [Bot features / deep linking](https://core.telegram.org/bots/features#deep-linking) and [bot links](https://core.telegram.org/api/links#bot-links): private `https://t.me/<configured_username>?start=<token>` leads to `/start <token>`; group `startgroup` opens group selection and supplies `/start@bot <token>`. Payloads allow A–Z, a–z, digits, underscore and hyphen, up to 64 characters. These links do not themselves establish identity; only a trusted bot update does.
- [Bots FAQ](https://core.telegram.org/bots/faq#what-messages-will-my-bot-get): privacy-enabled bots receive explicitly addressed commands. Keep privacy mode enabled; no `admin` parameter is added to new group links.
- [getChatMember](https://core.telegram.org/bots/api#getchatmember): lookup of other users is only guaranteed for administrators. New onboarding therefore proves the technician's presence using the trusted, non-anonymous command sender, which must equal the already-bound private user; it checks the bot's own membership/send restriction. It does not treat failed third-party lookup as proof of identity.
- [Update](https://core.telegram.org/bots/api#update): `my_chat_member` reports bot membership; receiving arbitrary `chat_member` updates requires administration. A regular bot cannot guarantee ongoing observation of another member leaving. Bot access changes and trusted group migration still invalidate availability; private changes force group revalidation. This limitation is tracked as TD-022 and must be accepted/verified before pilot. No automatic privilege escalation is performed.
- [getUpdates](https://core.telegram.org/bots/api#getupdates) and [getWebhookInfo](https://core.telegram.org/bots/api#getwebhookinfo): the separate existing polling worker persists offsets after processing and refuses a configured webhook or competing poller. It never clears webhooks or drops pending updates.

A regular group member may lack permission to add bots: the administrator-add/linked-technician-command alternative preserves the actor match. Per-client selection/permission UI and actual delivery need manual sandbox acceptance. No permissions for future schedule/form features are requested or assumed here.

## Configuration and process

Existing variable names are retained rather than introducing aliases:

| Variable                       | Meaning                                                                                                 |
| ------------------------------ | ------------------------------------------------------------------------------------------------------- |
| TELEGRAM_MODE                  | disabled by default; real only for explicitly authorized operation; fake restricted to test DB          |
| TELEGRAM_EXPECTED_BOT_USERNAME | Configured username used for links and startup identity verification                                    |
| TELEGRAM_EXPECTED_BOT_ID       | Positive numeric bot identity checked with getMe                                                        |
| TELEGRAM_INVITE_SECONDS        | 900 by default; server-enforced expiry                                                                  |
| TELEGRAM_TOKEN_FILE            | Ignored local secret file for a native worker; Compose mounts `.local/telegram-bot-token.txt` read-only |
| TELEGRAM_BOT_TOKEN             | Optional native-worker secret environment input; never a public/frontend variable                       |

The worker remains a separate process and an opt-in Compose profile. Real mode without credentials exits with BOT_NOT_CONFIGURED; disabled mode initializes no provider. Startup/exception messages are sanitized, library HTTP/update logs are suppressed, and worker state logs contain only event/status/error codes. API and worker engines hide SQL parameters. The API/web containers do not receive the bot token. Never put real secrets into examples, Git, command arguments or screenshots.

Before upgrading an existing installation, stop its worker, back up the database, apply `alembic upgrade head`, and deploy matching API/web/worker code together. Revision e7b310920001 follows d6c2f8a14001; it renames the private purpose in invitation/outbox rows and preserves existing invitations as manual-review credentials. Old migrations are unchanged. Downgrade translates purposes back; a subsequent upgrade conservatively treats surviving invitations as legacy review. Do not run old and new workers against the same bot/database during migration.

Default local startup (no Telegram calls):

```powershell
cd C:\HVAC_TECHNICIAN_HUB
docker compose up -d --build --wait
docker compose exec api python -m hub.auth.cli create-manager --username manager
```

## Manual sandbox verification — not run automatically

Use a new dedicated TEST bot, a fictional technician, your own test account and an isolated test group. Never use an operational bot or contact a real technician.

1. Create the TEST bot in BotFather, retain privacy mode and record its username and numeric bot identity. Put its secret token in ignored `.local/telegram-bot-token.txt` using a local editor, without echoing it or adding it to shell history. Native workers may use an absolute TELEGRAM_TOKEN_FILE instead.
2. In ignored `.env`, set TELEGRAM_MODE=real and the two EXPECTED_BOT identity values. Keep loopback origins/ports. Do not put a secret in NEXT_PUBLIC variables. Stop other pollers; do not remove an existing webhook to force ownership.
3. Only when intentionally ready for live TEST traffic, start the API/web and then the worker:

```powershell
docker compose up -d --build --wait api web
docker compose --profile telegram up -d --build telegram-worker
docker compose --profile telegram logs --tail 30 telegram-worker
```

4. Confirm the worker heartbeat, create the fictional technician, issue a private link and press Start using the intended test account. Verify automatic connection and the short private confirmation. Reopen the used link and verify rejection. Verify plain Start/home does not create profiles.
5. Issue a new group link. Have the linked account send the group Start command with the bot as a normal member. If an administrator adds the bot, have the linked technician send the fallback afterward. Verify automatic connection and the short group confirmation. A different user, channel, anonymous sender or group already bound elsewhere must fail. Do not grant admin rights merely to make the test pass.
6. Exercise expiry, revoke/regenerate, permission loss and notification failure recovery. Confirm group/private disconnect independently, partial-state warning, reconnect requiring new credentials, and no unrelated destinations receiving messages. Test the old review path only with existing migrated invitations.
7. Stop the worker and restore disabled mode:

```powershell
docker compose --profile telegram stop telegram-worker
# Edit .env: TELEGRAM_MODE=disabled
docker compose up -d --wait api web
```

For a native worker: `.\.venv\Scripts\python.exe -m hub.telegram.worker`; Ctrl+C requests graceful shutdown. Never run two polling workers for the same bot. The automated suite uses a guarded stdin-only fake harness and makes no real Telegram API calls.

## Quality-audit operational clarifications

The independent findings and verification are in [AUDIT_STAGE1_TELEGRAM.md](AUDIT_STAGE1_TELEGRAM.md). Ordinary bot membership is checked together with default group send permissions; unavailable permission data fails closed. Automatic invitation recovery never requires administrator escalation. A known `chat not found` failure marks the destination unavailable while preserving identity; other unrecognized provider descriptions remain a generic rejected request.

A polling offset whose last processed update is at least six days old (or missing locally) is not sent to Telegram, because the next update ID may restart randomly after a quiet week. The next committed event establishes the new offset. This conservative window is longer than Telegram's pending-update retention. Processed IDs still deduplicate retries. Polling respects Retry-After up to one hour and fails visibly for longer requests rather than retrying early; shutdown interrupts waits. Worker restart does not guarantee that an uncertain confirmation was sent: UNKNOWN requires operator assessment, not automatic replay.

Copying an invitation intentionally crosses into the operating-system clipboard, which may have history or device sync outside this application. Clear it after sharing the credential privately. Opening Telegram places the link in Telegram/browser history; the application itself does not persist it in storage or its route URL. No frontend analytics or remote QR service receives it.

For manual TEST-bot acceptance, additionally test a default read-only group with the bot as a regular member, explicit bot restriction, loss/restoration of group access, username/group rename, and basic-group to supergroup migration. Verify that identities remain reserved while delivery is unavailable and migration requires revalidation. Live tests remain manual only. Resolve TD-022 membership policy and TD-023 public-bot abuse controls before internal pilot.

## Stage 4 schedule delivery

See [Schedule delivery](SCHEDULE_DELIVERY.md) for the unified immutable dispatch path, dedicated
payload key, separate worker, calendar-local automatic delivery (OFF by default),
acknowledgement authorization, uncertainty recovery, retention, and dedicated TEST
acceptance runbook. The Telegram polling worker receives callbacks; the schedule
worker sends durable dispatches and evaluates automatic decisions. Neither starts
inside the web API. Stage 3 job filtering and wall-clock projection remain authoritative.
