# Stage 0 verification

Verified locally on Windows on September 16, 2026. No external integrations were invoked.

## Installed stack

- Next.js 16.3.5, React 19.3.0, TypeScript 5.9.3, Tailwind CSS 4.3.3.
- Native Python 3.13.7; Docker image Python 3.13 slim.
- FastAPI 0.141.1, SQLAlchemy 2.0.54 async, asyncpg 0.31.0, Pydantic 2.13.5, Alembic 1.20.0, Uvicorn 0.53.0.
- PostgreSQL 18.6 through `postgres:18-alpine`.
- Node.js 24.19.0 on Windows; Node 24 Alpine in the frontend image.
- npm and Python dependency resolutions are recorded in `package-lock.json` and `apps/api/requirements.lock`.

## Checks

| Check                                    | Result                                         |
| ---------------------------------------- | ---------------------------------------------- |
| PostgreSQL integration tests             | 33 passed                                      |
| Frontend component tests                 | 8 passed                                       |
| Playwright native smoke flow             | Passed                                         |
| Playwright production Compose smoke flow | Passed                                         |
| Next.js production build                 | Passed on Windows and in Linux Docker image    |
| TypeScript strict check                  | Passed                                         |
| ESLint                                   | Passed, zero warnings                          |
| Ruff lint and format                     | Passed                                         |
| Prettier format check                    | Passed                                         |
| Alembic upgrade / downgrade / upgrade    | Passed on isolated PostgreSQL test database    |
| Alembic metadata drift check             | No new upgrade operations detected             |
| OpenAPI contract snapshot                | Matches the application schema                 |
| Docker Compose configuration             | Valid                                          |
| Docker image builds and startup          | API, web, PostgreSQL start successfully        |
| Database-backed health                   | 200, connected                                 |
| Seed idempotency                         | Two runs produced exactly three demo calendars |
| git diff --check                         | Passed                                         |

The browser flow covers Dashboard -> Technicians -> Add -> detail -> edit -> assign calendar -> reload and verify persistence -> type the exact deletion phrase -> wait 10 real seconds -> permanently delete -> verify API 404 and card removal. Temporary smoke records are cleaned up.

Backend tests independently query PostgreSQL after permanent deletion to confirm that the technician row, calendar assignments, Telegram binding, and GPS binding have been removed. Calendar records survive. They also cover validation, unknown/immutable fields, no fabricated bindings on creation, transaction rollback, assignment history, calendar removal safeguards, nullable Telegram uniqueness, partial assignment uniqueness under concurrent requests, and health.

Visual review used temporary fictional profiles at desktop 1440px, tablet 820px, and mobile 390px. The browser reported no page errors and no horizontal overflow at 390px. Supporting text contrast was strengthened after review. Review images are local ignored artifacts under `.local/screenshots/`.

## Scope and limitations

- Local Stage 0 only: no authentication, authorization, audit trail, or field encryption. Use fictional data until operational safeguards are implemented.
- No real external provider adapters or calls; no fake revenue, jobs, locations, or provider connections.
- PostgreSQL development data persists in the named volume. The disposable test database is separate and protected by name/host checks.
- ESLint is pinned to 9.39.5 because the React lint plugin bundled with the current Next.js config is incompatible with ESLint 10's removed rule APIs. This pin affects development tooling only.
- Photo URLs are optional browser-loaded external images; automated tests use initials and block external browser requests.
- Lists are unpaginated for the initial small local workspace.

`C:\HVAC_TECH_CODEX` was neither read nor modified. Nothing was copied from the old HVAC repository. No Git push was performed.
