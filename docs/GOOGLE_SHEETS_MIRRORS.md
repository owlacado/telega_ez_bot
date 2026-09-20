# Google Sheets weekly accounting mirrors

Google Sheets mirrors are optional, derived, eventually consistent presentation
artifacts. PostgreSQL current WorkReport and Expense revisions feed the audited
`WeeklyAccounting` projection, which feeds the shared Stage 8 presentation model and
the Sheets payload. The application never reads Sheet values as business facts and
never imports manual edits.

Stage 9 requests only `https://www.googleapis.com/auth/spreadsheets` through an
explicit same-account OAuth reconnect. Calendar-only consent remains operational and
reports **Sheets permission required**. No Drive scope is requested. Managers supply
an existing Spreadsheet ID or normal `docs.google.com/spreadsheets/d/<id>` URL; URL
parsing is local and only the validated ID is stored.

Each technician can have one Individual target; one All Tech target is allowed. A
Spreadsheet ID can belong to only one mirror target because all targets use the same
deterministic week-tab namespace. Targets bind to the Google connection and carry a
lifecycle generation. Replacement is explicit. Disable and removal stop future
writes and never delete Google content.

Every selected week is Monday-Sunday and uses `YYYY-MM-DD - YYYY-MM-DD`. The worker
prefers a still-existing stored numeric sheet ID, so a manual rename is retained. If
that ID was deleted, it adopts the exact canonical title or creates it. If `addSheet`
succeeds but its response is lost, the retry refetches metadata and adopts the
existing tab rather than creating a duplicate.

Successful WorkReport and Expense submissions enqueue/coalesce affected Individual
and All Tech weeks in the same PostgreSQL transaction. Weeks come from
`operational_date` or `expense_date`. Manual sync uses the same durable upsert and
returns immediately. Configuration does not backfill history.

`requested_generation` advances for every request and `completed_generation` records
only the claimed snapshot. A change during provider work remains pending. Workers
claim with DB time, `FOR UPDATE SKIP LOCKED`, UUID tokens, and finite leases. Claim
and finalize transactions are short; canonical projection and provider calls run
without a business transaction or checked-out DB connection. Expired leases are
reclaimable, active workers renew their leases with DB time during long provider
operations, and stale claim/target/connection owners cannot finalize newer state.

The `accounting-mirrors` Compose profile starts the dedicated worker. The queue
survives API, worker, and Docker restarts. Heartbeats distinguish running, cleanly
stopped, error, stale, and never-seen worker states from Google failures.

Sheets reuse Stage 8's `WeeklyAccountingXlsxModel`, block geometry, labels, band
layout, styles, height/width rules, and text normalization. Google maps those roles
to Sheets formatting. Units, font metrics, pagination, print settings, and money-cell
types differ, so pixel parity is not claimed. Stage 8 intentionally uses no merges.

Every value write uses `valueInputOption=RAW`; no formula is generated. Strings
starting `=`, `+`, `-`, or `@` remain literal. Currency is canonical display text
such as `$1,793.16`, never `float(Decimal)`, preserving exact cents and large values.

The app owns only its recorded A1-anchored rectangle. Refresh clears values and
formats over the bounding union of old/new extents, then rewrites the payload. Shrink
removes stale rows and All Tech bands; growth expands the grid; outside data survives.
Manual changes inside the owned rectangle are overwritten. Values use bounded
500-row / 4 MB actual JSON-body chunks and formatting uses batches of 400 requests.

429 and transient 5xx/network failures receive bounded backoff and meaningful
`Retry-After`. Missing spreadsheets, access denial, and missing consent are permanent
until manager action. Partial writes never finalize success; retries rebuild the
entire deterministic range. A failed attempt cannot use the prior successful
fingerprint to skip that repair. Only safe error codes are persisted. Tokens,
response bodies, headers, and accounting values are excluded from logs and audit
events.

Managers configure, replace, enable, disable, remove, sync a selected historical
week, poll status, and open a locally constructed URL with `noopener noreferrer`.
Once mirrored, data is governed by the Google Spreadsheet sharing settings. The
manager controls them; Technician Hub cannot make an externally public Sheet private.

For later live acceptance, use a dedicated TEST Google account, TEST Spreadsheet,
and fictional data. Verify consent upgrade, both target types, auto-refresh,
rename/delete reconciliation, revocation, rate limits, and sharing. Do not use
production accounts or customer data.
