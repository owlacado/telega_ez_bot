# Stage 9 Google Sheets verification

## Safety and preservation

- Started from `codex/stage8-weekly-xlsx-quality-audit` at
  `719c3e39ce994bf20470a41032071db75ae97af9` with a clean tree.
- Normal PostgreSQL, API, and web were healthy; the manager and retained
  `technician-hub_postgres_data` volume were preserved.
- Baseline fingerprints are in `.local/stage9-preservation.json`.
- No normal mirror target was configured and no live provider was contacted.

## Implemented verification

- Additive Stage 8-to-Stage 9 migration, one head, and zero schema drift.
- PostgreSQL constraints cover target relationships/singletons, Monday weeks,
  generations, status, claims, completion ordering, attempts, and owned extents.
  Downgrade refuses while target data exists.
- Focused fake-provider tests cover consent gating, local ID parsing, exact RAW money,
  fingerprints, idempotent skips, ambiguous creation, coalescing, leases, All Tech,
  outside-range sentinels, and constraints.
- The final focused OAuth, money, RAW, range, generation, concurrency, and DB-pool
  recheck passed 21 tests.
- The full PostgreSQL backend gate passed 1,414 tests with two expected POSIX-terminal
  skips and no failures. Stage 8 XLSX regressions were included.
- Frontend unit tests passed 146 tests. Development Playwright passed 28/28 in 4.2
  minutes. Fresh production-image Playwright passed 28/28 in 4.0 minutes with zero
  retries.
- The initial production-image run exposed missing fake Google, credential-key, and
  schedule settings in `compose.e2e.yaml`: OAuth start returned a sanitized 503 and
  later cleanup calls timed out. After adding only disposable fake/test settings,
  the six targeted scenarios passed and the fresh full run passed.
- The 24 required mutations were detected, and SHA-256 checks confirmed all mutated
  source files were restored byte-for-byte.
- Fresh/historical/populated migrations, Stage 8-to-Stage 9 preservation, rollback
  refusal with target data, empty rollback/re-upgrade, one head, and zero drift passed.
- Secret/privacy scanning checked 302 Git-visible text files, two text artifacts, and
  five container logs. Eight positive controls were detected and the real scan had
  zero findings.

## Local payload scale probe

Synthetic empty-report technician blocks, measured on the local verification host:

| Technicians | Rows × columns | Value JSON bytes | Format ops | Value calls | Format calls | Build ms | Peak bytes |
| ----------: | -------------: | ---------------: | ---------: | ----------: | -----------: | -------: | ---------: |
|          10 |      120 × 130 |           61,041 |      1,251 |           1 |            4 |    40.25 |    815,223 |
|          20 |      243 × 130 |          123,257 |      2,371 |           1 |            6 |    81.43 |  1,515,871 |
|          30 |      366 × 130 |          185,473 |      3,491 |           1 |            9 |   128.37 |  2,397,580 |
|          50 |      612 × 130 |          309,905 |      5,731 |           2 |           15 |   223.47 |  4,230,271 |
|         100 |    1,227 × 130 |          620,985 |     11,331 |           3 |           29 |   488.78 |  8,764,669 |

One sync also uses one metadata call, at most one add-tab call, and one owned-range
clear call. Formatting operations are carried in batches of 400, not per-cell HTTP
requests. These are bounded local measurements, not live-provider capacity evidence.

## Mutation coverage

Assertions detect Sheet authority, renderer recalculation, net-TOTAL changes,
USER_ENTERED, Decimal-to-float, executable formulas, missing review/payment fields,
duplicate tabs, over-clearing, shrink residue, provider work during business commits,
lost generations, duplicate ownership, stale lifecycle finalization, silent OAuth
broadening, raw error leaks, missing auth/CSRF/origin, presentation drift, All Tech
caps, and DB connection retention during provider work.

## Live acceptance

Real Google acceptance was deliberately not run. Follow the dedicated TEST procedure
in `GOOGLE_SHEETS_MIRRORS.md` with a TEST account and TEST Spreadsheet before pilot.
