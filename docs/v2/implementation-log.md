# Implementation log

## 2026-10-27 — Phase 1 start
- `git tag baseline-pilot`; branch `feature/v2-phase1-foundation`.
- Env: Python 3.12.10, Node 24, fastapi/sqlalchemy/psycopg2/pytest present; no docker/psql/pg_dump. WSL Ubuntu-24.04 present.
- Redis 7.0.15 installed in WSL (apt), config `/etc/redis/redis-uetl.conf`, loopback + requirepass, `PING` ok, unauth from Windows => NOAUTH. [TESTED LIVE]
- Read-only probe of `spiec_verti`: empty, `public` only. [TESTED LIVE]
- `scripts/db/bootstrap_roles.py` run once as `postgres`: created `uetl_migrator`, `uetl_app`, schemas `uetl_meta/uetl_staging/uetl_published`. Verified: app role cannot CREATE (InsufficientPrivilege); neither role is superuser/createrole/createdb. [TESTED LIVE]
- Mistake caught: `.env.example` was overwritten by mistake and restored from git before any commit.

## 2026-10-27 — Phase 1: DB, API, UI layer
- Migrations 0001/0002 applied as `uetl_migrator` (`backend/migrate.py`). Rollback exercised: `down --yes` (0002) then `up`; tests re-passed. [TESTED LIVE]
- `argon2-cffi` installed (owner-approved). 
- New API `backend/v2/` (FastAPI): auth (argon2id, opaque session stored as sha256, idle 30 min / absolute 8 h, lockout after 5 failures for 15 min), CSRF + same-origin on unsafe methods, workspace membership (404 for non-members) then permission (403), audit of denials, correlation IDs, JSON logs, sanitized errors, `/healthz`, `/readyz` (PG + Redis ping; returned `ready` live).
- Tests `tests/v2/test_db_guards.py` (6) + `tests/v2/test_api.py` (16) = **22 passed** against live `spiec_verti`, each test in one rolled-back transaction. [TESTED LIVE; HTTP layer in-process via TestClient]. Includes OpenAPI-driven matrices: every route 401 unauthenticated; every workspace route 404 cross-workspace; viewer/author 403 on admin routes.
- Bugs found by tests and fixed: `inet` column rejected non-IP client host; psycopg2 needed `register_uuid()`; log line serialised a UUID.
- UI: `v2-ui.js` + `v2-ui.css` wrap `layout/page/navPage` of the pilot UI (pilot files untouched except two include lines in `index.html`). Login screen verified in Chrome at `http://127.0.0.1:8443/`. Logged-in screens NOT yet verified in a browser (no account exists; see below).
- Pre-existing, not ours: `sync-ui.js:33` calls `render()` before `prototype.js` is loaded -> console `ReferenceError: datasets is not defined` on first paint; UI recovers.
- Legacy Oracle `/api/*` routes are NOT served by the v2 server (D12: direct Oracle off by default). The pilot still runs through `Start U-ETL Test.bat`.
- Known gaps: Gate 1 forged-approval is covered at DB level (triggers) only; the approval HTTP route arrives in Phase 4. Backup/restore BLOCKED (no pg_dump). Docker compose not written/run (no Docker). CSP keeps `unsafe-inline` for the legacy shell (audit R06).
