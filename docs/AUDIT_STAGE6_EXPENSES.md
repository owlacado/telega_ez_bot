# Independent Stage 6 expense audit

## Starting evidence and architecture map (before implementation edits)

Starting branch `codex/stage6-expenses`, clean HEAD `1d6c092a3332b203cfe97bb8329422b7c423990f`.
Audit branch `codex/stage6-expenses-quality-audit`. Normal Compose API/database healthy; web running.

- `hub/expenses/models.py`: canonical UUID/technician/current-revision parent; immutable snapshot revision with amount, date, timezone, type, note, name and submission instant. Deferred composite FK and contiguous-sequence triggers protect current history; technician FK RESTRICT.
- `hub/work_reports/{models,service}.py`: shared purpose-discriminated form sessions, 32-byte random bearer/SHA-256 storage; technician -> binding -> session lock order, database wall clock, active/current binding generation, max five OPEN sessions. Submitted same-payload receipts can replay after TTL.
- `hub/telegram/{transport,updates}.py`: private Expenses command, current active binding, fragment-bearing mobile link. No external confirmation delivery on save.
- `hub/expenses/{schemas,service,router}.py`: strict decimal string parsing and bounded normalized free-text fields; server-owned date from submission instant and explicit profile zone; transaction creates expense/revision/session/audit. Independent sessions deliberately allow identical business values.
- Manager list/detail require manager auth; shared middleware separates capability endpoints, bounds JSON at 32 KiB, rejects duplicate keys and sanitizes errors. Audit stores event/entity/actor kind without business content. Global response privacy headers apply.
- `expenses.tsx`, `expense-form.tsx`, `use-resource.ts`: mobile fragment capability, credentials omitted, frozen retry payload, saved receipt; server-derived manager date/total and bounded recent list; path/identity guards protect technician navigation.
- `technicians/{schemas,service,router}.py`, `profile-panel.tsx`: optional explicit ZoneInfo-validated accounting timezone; deletion serializes on technician and rejects report/expense history. Current manager timezone field is free text; summary does not expose setup status for it.
- Migration `f6e609180001` adds schema/triggers and guards destructive populated rollback after audited Stage 5. No prior migration will be edited; audit fixes use a successor.
- Legacy inventory and authoritative read-only `ez_telega_bot/expenses/{models,services,tests/test_domain}.py` agree on free text, nonnegative Decimal including zero, maximum 9999999999.99, no receipt field. Correction/void/delivery are explicitly deferred.
- TD-030 covers transferable bearer and dedicated TEST acceptance; TD-031 covers retained form metadata and immutable business history/backup/privacy policy. Neither is eligible for closure by fake-provider tests.

## Verification status

Audit completed. Final results below are independently executed against the audited code.
Prior implementation results were context, not counted as proof.

## Reproduced findings and targeted fixes

| Severity           | Finding                                                           | Evidence and remediation                                                                                                                                                                                                                                                |
| ------------------ | ----------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| HIGH               | Direct SQL silently changed financial values                      | New raw INSERT regressions accepted 1.001, 1.009, -0.001 and 9999999999.991 under NUMERIC(12,2). New successor migration removes typmod, retains range, adds scale <= 2. Existing values are preserved; invalid precision cannot reach storage through rounding.        |
| MEDIUM             | Expiry could cross between authorization and submission timestamp | Controlled database-clock ticks at expiry-1 microsecond and expiry reproduced acceptance. Final submission timestamp now rechecks expiry. Same committed-payload retries retain their documented post-TTL receipt behavior.                                             |
| MEDIUM             | Placeholder timezone accepted                                     | Profile PATCH accepted Factory, which is not a technician's accounting location. Python and DB reject placeholder/environment zones; manager choices are the intersection of Python and PostgreSQL supported names. PostgreSQL-unavailable names return a truthful 422. |
| MEDIUM             | Missing timezone hidden from setup overview                       | Summary omitted timezone and dashboard/card did not warn. Summary now includes it; dashboard/card show missing setup, profile provides named US choices and complete supported selection including current value and existing save errors.                              |
| MEDIUM             | Pathological read plan after bulk intake                          | Initial cold-statistics 10,000-row list/total took 21,917 ms. Materialization alone still took 9,133 ms. Final current-revision projection uses bounded indexed lateral lookups and reuses a materialized current-facts set; final measurements below.                  |
| LOW, fixed locally | Bot invitation overstated configured lifetime                     | Expense invitation said 15 minutes even with a 600-second configuration. It now displays configured whole minutes (settings only permit 600-900 seconds).                                                                                                               |

No new CRITICAL finding. The SQL money defect was not exploitable through the strict
public money parser, but violated the promised durable financial boundary and would
silently corrupt future/direct writers. All original migrations remain unchanged.

## Business and security conclusions

- Read-only authoritative legacy inspection confirms required case-preserving free
  text, nonnegative Decimal including zero, 12 total digits/2 cents, optional note,
  no application receipt. Strict no-rounding input, 4,000-character bound and
  explicit nullable setup are deliberate improvements. Corrections/void/delivery
  remain deferred, not claimed as parity delivered.
- A 256-bit random fragment credential is a transferable bearer. A copied eligible
  link permits preview, one expense and receipt replay; no actor proof in another
  browser is asserted. Purpose, current technician activity, Telegram user/bot,
  binding generation, revocation and wall-clock expiry constrain it. Manager cookie
  alone cannot submit; bearer alone cannot read manager endpoints. Organization-wide
  manager UUID reads are intentional.
- Token SHA-256 is the only persisted credential. Raw tokens are not manager/API
  response fields, OpenAPI examples or audit metadata. Fragment is absent from HTTP
  request targets and Referer; no third-party resources/analytics are present on the
  mobile form. Browser history and local browser access still expose the bearer:
  TD-030 remains open. Screenshots omit browser chrome; no live tokens are published.
- Expense normalization accepts only ASCII unsigned decimal strings with 1-10 integer
  digits and optionally 1-2 fractional digits (or internal Decimal). No whitespace,
  commas, exponent, nonfinite, negative, JSON number/bool or Unicode digits; leading
  zeros are allowed within the digit bound. Decimal remains authoritative end-to-end.
  Direct SQL exact values use NUMERIC, bounded range and scale; excess trailing
  precision is rejected too. Zero is a valid fact.
- Type trims outer whitespace, preserves case and literal Markdown, rejects empty,
  > 100, markup delimiters and remaining Unicode category-C characters. Outer newline/
  > tab whitespace is trimmed before the single-line check, consistent with legacy.
  > Note is <=4,000 code points before cleanup, strips category-C except newline/tab,
  > trims outer whitespace and renders literal HTML. No receipt upload/link/storage,
  > arbitrary URL fetching, amount-based uniqueness or invented category exists.
- Shared form requests enforce streamed 32 KiB admission (including a 3 MB JSON
  probe), duplicate-key rejection, same-origin request headers and sanitized errors.
  Infrastructure connection/concurrency/request admission still belongs to existing
  TD-012/017/026. No new production fake/issuance route exists; the CLI harness
  remains guarded by loopback and database name technician_hub_test.
- Audit submission actor kind is TECHNICIAN, with no fake manager actor. Immutable
  expense entity -> technician FK preserves attribution after disconnect; submitted
  name is snapshotted. Notes/type/payload/token/hash are absent from generic audit.
- Date is PostgreSQL submission wall-clock converted using explicit technician zone.
  Five US zones, fixed-offset Etc/GMT+5 semantics, local midnight, UTC date differences,
  spring/fall transitions, NY -> Denver change and a Tokyo browser are checked.
  Historical date/zone snapshots remain stable. Missing timezone blocks issuance,
  form open and final submit; no calendar/browser/server fallback.
- Same-session 20-way retries yield one expense/revision; distinct valid sessions
  with identical fields each yield their own expense. Changed retry conflicts without
  revision 2. Browser test loses the response after DB commit then retries safely.
  Locked lifecycle races reject stale generation/inactive/deleted identity. Both
  delete/submit orders preserve either deletion without expense or expense with
  deletion blocked. WorkReport-only/Expense-only/both/neither retention is exercised.
- Actual PostgreSQL metadata was inspected: required fields, range/scale checks,
  immutable parent/revision triggers, deferred same-parent current-revision FK,
  unique contiguous revision sequence, owner check, submission markers, date/zone
  consistency, and RESTRICT history FKs. Direct SQL and ORM challenges cannot update,
  delete, orphan or append an inconsistent future revision. No correction/delete API
  is exposed. SQL owner/superuser privileges can disable guards and are outside the
  application threat boundary; controlled mutations do so only in isolated tests.
- Latest-only selection is challenged with synthetic revision 2. Today sum/count
  covers all current rows independently of latest-list bounds; >100/day and 10,000
  same-day rows remain valid. No Net/Profit/Payout semantics are introduced.
- React renders text, wraps unbroken content and bounds manager panel scrolling.
  Delayed A responses and selected A detail cannot appear under B. Today uses the
  server business date/zone, with missing configuration shown as unavailable.
- Private/group/supergroup/channel/malformed/unlinked bot contexts are challenged.
  Browser saved receipt is the only success delivery; no external Telegram send is
  falsely claimed. 1,000 mixed-purpose issuances retain metadata with max five OPEN.

## Evidence and limitations

Only isolated technician_hub_test databases and fake providers are used for
adversarial, destructive, concurrency, migration and browser tests. Normal manager
and volume preservation are checked with opaque row fingerprints. Prior implementation
results are not counted as new audit proof. Test-only huge parameter IDs initially
exceeded Windows' environment-variable limit; they were shortened and rerun.

Development HTML-shell caveat (LOW, documented): bundled Next development mode
unconditionally emits `no-cache, must-revalidate` for the public form HTML shell
(`next/dist/server/base-server.js`). That shell contains no expense facts or bearer;
all private form/API responses remain `no-store`. Production dynamic form HTML is
required to be `no-store` and tested separately. No framework monkeypatch/custom
server was introduced solely to alter development shell caching.

## Measured performance

Measured on local PostgreSQL 18 with synthetic single-technician/same-day data,
all revision/timezone/retention guards enabled, no manual ANALYZE before reads.
Seeding is excluded from read timings. Values are local observations, not an SLA.

| Expenses | Recent list + complete today total/count |  Detail | SQL statements |
| -------: | ---------------------------------------: | ------: | -------------- |
|       10 |                                 16.73 ms | 5.38 ms | 2 + 1          |
|      100 |                                 15.07 ms | 5.19 ms | 2 + 1          |
|    1,000 |                                 15.41 ms | 4.57 ms | 2 + 1          |
|   10,000 |                                 33.03 ms | 5.54 ms | 2 + 1          |

The two list statements are DB wall clock and one coherent list/aggregate SQL;
manager route metadata reads add a fixed number, never N+1. Detail is one query.
List returns at most 20 by default (API maximum 100), even when today has 10,000
expenses. Every count and exact Decimal total was checked. Future operational
capacity and broad list scaling remain TD-015, not inferred from local timings.

## Mutation proof

All **20/20** mutations were detected by assertion failures, with no collection-error
substitute. Each mutated source file was restored from original bytes in finally;
DB mutation fixtures restore FK actions and immutable triggers in finally.
Evidence: `.local/stage6-audit-mutations.json` and sanitized per-mutation logs.

| Mutation                                | Regression                                  |
| --------------------------------------- | ------------------------------------------- |
| Missing-zone UTC fallback               | Direct missing-zone HTTP/local-date checks  |
| Server date instead of technician date  | Same UTC instant across zones               |
| Expiry bypass (both checks)             | Expired capability rejected                 |
| Binding-generation bypass               | Rebound capability rejected                 |
| Negative money accepted                 | Strict money rejection matrix               |
| Money parsed through float              | Decimal FloatOperation trap                 |
| Fuzzy business-value deduplication      | Separate identical sessions persist         |
| Used session creates again              | Concurrent retry receipt invariant          |
| Revision UPDATE allowed                 | Direct SQL history immutability             |
| Historical rather than current revision | Synthetic revision 2 latest-only projection |
| Technician cascade deletion             | Direct SQL retained history                 |
| Total computed from bounded list        | 22 same-day expenses with list limit 2      |
| Gross-minus-expenses labelled Net       | Frontend financial-label assertion          |
| Payload/note logging                    | caplog and metadata privacy assertions      |
| Manager session substitutes capability  | Manager-only submission rejected            |
| Remove no-store                         | API privacy headers                         |
| Remove referrer policy                  | API privacy headers                         |
| Expose raw capability in response       | Response content privacy assertion          |
| Group issuance allowed                  | Private-only trusted-event matrix           |
| Accept client technician identity       | Server-owned identity payload rejection     |

## Reproduction

From the repository root with its installed venv/Node dependencies:

- `python -m pytest apps/api/tests -q` (default isolated loopback test DB on 5437;
  conftest rejects other database names/nonlocal hosts).
- `python -m pytest apps/api/tests/test_expense_audit.py apps/api/tests/test_expense_retention_audit.py apps/api/tests/test_expenses.py -q`.
- `python scripts/validate_migrations.py` against a separately configured disposable
  TEST_DATABASE_URL, never the normal development database.
- `npm test`, `npm run test:e2e`; production E2E_BASE_URL targets the isolated fake
  image stack with matching test DB/key. Provider guard fixtures forbid live calls.
- `npm run build`, `npm run typecheck`, `npm run lint`, `npm run format:check`,
  `python -m ruff check apps/api scripts`, `python -m ruff format --check apps/api scripts`,
  `python scripts/check_contracts.py`, `python scripts/scan_secrets.py`, `git diff --check`.

Final gate results, preservation and commit are recorded below after completion.

## Final verification and disposition

| Gate                                                 | Final result                                                                                                                                                                       |
| ---------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Full PostgreSQL backend, Stages 0-6                  | **1,208 passed, 2 skipped**, 847.42 seconds. Three upstream python-telegram-bot deprecation warnings.                                                                              |
| Windows skips supplemented on Linux                  | Both real terminal manager CLI tests passed; 19 unrelated tests deselected.                                                                                                        |
| Expense focused cases within full run                | **177 passed**: original 87 + independent timezone/financial/concurrency/performance 86 + retention combinations 4.                                                                |
| Supplemental DB probes                               | **9/9 passed**: revision gap, pointer mismatch, unpointed future row, duplicate revision, ORM update/delete, SQL Factory rejection, two contradictory session marker combinations. |
| Frontend                                             | **124 passed**, 9 files; mobile retry, late A -> B response, no Net label, setup warning and timezone selection included.                                                          |
| Development Playwright                               | **27 passed**, 4.3 minutes.                                                                                                                                                        |
| Production-image Playwright                          | **27 passed**, 3.5 minutes; form HTML no-store verified.                                                                                                                           |
| Mutation experiments                                 | **20/20 detected**, source bytes and DB guards restored.                                                                                                                           |
| Native production build / strict TypeScript / ESLint | Passed.                                                                                                                                                                            |
| Ruff lint / Ruff format / repository Prettier        | Passed; 139 Python files formatted.                                                                                                                                                |
| Generated contracts                                  | Runtime snapshot matches; regeneration byte-identical.                                                                                                                             |
| Migration / one head / drift                         | Fresh, audited Stage 5, populated Stage 6 forward/round-trip, guarded destructive rollback, preserved legacy rows; zero drift. Head **f6e609180002**.                              |
| Docker                                               | Compose config, API/web builds, isolated startup/health passed.                                                                                                                    |
| Workers                                              | Telegram and schedule delivery disabled with networking unavailable; both exited safely without provider initialization.                                                           |
| Secrets                                              | **261 Git-visible files, zero findings**; synthetic Expense capability positive control detected and removed.                                                                      |
| Privacy                                              | Audit logs/XML/JSON, static browser bundles and both isolated container logs scanned; zero credential leaks. Deliberate mutation leaks redacted before archival.                   |
| Whitespace                                           | git diff --check passed.                                                                                                                                                           |

Authoritative artifacts are `.local/stage6-audit-backend-final.{log,xml}`,
`stage6-audit-{frontend-final,development-browser-final,production-browser,migrations-final,
linux-tty,native-build-final,typecheck-final,eslint-final,ruff-final,format-final,
contracts,secrets,development-upgrade}.log`, mutation/DB-probe JSON and privacy JSON.
These local verification artifacts are ignored by Git; no credentials or traces are committed.
Mobile and manager screenshots under `apps/web/test-results/{development,production}`
were inspected. The 375px form fits and literal markup does not execute.

The normal stack was forward-upgraded only after isolated migration/expense/browser
acceptance. Opaque before/after fingerprints matched for technicians (including
accounting timezone), managers, work reports/revisions, expenses/revisions, calendars
and Telegram bindings. Normal named volume **technician-hub_postgres_data** was
preserved; no manager was created, deleted or reset. Normal API/web are healthy,
provider modes remain disabled, runtime expense files match final source and the
normal schema has zero drift with every expense integrity trigger enabled.
Only the two temporary audit stacks were stopped; the existing CLI stack was untouched.

No real Google/Telegram account, technician or customer data was used in testing.
Normal preservation checks exported only opaque fingerprints, never record contents.
No push, history rewrite, Stage 7 accounting, Contracts or GPS work occurred.

No new debt IDs or closures. **31 total / 10 resolved / 21 open** remain; TD-030/031
stay open and all existing pilot/production gates remain. New Critical findings: 0;
new High: 1 fixed; Medium: 4 fixed; Low: configured bot lifetime fixed and public
development-shell cache caveat documented. No unresolved Critical/High expense
finding remains. Commit message: `chore: audit expense integrity`.
