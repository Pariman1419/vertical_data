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

## 2026-10-27 — UI verified in Chrome (TESTED LIVE, manual)
- Bootstrap superadmin `admin` created via `python -m backend.v2.cli create-superadmin` (random password handed to the owner; no change-password feature yet — Phase 1 follow-up).
- Verified at `http://127.0.0.1:8443/`: login, session restore after reload, workspace create (audited), workspace selector, Members, Audit trail (shows `workspace.create` allow), Users, Sign out button present.
- UI bugs found by looking at it and fixed: tables lacked the pilot's `class="table"`; the Users menu was added after the pilot built the nav; the first created workspace was shown in the selector but `V2.ws` stayed null.
- Observation: the first screenshot after a navigation timed out twice (CDP, 30 s) then worked; server login took 230 ms. Not reproduced as a page hang; treat as browser-tool timing, unconfirmed.
- Data left in `spiec_verti`: user `admin`, workspace `main` (+1 membership, audit rows). Tests leave nothing.

## 2026-10-27 — tooling + Docker verification
- Installed (owner-requested): PostgreSQL 17.11 command-line tools only (no server/service), Docker Desktop 4.97.0 (Engine 29.9.2, Compose v5.6.1).
- `pg_dump` 17.11 against PG 13.6 as `uetl_migrator`, `--schema-only -n uetl_meta`: OK, 19 tables, no secrets in output. [TESTED LIVE, read-only]
- `docker compose build/up`: api healthy; `/healthz` 200; `/readyz` 200; Redis stopped -> 503 (healthz 200) -> restarted -> 200. Hardening verified via `docker inspect`/exec. [TESTED LIVE]
- Fixes found by running it: compose now overrides `UETL_REDIS_URL` (the `.env` value pointed at host 127.0.0.1); added `.dockerignore`.
- Not done: restore round-trip (needs a throwaway schema; awaiting approval).

## 2026-10-27 — Phase 2 part 1 (owner: "use SPICE together with Postgres as planned; complete the plan")
- Owner decision recorded: continue past Gate 1 with its open items (backup/restore round-trip, API-level forged approval) carried forward.
- Migration 0003 applied: `connection_allowed_object` (per-connection object allowlist, D13) + DB trigger forbidding a connection from using another workspace's `secret_ref`. [TESTED LIVE]
- `backend/v2/netpolicy.py`: connection URLs must be on `UETL_SPICE_ALLOWED_HOSTS` (host:port) and may not resolve to loopback/link-local/metadata/multicast/unspecified even if allow-listed; empty allowlist = deny all; `resolve_pinned()` returns the IP to connect to (rebinding defence). Bug found by its own test: default resolver was bound at import and could not be substituted; now late-bound.
- `backend/v2/connections.py`: secret refs (names only, env-var style), connection CRUD, object allowlist; workspace-scoped, audited, no secret values in any response. Changing `base_url` resets status/capabilities.
- Tests: `tests/v2/test_connections.py` (9) -> total **34 passed** [TESTED LIVE (DB); no SPICE contacted].
- NOT done / BLOCKED (D2): no SPICE host/port/credentials known (`D:\CIM Project\spice` no longer exists on this machine); no read-only probe has been run; therefore no SPICE client, catalog refresh, test-connection, capabilities or preview endpoints yet. They must not be coded against an unprobed wire format.

## 2026-10-27 — SPICE probe (D2) [TESTED LIVE, read-only]
- Target 10.153.90.17 :8091/:50051 (owner-supplied). Full list of statements, results and the NOT-tested list in `09-spice-probe-results.md`.
- Headline: no auth; REST has no streaming/row cap (2 M rows = 34.9 MB); Flight streams in 8,192-row batches and can be stopped early (0.03 s); decimal128 exact on Flight, exact text on REST; binds work on REST only; dialect DataFusion; errors leak internal names.
- Not tested: writes/DDL rejection, server-side cancel, TLS, behaviour on large real tables.
