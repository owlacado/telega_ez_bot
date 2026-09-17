# Telegram onboarding and later dedicated-test-bot runbook

## Manager flow

1. Sign in and open an active technician. The private and work-group rows show approved identity and availability independently of a pending invitation. Runtime status distinguishes disabled, bot unconfigured and stale/unavailable worker; web health never implies worker health.
2. Open **Connect Telegram — Generate invitation**. Copy the link, open Telegram, or scan its locally generated QR. Links are returned once, kept only in component memory, and cleared when the dialog closes. Regenerate if lost. Send the link to the intended technician yourself.
3. The technician opens Telegram and presses **Start** in a private conversation. The worker obtains the actual user ID from the update. The candidate has no access until a manager reviews the display name, optional username and numeric ID against the intended Hub profile and selects **Approve account**. Forwarded links cannot bypass this review.
4. After private approval, select **Connect Work Group — Generate invitation**. A human owner/administrator selects or creates a group in Telegram. Add the approved technician account and grant the bot administrator status for reliable `getChatMember` queries. Do not grant blanket moderation privileges. Some clients force their own minimal admin-rights selection; verify the selected rights manually.
5. An existing group also works. If its Telegram client does not dispatch the startgroup payload when the bot is already present, paste the exact scoped `/start@configured_bot payload` command shown in that dialog into the intended group. It has identical expiry, single-use and review checks. This message contains an invitation secret; do not post it elsewhere. The app does not create public group links or automate user accounts.
6. Review group title/ID, initiating account, administrator checks and technician membership; select **Approve group**. A title or username is never an identity key. Anonymous senders and channels are rejected. Fix failed checks and use **Retry checks**; the worker verifies them outside DB transactions. Proof older than two minutes must be retried before approval.
7. **Test private account / Test work group** opens a destination-specific confirmation. **Send test message** enqueues a fixed message. Recent activity shows QUEUED, PROCESSING, SENT, FAILED, UNKNOWN or CANCELLED. SENT means accepted by Telegram, not read. An UNKNOWN result is not retried automatically; a later deliberate test could duplicate an uncertain previous send.

Approval messages are also durable. A failed notification never rolls back a valid identity binding. Tests are limited to one per technician/destination/minute; verification retries to three/minute; invite issuance to twelve/manager/technician per fifteen minutes.

## Lifecycle

Replacement requires confirmation and keeps the approved connection until candidate approval. Expiry, rejection and revocation leave that connection intact. Generations reject stale browser approvals/actions. Replacing or disconnecting a private account suspends group delivery and preserves the old group reservation. After establishing the intended private account, generate a replacement group invitation and re-approve membership before resuming delivery. Group disconnect is independent.

Inactive profiles retain their identity but cannot claim, approve or deliver. Blocking, lost permissions and membership loss change availability; they cannot attach a new identity. Group-to-supergroup migration is accepted only through a trusted Telegram update. Conflicting migration targets are not stolen. Migrated groups require revalidation.

Deleting a technician requires the existing exact-name confirmation and ten-second countdown, with backend confirmation and manager authorization. Pending invitations, candidate PII and local notification rows cascade away. A late claim cannot recreate the profile. Telegram groups/accounts, local calendars and already delivered external messages are not deleted.

## Default Windows startup: no Telegram calls

```powershell
cd C:HVAC_TECHNICIAN_HUB
docker compose up -d --build --wait
docker compose exec api python -m hub.auth.cli create-manager --username manager
```

Enter a new 14–128 character password interactively; never pass it as an argument. Sign in at `http://localhost:3000`. Run bootstrap once per desired manager. No account is automatically created.

Explicit migrations if using the native API:

```powershell
..venvScriptspython.exe -m alembic -c apps/api/alembic.ini upgrade head
..venvScriptspython.exe -m hub.auth.cli create-manager --username manager
..venvScriptspython.exe -m uvicorn hub.main:app --host 127.0.0.1 --port 8000
# In a second terminal:
npm.cmd run dev
```

`TELEGRAM_MODE=disabled` is the default. Ordinary `docker compose up` excludes the worker. Do not run a worker merely because a token happens to exist.

## Later manual test — not performed in this coding stage

Use a **new dedicated TEST bot**, one fictional technician, your test private account, and one test work group. Never use an operational bot or real technician/group.

1. In Telegram, use BotFather to create that TEST bot. Record its username and numeric bot identity (the numeric prefix of its bot token is checked against `getMe` by the worker). Keep its token private.
2. Place the token alone in ignored `.local/telegram-bot-token.txt`, using a local editor. Avoid terminal commands that echo it or add it to shell history. Example preparation (does not contact Telegram):

```powershell
cd C:HVAC_TECHNICIAN_HUB
New-Item -ItemType Directory -Force .local | Out-Null
notepad.exe .local/telegram-bot-token.txt
```

3. Set these non-secret values in ignored `.env` with your actual TEST bot values:

```dotenv
TELEGRAM_MODE=real
TELEGRAM_EXPECTED_BOT_USERNAME=your_dedicated_test_bot
TELEGRAM_EXPECTED_BOT_ID=your_numeric_test_bot_id
```

The sample ID above is a placeholder, not a valid configuration. Do not put the token in any `NEXT_PUBLIC` variable. API/web containers receive no token. If changing web ports, update `ALLOWED_ORIGINS` to the exact loopback origin.

4. Only when intentionally ready to contact that TEST bot, run:

```powershell
docker compose up -d --wait api web
docker compose --profile telegram up -d --build telegram-worker
docker compose --profile telegram logs --tail 30 telegram-worker
```

Startup calls `getMe` and checks exact configured bot ID/username, then `getWebhookInfo`. Any existing webhook is a hard refusal. No deleteWebhook/setWebhook/drop-pending helper is called. An existing poller yields a clear conflict and shutdown. Resolve ownership outside this app; never clear a webhook to force this test through. The adapter uses low-level `Bot.initialize`, not `Updater`/`Application.run_polling` takeover helpers.

5. In the app confirm a fresh running heartbeat, then perform the private and group flow above. Opening Start, choosing the group, adding the technician and granting minimum group administration are intentional human steps. Check pending candidates do not report connected; approve each separately. Try wrong-context, missing-member and missing-bot-admin cases, retry verification, test each destination, replace/reject, disconnect and delete the fictional profile. Confirm no messages go to unrelated chats.
6. Stop explicitly and restore disabled mode:

```powershell
docker compose --profile telegram stop telegram-worker
# Edit .env back to TELEGRAM_MODE=disabled, then:
docker compose up -d --wait api web
```

For a native worker, set `TELEGRAM_TOKEN_FILE` to the absolute ignored file path and run `..venvScriptspython.exe -m hub.telegram.worker`; Ctrl+C requests graceful shutdown. Do not run native and Compose pollers for the same bot. Docker grants 50 seconds for shutdown. Network calls have bounded timeouts; poll transport retries stop after five backoffs.

## Telegram assumptions and references

- [Deep linking](https://core.telegram.org/bots/features#deep-linking): URL-safe payload limited to 64 characters. Ours is 43 characters from 32 random bytes. Client UX differs; fallback is scoped to the same invitation.
- [getChatMember](https://core.telegram.org/bots/api#getchatmember): reliable information about other users requires bot administration. Privacy mode need not be disabled for addressed `/start@bot` commands. We do not request blanket moderation rights.
- [getUpdates](https://core.telegram.org/bots/api#getupdates): acknowledgement follows the next request with a larger offset, after processing is durable. No negative offset or pending-update drop is used.
- [getWebhookInfo](https://core.telegram.org/bots/api#getwebhookinfo): a configured webhook prevents this polling worker from starting.
- [Update](https://core.telegram.org/bots/api#update): explicit message, my_chat_member and chat_member update selection; trusted message migration fields preserve signed 64-bit group IDs.
- [python-telegram-bot Bot](https://docs.python-telegram-bot.org/en/stable/telegram.bot.html): pinned async adapter version 22.8. Installed startup source was inspected: low-level Bot initialization initializes HTTP and gets bot identity; Updater startup can delete webhooks and is intentionally unused.

The exact client permission UI, real account claims, real migration events and provider error behavior still need that manual TEST-bot verification. Membership proofs are time-bound observations, not a guarantee against a person leaving a group immediately afterward. Group sends check bot/technician membership again.
