# Google Calendar integration - Stages 2 and 3

CalendarList discovery manages provider metadata and local assignments. Stage 3 adds bounded read-only events and schedule previews after explicit event consent. Hub never deletes Google calendars, edits events, or uses Google Sheets. Stage 4 optionally reads next-work-day schedules during its bounded automatic delivery window and delivers immutable snapshots through Telegram; CalendarList discovery remains manager initiated. Google is authoritative for provider metadata; PostgreSQL is authoritative for technician identity, assignments, history, and exclusions.

## Verified references

Consulted on September 17, 2026, before implementation:

- [Google OAuth web-server flow](https://developers.google.com/identity/protocols/oauth2/web-server): authorization-code exchange, state, offline access, refresh-token omission, incremental authorization, and revocation.
- [CalendarList.list](https://developers.google.com/workspace/calendar/api/v3/reference/calendarList/list): `nextPageToken`/`pageToken`, `showHidden`, and permitted scope.
- [Google OAuth scopes](https://developers.google.com/identity/protocols/oauth2/scopes#calendar): CalendarList discovery scope.
- [Google PKCE guidance](https://developers.google.com/identity/protocols/oauth2/native-app#step1-code-verifier): S256 challenge semantics. This page describes native clients; web implementation support was separately verified in the installed official `google-auth-oauthlib==1.4.1` Flow implementation (`authorization_url`, `fetch_token`). Flow generates a 128-character verifier, SHA-256 challenge, and supplies the verifier during exchange. Technician Hub does not implement that cryptography itself.

Initial discovery requests only `https://www.googleapis.com/auth/calendar.calendarlist.readonly`. Grant Event Access explicitly adds `https://www.googleapis.com/auth/calendar.events.readonly` for the same account using `include_granted_scopes=true`. No broad calendar, write, email or OpenID scope is requested. Partial consent leaves discovery working; the stored granted_scopes array governs event capability. OAuthlib scope-change warnings are accepted only with a validated token and the required discovery scope. See the Stage 3 runbook below.

## Connection and security design

The official Google OAuth Flow creates an authorization URL with `access_type=offline`, `prompt=consent select_account`, and S256 PKCE. Client credentials and redirect URI come from server settings. The manager must already have an authenticated session and supply the existing Origin/CSRF protections to start, scan, disconnect, or change catalog state.

A 32-byte random state is returned only as part of the authorization URL. PostgreSQL stores its SHA-256 digest, initiating manager/session IDs, ten-minute expiration, expected connection generation, and encrypted PKCE verifier. Starting another attempt in the same session invalidates its predecessor. The callback checks exact session ownership, expiry, duplicate query parameters, provider denial, and missing code. It locks and consumes state before external exchange; failure requires starting a new attempt. Completion rechecks that the manager session is still active and that the current account/generation has not changed. There is no unauthenticated simulation route.

Callback parameters are copied into request-local state and removed from the ASGI query string before downstream access logging. Next development request logging ignores the callback path. Responses use no-store/no-referrer and redirect to `/calendars?google=connected` or `error`; the page removes that marker with history replacement. Configure any external ingress/access logger to omit the query string for the callback path. Do not enable HTTP wire tracing or request-body capture. The initiating OAuth URL necessarily contains state and the callback necessarily arrives with code/state; neither is retained by the application after processing.

`SecretCipher` uses cryptography Fernet authenticated encryption with a `v1:` envelope. Refresh tokens and pending PKCE verifiers are encrypted with `GOOGLE_CALENDAR_CREDENTIAL_ENCRYPTION_KEY`. Invalid or missing keys fail startup whenever Google is enabled. Wrong keys/corrupt ciphertext fail closed. Pydantic configuration errors suppress input values. Access tokens exist only in process memory; authorization codes are never persisted. Client secrets are never stored in PostgreSQL or returned to the UI. Provider errors and audit events have closed, safe metadata; no raw provider exception/payload is exposed.

One current connection is enforced by a partial unique index. Each connection retains a unique opaque account key, generation, status, encrypted credential, granted scopes, dates, error code, and retry deadline. To verify account identity without an extra scope, callback discovery requires exactly one primary CalendarList entry and uses its provider ID as the opaque account key. The UI deliberately displays `Google Calendar account`, not an inferred email. An incomplete or ambiguous identity fails closed.

Same-account reconnect preserves internal connection/calendar UUIDs and exclusions. If Google omits a refresh token, an existing credential is reused only after verifying the same account. A new account or a disconnected account without an existing credential must return a refresh token. Ordinary Reconnect refuses a different account. Change Google account shows catalog/assignment impact and requires explicit confirmation; the old account becomes unavailable, while its catalog, assignments, and exclusions remain. Identical calendar IDs in different account contexts never merge. Switching back reuses the prior connection/catalog identities.

Disconnect first commits local credential deletion and unavailability, preserving assignments and history, then attempts bounded remote revocation. A failed revocation is audited without restoring the credential. Replaced-account credentials are also revoked best-effort; same-account refresh does not revoke the old token because Google's project-wide revocation could invalidate the new token too. OAuth exchange/activation and disconnect/revocation share a session advisory lock, held without a SQL transaction during network calls.

**Google revocation affects all scopes granted to the project for that account and can invalidate tokens from other clients in that project.** Use a dedicated test project. Remote revocation is best-effort and can be delayed; revoke manually in the Google account security settings if necessary. A crash after local deletion and before remote revoke is a documented operational gap (TD-025).

## Scan, exclusions, and assignment semantics

`GoogleCalendarProvider` is the sole Google network adapter, implementing the CalendarProvider protocol with normalized dataclasses. List requests use CalendarList only, `showHidden=true`, `showDeleted=false`, and `maxResults=250`. All continuation pages are collected before reconciliation. Repeated page tokens, conflicting duplicate IDs, invalid metadata, ambiguous bodies, or more than 1,000 pages fail the entire scan rather than commit a partial catalog. Names are bounded to the existing 150-character display contract. No raw provider payload is stored.

A single nonblocking advisory scan guard rejects a simultaneous scan with 409. Network requests occur after the snapshot transaction closes; a short transaction then rechecks connection generation and atomically updates/inserts by `(connection_id, provider_calendar_id)`. Missing calendars become UNAVAILABLE only after successful complete listing. A disconnect/reconnect/switch during fetch changes generation and discards the stale result. Failed pages do not change catalog metadata or mark unseen calendars unavailable. Permanent authorization/scope errors do mark all provider calendars unavailable and require reconnect; transient errors preserve last-known availability and display connection failure. These are discovery-time states, not a claim of continuous provider reachability.

401/invalid_grant maps to REAUTH_REQUIRED, 403 to SCOPE_REQUIRED, 429 to RATE_LIMITED, and transport/5xx to PROVIDER_TEMPORARY_ERROR. Temporary failures set a server-enforced retry deadline; Retry-After seconds or HTTP dates are respected, including values over one day. The adapter uses bounded 5-second connect/15-second read timeouts. No application retry loop or periodic polling exists; Google auth may perform its own bounded refresh retries. No SQL transaction sleeps through a retry.

Calendar rows carry explicit LOCAL_DEMO or GOOGLE source, availability, timezone, primary/access role, last_seen_at, and excluded_at/excluded_by. Local demo CRUD is development/test only; production catalog responses omit demo rows and production assignments reject them. Google rows cannot use local rename/delete endpoints.

Remove from Technician Hub requires EXCLUDE confirmation and the currently displayed assigned-technician ID. If that assignment changed, the server rejects stale confirmation. Removal deactivates the assignment and records history/audit in the same transaction, then sets the local exclusion. Scans may refresh excluded metadata but never clear exclusion. Restore intentionally clears it; an unavailable restored calendar remains unavailable. No Google delete endpoint exists.

Both existing partial unique indexes remain: at most one active calendar per technician, at most one active technician per calendar. Transaction-scoped calendar mutation locking serializes assign/reassign/unassign/exclude/restore/reconcile; indexes are the final database protection. A calendar-table transfer rolls back its prior unassignment if the target technician disappeared or the new assignment fails. Assignments retain calendar-name snapshots. Technician detail offers eligible available calendars plus its current unavailable selection (disabled with warning); cards show a bounded name and availability warning.

Audit actions include google.connection.initiated/completed/failed/replaced/disconnected, google.revocation.failed, google.scan.completed/failed, calendar.assigned/reassigned/unassigned/excluded/restored/assigned_removed. Existing audit retention and append-only debt remains open.

## Endpoints

All paths below are authenticated:

| Method       | Path                                          | Purpose                                                        |
| ------------ | --------------------------------------------- | -------------------------------------------------------------- |
| GET          | `/api/calendar-connections/google`            | Safe current status and impact counts                          |
| POST         | `/api/calendar-connections/google/start`      | CONNECT, RECONNECT, or confirmed SWITCH                        |
| GET          | `/api/calendar-connections/google/callback`   | Session-bound OAuth completion; fixed redirect                 |
| POST         | `/api/calendar-connections/google/scan`       | Complete manual discovery                                      |
| POST         | `/api/calendar-connections/google/disconnect` | Confirmed credential removal                                   |
| GET          | `/api/calendars`                              | Local catalog with source, availability, and exclusions        |
| POST         | `/api/calendars/{id}/exclude`                 | Confirm and suppress a Google calendar locally                 |
| POST         | `/api/calendars/{id}/restore`                 | Reinclude a suppressed calendar                                |
| PUT          | `/api/calendars/{id}/assignment`              | Atomic assign/transfer/unassign with expected current assignee |
| PUT / DELETE | `/api/technicians/{id}/calendar`              | Existing profile assignment endpoints                          |

## Safe manual acceptance - perform later, with a TEST account only

This procedure was **not performed automatically**. No real account or calendar was accessed during implementation/testing.

1. Create a dedicated Google test account and separate Google Cloud test project. Use fictional calendars and fictional technician data only.
2. In that project, enable Google Calendar API. Configure Google Auth Platform/OAuth consent, select the appropriate testing audience, and explicitly add the test account. Add only the CalendarList readonly scope. Google's testing-mode refresh-token lifetime and any verification requirements depend on project configuration; check the official OAuth guide when accepting the integration.
3. Create an OAuth client of type Web application. Register the exact redirect URI, for example `http://localhost:3000/api/calendar-connections/google/callback` for loopback development. Never use a wildcard. Production requires HTTPS and secure cookies.
4. Store the client ID/secret in the server's ignored `.env` or managed environment. Set `GOOGLE_MODE=real`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and `GOOGLE_OAUTH_REDIRECT_URI`. Keep the origin in `ALLOWED_ORIGINS`. Never use NEXT_PUBLIC_ variables for these values.
5. Generate a Fernet key in a private terminal with `.venv\Scripts\python.exe -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Store it as `GOOGLE_CALENDAR_CREDENTIAL_ENCRYPTION_KEY` in the protected server environment. Do not paste it into issues, chat, source, screenshots, or logs. Back up the key separately from encrypted database backups. Missing/wrong key requires recovery from the protected backup or deliberate disconnect/reconnect; do not edit ciphertext manually.
6. Start the app (`docker compose up -d --build --wait`) using disposable local data, create/sign in as a manager, and open Calendars. Keep the original development profile defaults only on loopback. Real deployment remains blocked by the debt register.
7. Click Connect Google Calendar. Verify the Google consent screen names the dedicated test project and requests only calendar-list discovery. Choose the TEST account. Verify return to `/calendars` with a safe success banner and generic account label.
8. Create several fictional test calendars, including a hidden calendar where practical. Click Scan Google Calendars. Verify every expected name appears. Rename one, add one, and rescan; verify stable internal identity and updated name without duplicates.
9. Assign GA - Atlanta to a fictional technician; verify the Calendars table, technician card, and detail selection. Reassign and unassign; inspect assignment history. Test a second technician claiming an already assigned calendar.
10. Remove an assigned calendar from Technician Hub. Confirm the warning, verify the technician becomes unassigned, and confirm the real Google calendar still exists. Rescan and verify it stays excluded. Restore it deliberately.
11. Remove access to a test calendar from the account, then scan. Verify UNAVAILABLE and preserved local assignment/history. Restore access and scan again to recover the same UUID.
12. Disconnect. Verify local credential removal, unavailable catalog, preserved assignments, and disabled Scan. Expect project-wide Google grant revocation; check the dedicated account security page if revocation failed.
13. Reconnect the same TEST account, consent again, then scan. Verify the same internal calendar identities, exclusions, and assignments recover. Test Change Google account only with a second dedicated TEST account after reviewing impact; verify accounts never share local catalog identity.
14. Save sanitized pass/fail evidence without OAuth URL parameters, tokens, cookies, or real profile data. Disconnect both test grants and remove disposable test data when done.

Key rotation is currently an operator procedure: stop provider operations, back up DB and key securely, disconnect while the old key is configured (revoking grants), install a new generated key, restart, reconnect each test account, and rescan. Metadata/assignments/exclusions persist. Automated in-place re-encryption and durable revoke retries are deferred in TD-025.

## Migration and automated testing

New revision `0a542f68aa75` descends directly from audited `e7b310920001`. Historical revisions are unchanged. Existing calendars become LOCAL_DEMO with AVAILABLE state; active assignment indexes and historical names stay intact. Fresh/populated upgrade and empty-provider downgrade/re-upgrade are supported. Downgrade refuses when connection/attempt data exists, avoiding silent loss of encrypted credentials, exclusions, and provider identities. For rollback after real adoption, restore a coordinated pre-upgrade database/key backup instead.

Tests use FakeCalendarProvider, synthetic credentials, and an isolated `technician_hub_test` database. Google network requests are denied by the backend test fixture; browser tests abort non-loopback requests. `GOOGLE_MODE=fake` requires APP_ENV=test and an approved local test database. The fake provider lives behind the normal authenticated OAuth flow; no production test HTTP endpoints are added. See STAGE2_GOOGLE_CALENDAR_VERIFICATION.md for actual counts and evidence.

## Independent audit clarifications

Account replacement now confirms an impact digest as well as connection generation.
The server rechecks calendar identities/names/exclusions and active assignments both
when starting SWITCH and when completing it. An intervening change consumes the
callback without replacing the account; close the warning and start again from the
latest status. Migration b2917d804e12 adds this digest to pending attempts; old pending
switches without it fail closed. Downgrading that additive revision burns pending
switch attempts before dropping the digest.

Reconnect without a new refresh token requires successful decryption, provider refresh,
required scope and matching primary identity for the retained grant. Token refresh is
serialized with OAuth/disconnect; a rotated scan credential is committed encrypted before
listing pages. PostgreSQL and external OAuth cannot share an atomic commit: a failed
local commit after exchange/rotation still requires operator recovery (TD-025).

Google advisory owners use dedicated unpooled connections, not transaction-pool slots.
Waiters release their connection between lock attempts. Budget these connections in
PostgreSQL and bound inbound requests before pilot. Synchronous HTTP running in a worker
thread completes before a single cancellation unwinds its lifecycle guard. Connect/read
timeouts do not impose a complete-scan deadline (TD-017/026).

CalendarList pagination has no application-controlled provider snapshot isolation.
Malformed/looping continuation, conflicting duplicate identity, failed pages and the
1000-page cap reject the entire catalog result. A structurally complete listing can still
omit a calendar moved between provider pages; local absence means UNAVAILABLE, never
permanent deletion. A later complete listing restores the same UUID and assignment.
An identical successful scan intentionally updates each calendar's last_seen_at;
connection.last_success_at alone does not describe the last observation of missing rows.
One scan audit event is emitted, not one per unchanged row.

Assignments survive exclusion as inactive name snapshots, and remain active/visible on
provider disappearance or disconnect. Explicit exclusion detaches atomically. Technician
deletion intentionally cascades all of that technician's assignment history; durable audit
retention is still TD-010. No-op assignment/unassignment/exclusion/restore adds no history
or audit event. Rename does not rewrite historical calendar_name snapshots.

The `v1:` credential envelope identifies format, not key identity. Keep encrypted database
backups and the matching external key in separately protected recovery channels. Losing
or replacing the sole key makes existing refresh tokens and pending PKCE verifiers
unreadable; restoration or deliberate reconnect is required. Never downgrade encryption
to plaintext. See the independent audit and TD-025 for remaining crash/revocation/rotation
recovery obligations.

### Cross-site callback cookie policy

Ordinary manager login retains its existing SameSite=Strict cookie policy. A successful,
CSRF-protected Google OAuth start reissues the same session cookie as SameSite=Lax so it
is included on Google's cross-site top-level GET callback. HttpOnly, configured Secure,
path and remaining session lifetime are preserved; the session is neither rotated nor
extended. Callback state still binds manager/session and is single-use. All normal
mutations still require exact trusted Origin and CSRF proof. A browser test simulates the
consent page on localhost and returns to 127.0.0.1; it performs no Google network access.

## Stage 3 event access and dedicated TEST-account runbook

Discovery-only connections remain valid. From Calendars choose Grant Event Access, authorize the same
dedicated TEST account for calendar.events.readonly, and verify discovery plus event capability separately.
Decline just event access once: discovery must continue, while Today explicitly asks for event access.
Repeat consent with and without a new refresh token where Google permits; never record tokens/codes.
Do not execute this acceptance automatically or use real business/customer calendars.

In a disposable TEST calendar, manually create fictional events:

1. An 08:00 `1. Furnace (old customer) didnt buy` job with a synthetic address.
2. An 11:00 normal numbered job, plus an unnumbered valid job.
3. A cancelled provider event and a `CANCEL - job` title.
4. A `fake job` title.
5. A valid title whose description contains `cancel` (must remain visible).
6. A recurring job and one cancelled occurrence; instances must appear individually.
7. All-day reminder, 07:59, 08:00, 22:00 and 22:01 boundary events.
8. Duplicate sequence numbers, Unicode and harmless script-looking text.

Assign the calendar to a fictional technician. Open Today, verify calendar wall-clock times (set the
browser to a different zone), title filtering, notes and empty-success/error distinctions. Preview
uses cleaned titles and the next work date. On Saturday and Sunday verify Monday; on Friday verify
Saturday. Use dedicated test dates around spring/fall DST and compare office calendar display.
Change a TEST event manually at Google, press Refresh, and verify the new data with a refreshed timestamp.
Disconnect/revoke event access and verify truthful states with local assignments retained. Never test
Google event insertion/update/deletion through Hub: no such methods exist. Confirm preview sends no
Telegram message. Record only synthetic counts, safe status codes and dates in acceptance evidence.

See STAGE3_CALENDAR_EVENTS.md for exact timezone, filtering, payload-budget and privacy rules, and
STAGE3_CALENDAR_EVENTS_VERIFICATION.md for automated fake-provider evidence.

## Stage 4 schedule delivery

See [Schedule delivery](SCHEDULE_DELIVERY.md) for the unified immutable dispatch path, dedicated
payload key, separate worker, calendar-local automatic delivery (OFF by default),
acknowledgement authorization, uncertainty recovery, retention, and dedicated TEST
acceptance runbook. The Telegram polling worker receives callbacks; the schedule
worker sends durable dispatches and evaluates automatic decisions. Neither starts
inside the web API. Stage 3 job filtering and wall-clock projection remain authoritative.
