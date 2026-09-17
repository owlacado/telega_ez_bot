# Stage 3 calendar event views

Scope: read-only Today’s Jobs and next-work-day preview, based on audited commit
253071c8059c711e080c0e564b1253f6a7d0ebc7. No Stage 4 delivery, event writes, event mirror,
webhooks, accounting or scheduled dispatch is included.

## Official references verified before implementation

Reviewed 2026-09-17:

- [Events.list](https://developers.google.com/workspace/calendar/api/v3/reference/events/list)
- [Event resource](https://developers.google.com/workspace/calendar/api/v3/reference/events)
- [Recurring events](https://developers.google.com/workspace/calendar/api/guides/recurringevents)
- [Calendar timezones](https://developers.google.com/workspace/calendar/api/concepts/events-calendars)
- [Read-only scopes](https://developers.google.com/workspace/calendar/api/auth)
- [Incremental OAuth](https://developers.google.com/identity/protocols/oauth2/web-server#incrementalAuth)

Events.list uses singleEvents=true, orderBy=startTime, showDeleted=false, explicit calendar timeZone,
250 items per page and a partial-response fields mask. Recurring instances are expanded by Google;
instance ID, recurring parent and original start are retained. Cancelled tombstones are excluded even
when returned unexpectedly. Conflicting duplicate IDs/instances or statuses reject the entire fetch.
No sync token is used. Empty pages can continue. Malformed/repeated tokens and failed later pages never
produce a complete-looking partial result. Limits: 100 pages, 10,000 unique events, 8 MB cumulative body
and a 45-second pagination budget checked before each request and between stream chunks; individual
HTTP connect/read timeouts are 5/15 seconds. This is not a hard end-to-end deadline: a current blocking
HTTP read and lifecycle waiting may extend elapsed time. Quotas/admission remain TD-026/017.

## Capabilities and authorization

CalendarList remains `https://www.googleapis.com/auth/calendar.calendarlist.readonly`.
Event access adds only `https://www.googleapis.com/auth/calendar.events.readonly` through explicit
Grant Event Access and include_granted_scopes=true. No broad calendar or event-write scope exists.
Discovery works when event consent is absent, declined or partially granted. The stored granted_scopes
array is the only granted-capability state; the OAuth-attempt boolean describes requested intent.
Same-account, PKCE, hashed state, expiry, single-use, session and account-replacement protections remain.
Wrong-account upgrade never replaces the connection. A reused refresh credential must independently
prove the event capability; a one-off upgraded access token does not imply a refreshed grant has it.
Normal failed attempts leave existing discovery operational.

Both projections require a current manager session, including a second check after provider I/O.
They return no credentials, ciphertext or raw provider payload. API responses carry Cache-Control:no-store.
Provider events are fetched on demand, not persisted. This preserves a future caching boundary without
building a durable event mirror.

## Calendar wall-clock semantics

The assigned calendar’s IANA timezone defines operational today and the query day. Day boundaries are
local midnight and the following local midnight, converted independently to UTC. DST therefore yields
23/24/25-hour windows. Events.list overlaps these bounds (timeMin applies to end; timeMax to start).
Projection further requires the event’s calendar-local START date to equal the target date, so an
overnight event starting yesterday does not appear as a new job today.

Provider offsets are parsed as instants; explicit event timezone is validated. An offset-free provider
dateTime is accepted only with explicit IANA timezone and an unambiguous, existent local time. Response
fallback uses the assigned calendar timezone. Missing/invalid calendar timezone produces TIMEZONE_REQUIRED,
never the server timezone. An event’s instant is rendered in its calendar timezone, matching the office
calendar view: an office 08:00 job stays 08:00 for a technician/browser elsewhere. An event authored in a
different explicit zone is converted into the assigned calendar’s view, not the manager’s zone.
Technician timezone is not used to shift dispatch time. The browser displays server `display_start_time`
and `display_end_time` directly; UTC timestamps remain machine-readable. All-day dates have exclusive ends.
Accounting timezone policy is outside this stage.

## Business projection

One JobEventFilter is shared by Today and preview:

- Provider cancelled events and all-day reminders are excluded.
- Title-only, case-insensitive whole-word exclusion: cancel, cancelled, canceled, canceling, cancelling,
  cancellation, reschedule, rescheduled, rescheduling, fake, faked, faking, redo, redone, redoing.
  Punctuation/whitespace are tolerated; unrelated substrings and description words do not exclude jobs.
- Start time must be 08:00 through exactly 22:00, inclusive, in calendar wall time. Ends may extend later.
- Optional leading digits followed by a literal period establish job number. Numbered jobs sort first,
  then number, wall-clock start, actual start instant and provider ID. Unnumbered jobs follow by start/ID.
  Duplicate numbers remain visible with a warning. Zero is a valid explicit sequence; up to nine digits.
- Today retains the normalized near-raw title. Preview uses a separate schedule_summary that removes
  simple parenthetical notes and “didnt buy” (including apostrophe variants), then collapses whitespace.
  Raw summary is retained. No event is rewritten at Google.

The legacy rules in the task are the behavioral source; no readable legacy bot source was present in
the supplied workspace. Keeping unnumbered jobs is an intentional reliability improvement over strict
legacy numbering. All-day reminders are deliberately excluded, not subjected to an accidental 08:00 cutoff.

next_schedule_date: Monday→Tuesday, Tuesday→Wednesday, Wednesday→Thursday, Thursday→Friday,
Friday→Saturday, Saturday→Monday, Sunday→Monday. Saturday is a work day; only Sunday is skipped.
No holidays, individual working patterns or automated delivery are inferred.

## Data, privacy and UI

Normalized fields include provider_event_id, calendar_id, summary, bounded optional description/location,
start/end, all-day/status, optional validated Google html_link, recurring_event_id, original_start_time,
provider_updated_at and schedule display fields. Summary/location/description are capped at 500/1000/4000
characters in the API projection; filtering uses the entire bounded provider title before display truncation. Control characters are stripped while readable whitespace and Unicode survive. A source text
field above 100,000 characters fails the fetch. Unknown/missing times, reversed durations and malformed
payloads fail safely. Only exact HTTPS calendar.google.com links without credentials/ports/control spaces
are clickable. UI uses React text, bounded wrapping and a scrolling job list; notes expand on demand.

Successful reads do not write business audit records. Safe operational logs carry operation, internal
technician/calendar IDs, elapsed duration, result and count only. Capability/reauth transitions use a
small existing audit event without customer metadata. No raw summaries, addresses, descriptions,
provider response bodies or credential-bearing exceptions are logged. Client memory retains only the
currently visible response, clears it on refresh/failure and isolates URL/assignment identity.

States: READY (including empty success), NO_CALENDAR, CALENDAR_UNAVAILABLE, EVENT_SCOPE_REQUIRED,
REAUTH_REQUIRED, TIMEZONE_REQUIRED, PROVIDER_ERROR, CHANGED and BUSY. Unavailable local calendars never
issue event calls. Reauth retains assignments. Scope loss removes only event access; calendar ACL denial
is separately unavailable. Quota/temporary failure returns safe code/retry time. Manual refresh/retry is
explicit and deduplicated. Preview is a modal with a target date and Close; it has no Send action.

## Operational limits

Complete provider pagination is not a transactional snapshot; conflicting data fails conservatively.
External token rotation and PostgreSQL commit are not atomic. Credential-key rotation/recovery and
revocation durability remain TD-025. Large-day UI performance and global rate/admission limits remain
TD-015/017/026. Real Google incremental consent, shared calendar event visibility, recurrence and DST
acceptance remain manual under TD-027. Existing HIGH TD-010/011 and overdue TD-014 are not closed.
