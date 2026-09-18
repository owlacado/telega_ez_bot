# Schedule delivery (Stage 4)

## Scope and boundaries

Manual Send, explicit Resend, and the automatic scheduler all call
`hub.schedule_delivery.service.create_dispatch`. The service re-reads the audited
Stage 3 next-work-day projection. The API never accepts a job list. The worker
never fetches Google to replace a queued snapshot. No Reports, Expenses,
Contracts, Accounting, GPS, or Stage 5 implementation is included.

The starting point is `codex/stage3-calendar-events-quality-audit` at
`b1451778d9720fd24709e6eb79452cd0e4c5ed84`. Stage 4 uses
`codex/stage4-schedule-delivery`; nothing is pushed by this work.

## Data and fingerprint

ScheduleDispatch stores technician/calendar references, calendar target date,
MANUAL/AUTOMATIC/MANUAL_RESEND trigger, WORK_GROUP/PRIVATE destination,
PENDING/PROCESSING/SENT/FAILED/AMBIGUOUS/CANCELLED state, SHA-256 fingerprint,
job count, encrypted immutable payload, destination identity/generations,
claim owner/expiry, provider-start marker, attempt count, retry availability,
deadline, message ID, safe error, creator, acknowledgement state/hash/expiry,
and timestamps. Browser DTOs expose only bounded operational metadata.

The versioned canonical JSON contains target date, canonical technician name,
and the ordered projected job clock, cleaned title, and optional location.
New projections normalize text to NFC, collapse whitespace, and treat empty
locations as absent before both rendering and fingerprinting. Already committed
version-1 payloads retain their exact canonical bytes and remain readable.
Sorted object keys and stable separators yield SHA-256. Provider event IDs,
fetch times, original descriptions, and calendar IDs are excluded. The source
version separately binds active status/name, assignment, calendar/timezone,
availability/exclusion, and Google connection identity/generation/scopes.

A manager sends `{target_date, fingerprint}`. Unknown fields are rejected.
Changed authoritative content yields SCHEDULE_CHANGED and requires refreshing.
Assignment, connection, technician, or calendar changes during the Google read
are rejected by Stage 3 and checked again under the existing calendar mutation
lock before insertion. Manager session validity is rechecked after provider I/O.

## Encryption and retention

SCHEDULE_DELIVERY_ENABLED defaults false. Enabling it requires a dedicated
SCHEDULE_PAYLOAD_ENCRYPTION_KEY, a configured Telegram mode and bot identity.
Use a generated Fernet key, kept server-side; never NEXT_PUBLIC or committed.
The existing versioned SecretCipher authenticates encryption. Missing keys fail
configuration, and incorrect keys/corrupt snapshots fail closed before sending.

Only the encrypted canonical payload is persisted. It is purged in the same
transaction that confirms SENT, and immediately when CANCELLED or definitively
FAILED. FAILED has no ordinary retry path; explicit Resend rebuilds current
content. Legacy FAILED ciphertext is preserved on migration and expires through
the existing cleanup. AMBIGUOUS ciphertext remains for at most seven days from
creation for controlled recovery review, then the
running worker's bounded cleanup removes it. A stopped worker delays cleanup;
operations must monitor this. Metadata remains for history; a broader metadata
retention policy is an existing operational debt, not implicit indefinite legal
approval. Backups require the same retention/key controls.

Database checks enforce state/timestamp/claim/ack compatibility, positive counts,
encrypted version prefix, active payload presence, and sent payload removal.
Partial unique indexes permit at most one active dispatch per technician/date
and one automatic dispatch per technician/date. A unique resend parent prevents
double-clicks from creating multiple children. A trigger rejects changes to
snapshot identity/content and terminal delivery states. Purging ciphertext and
acknowledging a sent message remain allowed.

## Telegram message and acknowledgement

The message contains technician name, weekday/date, then ordered time/title and
location. Empty schedules explicitly say No scheduled jobs. Descriptions are
excluded. All variable text passes through HTML escaping; only our bold tags
are markup. Link previews are disabled and protect_content is enabled.

Telegram's ordinary sendMessage accepts 1-4096 characters after entity parsing;
callback_data is 1-64 bytes. The implementation conservatively limits the entire
escaped HTML message to 4096 UTF-16 units, so some content below Telegram's true
limit is rejected. SCHEDULE_TOO_LARGE queues nothing; it neither truncates nor
splits a schedule. A 32-byte random capability produces 47-byte `sch:` callback
data. Only its SHA-256 hash is stored. It expires seven days after the send
attempt. Tokens are never returned by an application API or logged.

The Schedule received button is not authentication by itself. The callback must
match the current bound Telegram user, bot, dispatch-era private generation,
chat and message ID, active technician, and (for group delivery) current group
binding/generation. Unrelated group participants, expired tokens, disconnected
or rebound accounts, and callbacks for other messages cannot acknowledge it.
A row lock makes repeat/concurrent acknowledgements idempotent and records one
audit event. SENT and ACKNOWLEDGED are separate facts. Callback handling promptly
answers the Telegram query before database work; a cosmetic answer failure or
message-edit failure cannot undo a committed acknowledgement. No editing is
required. A callback arriving during finalization waits for the same technician
lock and can be accepted once SENT commits.

Official semantics verified on 2026-09-17:
[sendMessage](https://core.telegram.org/bots/api#sendmessage),
[HTML formatting](https://core.telegram.org/bots/api#html-style),
[InlineKeyboardButton](https://core.telegram.org/bots/api#inlinekeyboardbutton),
[CallbackQuery](https://core.telegram.org/bots/api#callbackquery), and
[ResponseParameters](https://core.telegram.org/bots/api#responseparameters).
Telegram returns a Message on success; retry_after tells how long to wait after
rate limiting. Telegram offers no idempotency key for this sendMessage workflow.

## Destination, attempts, and recovery

The audited can_deliver state determines eligibility: non-null IDs alone do not.
A usable work group is preferred; otherwise the same bound technician's usable
private Telegram is selected. Destination identity and generations are frozen
at creation and revalidated immediately before each send. Group bot send rights
and technician membership are inspected through the provider outside SQL
transactions. A definitive unavailable group can fall back to that same private
identity. A transient membership-inspection failure is FAILED with zero attempts.
History preserves requested destination, actual destination, and a closed fallback
reason without chat IDs. Legacy requested destinations remain unknown rather than
inventing a pre-audit request after fallback provenance was lost.
A source/identity change cancels a queued dispatch; disabling auto cancels queued
automatic dispatches, while explicit manual sends remain eligible.

Only ACCESS_DENIED or CHAT_UNAVAILABLE from a group send permits fallback after
a send attempt. Timeouts, resets, unknown exceptions, and provider-unavailable
results are AMBIGUOUS and never trigger fallback or automatic resend.
REQUEST_REJECTED and invalid credentials are known failures. A confirmed rate
rejection can retry up to three total send attempts, respecting retry_after,
a one-hour maximum wait, and the dispatch deadline. Membership inspection,
queue scanning, and claim recovery do not increment attempts.

Workers claim with SELECT FOR UPDATE SKIP LOCKED, a fresh UUID owner, and a
90-second database-clock lease. A committed pre-provider marker increments the
attempt counter immediately before calling send_schedule. There is necessarily
a tiny crash interval between committing that marker and entering the provider;
it is conservatively counted as a potentially attempted send. No claim protocol
can observe the network across that crash atomically.

Expired claims without a provider marker can be reclaimed. Expired marked
claims become AMBIGUOUS. A stale owner cannot finalize. The technician advisory
lock serializes delivery with profile/binding changes; its dedicated NullPool
connection does not occupy the transaction pool. SQL transactions and row locks
are closed before Google/Telegram calls. Exactly-once external delivery is NOT
claimed: Telegram may accept a message before the local commit or before a
connection fails. Those cases remain uncertain until manager review.

Normal Send refuses an already-sent identical fingerprint. A changed fingerprint
may be sent explicitly. In-flight work coalesces or conflicts. Any ambiguous
history for the date requires an explicit resend choice. Resend always creates
a new dispatch after fetching current content and receiving duplicate-risk
confirmation; it preserves the parent's immutable outcome. Each parent has at
most one child. To send another copy, choose the latest child.

## Automatic schedule

Per-technician enablement defaults OFF and requires a manager mutation. The
separate schedule worker evaluates enabled technicians with active assignments
and uses the assigned calendar's timezone. It reuses the same Stage 3 scope,
connection, projection and creation eligibility checks. No FastAPI startup loop
and no browser timer sends schedules.

SCHEDULE_AUTO_DELIVERY_LOCAL_TIME defaults 20:00; configuration permits a time
before 23:00. Catch-up is from that time through, but excluding, 23:00 calendar
local time. The target rule is Monday to Tuesday through Friday to Saturday;
Saturday and Sunday target Monday. One logical decision per technician/target
date means Saturday and Sunday cannot deliver two automatic Monday schedules.
A MISSED decision remains missed for that target date. No next-morning catch-up
is performed. Known pre-creation failures are observable as RETRY and reconsidered
after five minutes within the window. Missing assignments/timezones are ineligible;
the preview explains assignment/timezone requirements rather than inventing a date.

Any successful manual delivery for the date suppresses automatic delivery even
if content changes later. In-flight or ambiguous delivery suppresses it too.
A database automatic uniqueness constraint survives concurrent workers/restarts.
Auto dispatches expire at 23:00 of the source local day; manual dispatches expire
one hour after queueing. Expired pending work cancels without sending stale jobs.
Scheduler and delivery run in separate tasks within each cycle; delivery drains
at most 20 dispatches sequentially per worker. Slow Google evaluation does not
block that cycle's ready sends. Worker cycles wait up to one minute between
evaluations; provider latency can extend this interval. Multiple instances are
intentionally supported; capacity planning must bound the configured fleet. Worker lag and global request admission remain TD-017/026.

## UI, authorization, and privacy

The existing preview exposes destination, explicit Send/Resend, automatic toggle,
and the latest 20 dispatches. It shows Queued/Sending until confirmed SENT, and
Awaiting acknowledgement until a valid callback. Active history polls every
three seconds; pending acknowledgement every thirty seconds. Polling stops on
terminal acknowledgement/failure, modal unmount, or after ten minutes; manual
refresh remains available. Keyed technician panels and abort guards prevent late
A responses or mutations from overwriting B's view.

All application endpoints require the existing manager session, trusted Origin,
and CSRF boundary for mutations. Responses are no-store and safe DTOs omit
chat/user IDs, message payload/ciphertext, provider message IDs, and ack hashes.
Audits record manual enqueue, resend, ambiguous duplicate-risk confirmation,
enable/disable, and acknowledgement once. Dispatch state carries routine worker
operations without flooding audit_events. Logs contain internal dispatch IDs and
safe result codes only, never provider exception bodies or message contents.

## Operations and manual TEST runbook (not automatically executed)

1. Use a dedicated Google TEST account, dedicated Telegram TEST bot, your own
   test Telegram account, a private fake-work group, and synthetic job/customer
   data. Do not use technician/business accounts or existing business groups.
2. Complete the existing Google discovery/event-scope and Telegram onboarding
   runbooks. Assign a TEST calendar with its intended IANA timezone. Confirm the
   connected private identity and group membership/send permissions in the UI.
3. Generate an independent Fernet key using the existing key-generation guidance.
   Back it up through your approved secret store. Configure it identically in the
   API and schedule worker. Keep Google and Telegram credentials in their existing
   server-only boundaries. Do not print them into logs or screenshots.
4. Set SCHEDULE_DELIVERY_ENABLED=true. Keep every technician's automatic toggle
   OFF. Start the API, web, existing Telegram callback/polling worker, and separate
   schedule worker (`python -m hub.schedule_delivery.worker`, or Compose profile
   `schedules`). Only the original Telegram worker calls getUpdates; both workers
   verify the configured bot identity and refuse an existing webhook.
5. Add a few synthetic numbered jobs including HTML-like text, parentheses,
   excluded titles, a location, and notes. Preview the next work day. Confirm the
   exact wall clocks, cleaned titles, location, weekday/date and omitted notes.
6. Send once. Observe Queued then Sent and compare the TEST Telegram message.
   Confirm the normal Send button is disabled for the same fingerprint. Click
   Schedule received with your bound account; observe one acknowledgement. A
   second TEST participant must not acknowledge your schedule.
7. Edit a synthetic job between preview and Send. Expect SCHEDULE_CHANGED; refresh
   and explicitly send the updated preview. Confirm a new fingerprint and history.
8. Use explicit Resend and read/confirm the duplicate-risk notice. Verify a new
   dispatch and preserved parent history. Repeated clicks must not create extras.
9. In the TEST group only, remove bot send rights or the bound participant. Verify
   safe private selection/fallback. Restore through the existing audited onboarding
   revalidation. Confirm disconnect/rebind rejects old acknowledgement buttons.
10. Test one empty day and one oversized day. Empty sends an explicit no-jobs
    message. Oversized queues nothing. Verify HTML-like content renders literally.
11. Enable auto only for the dedicated TEST technician. At 20:00 calendar local
    time verify next-day/weekend targeting. Test a prior manual send, worker restart
    during the catch-up window, and a restart after 23:00. Verify suppression and
    missed-window state. Turn auto OFF at the end.
12. For crash/timeout/ambiguous acceptance use the injected test harness or a
    controlled TEST network interruption, never a real technician group. Verify
    there is no automatic retry/fallback; manager confirmation creates a separate
    resend. Record expected duplicate risk if the first copy actually arrived.
13. Check schedule_worker_states heartbeat/status and dispatch backlog/error codes.
    Alert on stale heartbeats, old PENDING/PROCESSING rows, AMBIGUOUS outcomes and
    overdue ciphertext cleanup. SIGTERM allows current calls to finish within the
    shutdown grace period; an interrupted marked attempt recovers as ambiguous.
14. Inspect approved TEST evidence only. Redact credentials, acknowledgement tokens,
    invitation links, customer notes and identifiers from shared artifacts. Disable
    delivery/workers, clean up TEST resources, and document the acceptance result.

Key loss fails closed; rotate only after draining/cancelling queued snapshots and
purging retained payloads or through a separately reviewed migration. No automatic
key-reencryption or operator plaintext inspection endpoint is provided. Rollback
requires stopping both workers and the supported empty-history migration path below.
Populated dispatch/decision history blocks downgrade; there is no loss-acceptance flag.

## Independent Stage 4 audit operations

The appended migration `d4e509170002` leaves `d4e509170001` unchanged. It preserves
all existing dispatch rows and ciphertext, adds nullable provenance for legacy
history, and protects terminal receipt fields and completed acknowledgements.
Rollback refuses before removing any guard when dispatch or auto-decision history
exists. There is no destructive bypass flag. Empty-history downgrade/re-upgrade is
supported. Retain a verified backup and use an explicitly reviewed archive/retention
procedure before considering any populated rollback; running an old code checkout's
unguarded downgrade is not a supported escape hatch.

Run `python -m hub.schedule_delivery.health` in the configured worker environment.
It checks database connectivity and independently reports schedule and onboarding
worker state. A schedule heartbeat older than 120 seconds is stale; any recent
RUNNING schedule instance satisfies liveness. Heartbeats update every 15 seconds
using the database clock, including while provider work is pending. This is process
liveness, not evidence of completed deliveries: separately alert on queue age,
ambiguous outcomes, and overdue purges. API `/api/health` deliberately reports only
API/database health. The health command emits no bot IDs, payloads, or secrets.

On shutdown the active cycle has 40 seconds to finish before cancellation. A
cancelled marked send remains PROCESSING until its lease expires, then becomes
AMBIGUOUS. A cancelled unmarked claim can be reclaimed. The 50-second Compose grace
leaves time to close clients. Hard process death is still covered by lease recovery.
Terminal SENT and ciphertext purge are one commit, so no durable SENT-with-payload
crash window exists. An `attempt_count` increment records a durable possible provider
attempt: death between marker commit and the HTTP call may count an unissued call.

A whole-window outage with restart next morning does not send the missed schedule.
It also cannot reconstruct a past MISSED decision when no evaluation occurred that
evening; use worker uptime/queue monitoring to detect that operational gap. A
Saturday MISSED decision intentionally prevents a Sunday retry for the same Monday.
A definitively FAILED manual dispatch does not suppress a later first automatic
attempt; SENT, AMBIGUOUS and active manual dispatches do suppress it regardless of
fingerprint. Resend means send the current authoritative schedule again.

Send preparation follows the existing global calendar mutation lock before the
technician row lock and rechecks database-clock lease expiry after those waits.
Expired leases/deadlines are recovered across bot rotations; live claims remain
restricted to the configured bot. An expired marked attempt belonging to a retired
bot becomes AMBIGUOUS, never a send through the replacement bot. An expired pending
row is cancelled and its payload purged.
