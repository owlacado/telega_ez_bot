# Technician expenses — Stage 6

PostgreSQL is canonical. Expenses have no Google Form, Sheet, mapping row, Calendar,
Discord, receipt-upload, customer/job, reimbursement or approval dependency. See
[legacy evidence](LEGACY_EXPENSE_INVENTORY.md). This workflow stores raw facts;
it does not implement Daily/Weekly Accounting or payout formulas.

## Technician flow and fields

An active linked technician uses **Expenses** or `/expenses` in the private bot.
The manager must first set **Accounting timezone** on the technician profile to an
explicit IANA zone (for example `America/Los_Angeles`). Existing profiles migrate
with NULL; no automatic assignment or calendar/browser fallback is used. Without a
zone the bot explains that setup is needed and issues no credential. Clearing the
zone before submission blocks the submission. Historical expenses remain readable.

The mobile form accepts:

- `expense_type`: required trimmed free text, original case, at most 100 characters;
  blank, markup delimiters and Unicode control/format characters rejected. There
  is no taxonomy, enum, dropdown or accounting bucket.
- `amount`: required ASCII decimal string, 0.00 through 9999999999.99 inclusive,
  at most two fractional digits, Decimal and PostgreSQL NUMERIC(12,2). Zero is
  intentional legacy parity. No negatives, float JSON, exponent, commas,
  whitespace, nonfinite values or silent rounding.
- `note`: optional plain multiline text, at most 4000 characters before cleanup;
  outer whitespace trimmed, control/format characters removed except newline/tab.
  Markup is rendered as literal text, never HTML.

Technician, date and timezone are server-owned. No receipt URL/file/photo field is
accepted. Receipt photos may remain in the technician work group outside Hub;
Hub does not store, fetch, link or claim to manage them. Attachment storage remains
out of scope, consistent with the latest legacy app. Receipt/service-contract is a
different workflow and is not implemented here.

## Security and retries

`TechnicianFormSession` is shared with Work Reports, discriminated by `EXPENSE`.
The existing 600–900 second configuration `WORK_REPORT_SESSION_SECONDS` applies
(default 900); there is no second authentication scheme. A 32-byte random token is
returned only to the trusted private Telegram command; only SHA-256 is persisted.
The link uses a fragment and the browser sends an Authorization bearer header with
cookies omitted. The server checks purpose, active technician, current Telegram
user/bot, binding generation, availability, revocation and database-clock expiry
under technician → binding → session locks. There are at most five OPEN form
sessions combined across purposes. Older/expired metadata is retained (TD-031).

Bearer links **are transferable**. A copied valid link can be used in another
browser; no Telegram initData proof or device binding is claimed. Deployment and
actual mobile acceptance remain TD-030 obligations.

One session atomically creates one stable expense, immutable revision 1, consumed
session state, normalized payload fingerprint and metadata-only audit event. Same
payload retries return the same UUID/revision receipt, including after TTL while
current identity remains eligible. Changed retries conflict. A new session can
create another real expense with identical values; there is no fuzzy deduplication.
Browser retry preserves the submitted payload even if inputs later change.
Refresh of a consumed link shows the saved receipt. Browser confirmation is the
only success delivery; no new Telegram outbox has been introduced.

Manager-authenticated POST `/api/technicians/{id}/expense-sessions/{session_id}/revoke`
revokes an OPEN expense session. Work Report revocation cannot cross purpose.
Deactivation, disconnect/rebind and submission share the existing lock boundary.

## Date and history

Expense business date is the PostgreSQL wall-clock submission instant converted
in the currently configured technician accounting timezone. It is calculated after
locks; the form displays a preview and explicitly warns that midnight may change
the saved date. The revision freezes date, timezone, submission instant and
technician name. Changes to profile/timezone do not rewrite history. This is
separate from Work Report calendar/dispatch wall-clock dates. Database triggers
validate zone names and date/instant consistency. DST, midnight and browser/server
timezone mismatch are tested with explicit instants, not browser parsing.

`TechnicianExpense` stores UUID, technician FK, creation time and current revision
pointer. `ExpenseRevision` stores the immutable submitted fields, attribution
snapshot, date/zone, revision number and submitted time. Unique revision numbers,
deferred current-revision FK, contiguous sequence triggers and immutable
UPDATE/DELETE guards protect both tables. Technician FK uses RESTRICT. Permanent
technician deletion returns a business-history conflict; deactivation preserves
reads. There is no expense deletion/correction/void endpoint. Supporting revisions
2+ later requires a deliberate migration of the Stage 6 immutability boundary.

Future accounting must use `current_expenses()`: join expense ID **and** current
revision number. Never sum history rows independently. Current Stage 6 records are
all submitted valid facts; no invented payment/approval state is exposed.

## Manager views and privacy

The technician detail quadrant shows Work Reports and Expenses separately.
Expense recent list defaults to 20, maximum 100. Today amount/count aggregates all
current expense revisions for this technician's current local date, independently
of the list bound, in the same SQL snapshot as the list. Missing timezone displays
an unavailable total. No Net, Profit, Payout or gross-minus-expenses figure is shown.
Expense detail is read-only and shows the stored attribution/date/zone/type/amount/
note/revision/submission time and the absence of a stored receipt.

Expense form APIs accept capability only; manager APIs require manager session.
Client identity/date/receipt fields are rejected. Requests share the audited 32KiB
stream bound and duplicate JSON-key rejection. APIs use no-store/no-referrer;
frontend uses no-store fetches and a dynamic expense page. Content never enters
generic audit metadata or operational logs. Failures return sanitized messages.
No public test/issuance/provider route exists; fake harness is stdin-only and
restricted to a loopback database named `technician_hub_test`.

## Migration and operations

Additive revision `f6e609180001` follows audited `e5f509180003`. Existing Work Report
rows, profiles and manager accounts are preserved. Existing timezone remains NULL
until explicitly configured by a manager. Deploy with old writers stopped before
using EXPENSE sessions, since the old shared model only accepts WORK_REPORT.

Downgrade refuses if expense history, expense sessions or configured timezone data
would be lost. An empty Stage 6 database can downgrade/re-upgrade; populated history
must not be deleted to enable rollback. Destructive tests use isolated PostgreSQL.
Retention, archival/anonymization, encrypted backup policy and session purging remain
TD-031. Corrections, uploads, delivery, full accounting and mirrors are deferred
scope rather than silently promised features. No Stage 7 work is included.
