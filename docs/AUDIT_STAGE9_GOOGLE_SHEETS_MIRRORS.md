# Independent Stage 9 Google Sheets mirror audit

## Scope and safety boundary

The audit started from `codex/stage9-google-sheets-mirrors` at
`3c1c0e97c79765df7b9833dfe172763f0105f70d` with a clean tree and continued on
`codex/stage9-google-sheets-mirrors-quality-audit`. The retained normal PostgreSQL
volume is `technician-hub_postgres_data`. Baseline fingerprints recorded one manager,
three calendars, no WorkReports, no Expenses, and zero mirror targets. All destructive
tests used only `technician_hub_test`. No real Spreadsheet ID, Google account, Telegram
account, or live provider was used.

Stage 5-8 WorkReport, Expense, accounting, week, money, revision, and XLSX semantics
were frozen. Audit fixes are confined to the Stage 9 mirror, its database invariants,
worker health contract, and mirror UI state.

## Architecture and authority boundary

PostgreSQL stores mirror targets, one coalesced refresh row per target/week, and worker
heartbeats. WorkReport and Expense submissions insert their business fact and enqueue
affected enabled Individual and All Tech targets in the same transaction, using stored
`operational_date` and `expense_date`. A standalone worker claims with `FOR UPDATE SKIP
LOCKED`, a UUID token, a DB-clock lease, and target/connection generations. It builds
the canonical `WeeklyAccountingXlsxModel` in a short database session, releases that
session, then calls Google. Finalization rechecks claim ownership and lifecycle
generations.

The Sheets provider reads only spreadsheet/tab metadata: `sheetId`, title, and grid
dimensions. It never reads cells, identities, expenses, reports, payments, or totals.
All business values come from PostgreSQL's audited accounting projection. Google
Sheets remains a derived, eventually consistent presentation artifact.

## Findings and fixes

| ID     | Severity | Finding                                                                                                                                                          | Disposition                                                                                                                          |
| ------ | -------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| S9-A01 | HIGH     | Distinct logical targets could be configured with the same Spreadsheet ID. Because both use the same deterministic week title, they could overwrite one another. | Fixed with an API conflict check and PostgreSQL unique index. Migration refuses ambiguous pre-existing duplicates for manual review. |
| S9-A02 | HIGH     | A fixed 15-minute lease was not renewed during long multi-chunk provider work. A second worker could reclaim while the first still wrote remotely.               | Fixed with a DB-clock lease-renewal task. Crash recovery still relies on expiry; stale owners still fail token finalization.         |
| S9-A03 | MEDIUM   | A retry claimed from `FAILED` could trust an older successful fingerprint and skip the deterministic repair pass.                                                | Fixed: failed claims never fingerprint-skip. Last-known-success metadata remains available for UI truthfulness.                      |
| S9-A04 | MEDIUM   | Database constraints did not encode lease ordering, successful-state metadata coherence, successful completion equality, or nonnegative Google sheet IDs.        | Fixed additively in `faa609190001`.                                                                                                  |
| S9-A05 | MEDIUM   | Slow configure/action/OAuth responses could update local busy/error/input state after the component moved to another technician or week.                         | Fixed by binding pending work and local state to the request identity; focused rerender coverage rejects stale results.              |
| S9-A06 | LOW      | Worker health collapsed an explicit clean stop or error into `STALE`.                                                                                            | Fixed with distinct `STOPPED` and `ERROR` states in API and generated contracts.                                                     |
| S9-A07 | LOW      | The 4 MB chunk estimator used compact UTF-8 JSON while `requests` uses escaped JSON with normal separators, undercounting non-ASCII request bytes.               | Fixed by measuring the actual encoding semantics and rejecting an indivisible oversized row.                                         |

No Critical finding remains. No High finding remains. All discovered Medium and Low
findings were localized and fixed.

## OAuth and security

The only Stage 9 scope is
`https://www.googleapis.com/auth/spreadsheets`. No Drive, Drive.file, or Drive.readonly
scope exists. Sheets permission requires explicit same-account `RECONNECT`; a
Calendar-only connection remains valid for calendar list, event access, and schedule
flows. Existing state hashing, single-use state, expiry, PKCE verifier encryption,
session binding, callback origin, and cookie rules remain unchanged and covered by the
full OAuth suites.

Mirror read and mutation routes remain manager-only. Mutation requests require exact
configured Origin and CSRF. Anonymous, inactive-manager, missing-CSRF, `null`, path,
and lookalike origins fail. Spreadsheet parsing is local; canonical URLs, `/edit`,
queries, raw IDs, whitespace, credentials, lookalike domains, JavaScript URLs, control
characters, and overlong values have adversarial coverage. Open links are constructed
only from validated IDs and use `noopener noreferrer`.

Fake Google remains startup configuration only. Settings reject fake providers outside
the isolated test environment/database. No request can select a provider, impersonate a
manager, or bypass session checks. The synthetic keys in `compose.e2e.yaml` exist only
in the disposable test stack and are not normal defaults or real credentials.

## Durability, generations, and recovery

Successful business writes and their refresh intent share one PostgreSQL transaction;
rollback removes both. Google failure, stopped worker, revoked OAuth, bad target, and
old queued work cannot roll back the business record. No provider method is referenced
by either business service. No target or a disabled target produces no automatic job.
With Individual and All Tech enabled, the same historical fact queues both exact
historical Monday rows.

One hundred changes to the same target/week remain one row while advancing
`requested_generation` to 100. `completed_generation` cannot exceed requested. A
generation arriving during provider work remains pending after the claimed generation
finalizes. Target replacement deletes obsolete queue state and advances target
generation; disable, removal, and Google connection generation changes prevent stale
lifecycle success. Last-success time/fingerprint survives a later failure, while status
remains FAILED or pending rather than Synced.

Claims and renewals use PostgreSQL `clock_timestamp()`. Tests prove one owner under 2,
5, 10, and 20 concurrent consumers. A valid expired lease can be reclaimed; the old
token cannot finalize after reclaim. A crash before the provider call is reclaimed
after expiry. A crash after a deterministic provider write retries the entire owned
range and converges. Network calls run without an open business transaction or retained
pool connection.

## Tab and owned-range reconciliation

Weekly titles remain deterministic Monday-Sunday titles. A stored numeric `sheetId` is
preferred over title; the documented contract retains a manager rename without
creating a duplicate. Deleting the tracked ID causes canonical-title adoption or new
tab creation and persists the new ID. An ambiguous `addSheet` timeout is resolved by
metadata lookup on retry. Target-level queue ownership plus lease renewal prevents two
workers for the same target/week from racing tab creation.

The application clears values, formats, and row/column dimensions only over the
bounding union of the prior and new A1-anchored owned rectangles. Row and column
shrink, growth, 50-to-10 All Tech cleanup, and multiple outside sentinels are covered.
Stage 8 and Stage 9 generate no merged cells, so there is no application merge state
to leave stale; formatting requests are explicitly merge-free. Manual values outside
the old owned rectangle survive. Manual values inside it are presentation edits and are
overwritten on a real refresh.

## Values, parity, and provider failures

Sheets consumes the shared Stage 8 presentation model and never recomputes accounting.
Gross, expenses, TOTAL, all eight payment buckets, three review buckets, two closer
buckets, maintenance, job rows, and Expense rows retain semantic parity. Monday-Sunday
dates are pre-rendered from canonical dates, so spreadsheet locale/timezone cannot move
business days. Technician name and All Tech inclusion/order changes alter fingerprints.
The layout version participates in every fingerprint.

Money is exact RAW text from `Decimal`, including `0.01`, `1.10`, `193.01`, `1793.16`,
`9999999999.99`, `99999999999900.00`, and `99999999999999.99`. No float conversion
exists. The HTTP request uses `valueInputOption=RAW`; strings beginning with `=`, `+`,
`-`, `@`, HYPERLINK, WEBSERVICE, IMPORTXML, and DDE-like text remain literal.

Values use a maximum of 500 rows and 4,000,000 actual JSON bytes per request;
formatting uses 400 operations per request. Boundary and mid-chunk failure tests prove
no missing/duplicate row and full-retry convergence. Values-success/format-failure and
provider-failure/retry paths do not claim success. HTTP 429 honors bounded
`Retry-After`; 5xx/network errors retry; 403, missing consent, and 404 are safe
actionable failures without hot loops. Only catalog codes reach database/API/logs;
token, address, expense, and customer canaries remain absent.

## Frontend and audit events

The UI distinguishes not configured, ready, disabled, permission required, reconnect,
pending, syncing, failed, and synced, and separately reports running, stopped, error,
stale, or missing workers. Last success remains visible alongside a current failure.
Configure, replace, enable, disable, remove, and exact historical sync use generation
preconditions. Enabling does not enqueue full history. Slow technician/week actions
cannot overwrite the new identity, including local input, busy, error, link, or status.

Configure, replace, enable, disable, remove, and manual sync create one safe audit event
with fixed metadata. Repeated status polling creates no audit events. Spreadsheet
contents, IDs as free-form payload, OAuth material, and provider bodies are excluded.

## Migration and normal-data preservation

The Stage 9 base migration remains unchanged. Additive audit migration
`faa609190001` adds Spreadsheet exclusivity and refresh lifecycle constraints. Fresh,
all historical, populated Stage 8, populated Stage 9, refusal, empty downgrade/re-upgrade,
one-head, and drift checks pass. Direct SQL probes reject invalid target relationships,
duplicates, non-Monday weeks, negative extents/sheet IDs, invalid generations/status,
invalid claim combinations, reversed leases, incoherent success metadata, and completed
generation ahead of requested.

The normal manager/calendar/business fingerprints and `technician-hub_postgres_data`
volume are checked before and after the audit. The normal mirror-target count remains
zero.

## Performance

Local deterministic measurements below exclude network latency and are not Google
quota evidence:

| Scenario                              | Rows × columns | Value bytes | Format ops | Value calls | Format calls | Total calls without optional add | Build ms | Peak bytes |
| ------------------------------------- | -------------: | ----------: | ---------: | ----------: | -----------: | -------------------------------: | -------: | ---------: |
| Individual typical                    |       120 × 12 |       8,275 |        235 |           1 |            1 |                                4 |     6.71 |    127,840 |
| Individual 500 reports / 500 expenses |       605 × 12 |     471,457 |        720 |           2 |            2 |                                6 |    55.00 |  2,251,534 |
| All Tech 10                           |      120 × 130 |      85,370 |      1,271 |           1 |            4 |                                7 |    41.49 |    763,921 |
| All Tech 50                           |      612 × 130 |     433,114 |      5,831 |           2 |           15 |                               19 |   236.26 |  4,428,933 |
| All Tech 100                          |    1,227 × 130 |     867,794 |     11,531 |           3 |           29 |                               34 |   486.92 |  9,161,170 |

One metadata and one clear request are included; a missing tab adds one request. There
is no technician cap. TD-034 remains open because local payload work is not live quota,
latency, or grid-limit evidence.

## Mutation evidence

The reproducible mutation harness killed 28/28 required mutants: cell authority,
synchronous Google use, missing durable enqueue, lost generation, stale lease owner,
duplicate worker ownership, blind ambiguous creation, ignored sheet ID, over-clear,
row shrink, All Tech cleanup, outside sentinel, USER_ENTERED, Decimal-to-float,
formula execution, missing Facebook, merged payment buckets, silent scope broadening,
Calendar coupling, stale target finalization, disabled auto-refresh, raw error leakage,
missing manager auth, CSRF/origin bypass, retained DB session, production fake mode,
failed fingerprint skip, and omitted layout version. A `finally` restoration plus
SHA-256 comparison confirmed all source bytes were restored.

## Verification results

| Gate                                           | Result                                                                             |
| ---------------------------------------------- | ---------------------------------------------------------------------------------- |
| Stage 9 focused and independent audit          | 77 passed                                                                          |
| Full PostgreSQL backend                        | 1,450 passed, 2 expected Windows platform skips                                    |
| Frontend unit                                  | 147 passed across 11 files                                                         |
| Strict TypeScript / ESLint                     | Passed after the stale-state ref fix                                               |
| Development Playwright                         | 28 passed, including mirror payload/state assertions                               |
| Production-image Playwright                    | 28 passed against the disposable production-image stack                            |
| Migration validation                           | Fresh/historical/populated/refusal/round-trip; one head `faa609190001`; zero drift |
| Mutation audit                                 | 28/28 detected; all source hashes restored                                         |
| Native/Docker builds                           | Native web plus API, web, and mirror-worker images passed                          |
| Ruff / format / Prettier / contracts / Compose | Passed                                                                             |
| Secret/privacy scan                            | 307 Git-visible files, 4 artifacts, 5 logs; 8/8 controls; zero findings            |

## Debt disposition

No debt was added or resolved. TD-033 remains OPEN before internal pilot because no
live TEST Google acceptance occurred. TD-034 remains OPEN before production because
the local scale probe is not live quota/latency/grid evidence. TD-035 remains OPEN for
later scale because Google row-height behavior was not visually accepted in real
Sheets. All earlier pilot blockers and TD-016/019/020 production blockers remain.

Stage 10 was not started.
