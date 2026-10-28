# Implementation log

## 2026-10-28 — Load hardening and TanStack UI

- Plan `2026-10-27-load-hardening-and-tanstack-ui.md` reviewed against the code before execution. Migration 0005 up/down/up and PostgreSQL lease races tested; independent short transactions replace the per-process semaphore. Catalog records source kind and learned LIMIT support; previews preserve 429 headers and denial audits and release auth/session locks before source reads.
- Closed generated SELECT grammar, 2000 hostile seeded cases, bounded decimal exponent formatting. Fixed oversized-row admission, shared Flight/retry time budgets and JS-safe integer boundary. A controlled Arrow-date regression covers year zero; the exact live cycletime scalar remains unisolated after the source connection failed.
- Five owner-approved TanStack packages vendored with pinned SHA-512 tarballs, SHA-256 files, licenses and Windows newline protection. Native ESM entry, centralized Store/QueryClient/hash routes, 2-D virtual table, exact numeric sort, column picker, form-core validation, five-filter builder, busy feedback and capabilities display. Static build and the legacy static server include the new dependency tree.
- Chrome headless verified login, Back, one GET per resource, double-submit protection, inert hostile text and bounded DOM cells; controlled 300x1000 fixture used 72 initial / 165 scrolled cells. The mocked busy banner retained Retry-After seconds. Existing pilot bootstrap ReferenceError is recorded, not attributed to new modules.
- Real 10-user/60-second machine_map load: 773 requests, 232 successes, 541 busy replies, zero errors; p50 637.3 ms / p95 1240.2 ms (all statuses). Sampled lease maximum 2; health maximum 71.5 ms; login maximum 1326.7 ms. Fixture objects were removed and the staging schema preserved; no normal metadata or credentials were printed or committed.
- Final independent review found five Important lifecycle/learning/cleanup issues. All were reproduced and fixed in one pass: response identity guards and input reset; in-flight query invalidation; object-change response rejection; TTL fallback preserving source outcomes; and cross-process per-dataset LIMIT learning with revision-safe publication. A batch-boundary regression additionally prevents reading beyond the row cap.
- When source availability recovered, metadata-only diagnosis confirmed two cycletime date32 columns outside Python's date range. Final Chrome preview passed: 477 rows × 286 columns before byte truncation; 72 DOM cells. Controlled 300x1000 scrolling stayed at 165 cells. Final tests: 166 Python across the project, 25 UI, 39 pilot, static build and diff check passed. Review and decisions: `11-load-hardening-review.md`.
- Full observations, evidence labels, deviations and open Gate 2 items: `10-load-test-results.md`. ODBC load and a heavyweight live aggregate were not run; upstream cancellation/RSS and other operational checks remain unverified. Gate 2 is not declared closed.

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

## 2026-10-27 — Phase 2 part 2 (owner approved the SPICE transport proposals with "ตกลง")
- Decisions applied: Flight for data, REST only for health/datasets/DESCRIBE; numbers to the browser as strings when beyond JS-safe range or decimal; `pyarrow==25.0.1` pinned; Flight/REST concurrency 2 (`UETL_SPICE_CONCURRENCY`); preview budgets 1000 rows / 1 MB / 10 s.
- `backend/v2/spice.py`: pinned-IP REST client, bounded Flight reader, typed literal formatter, SpiceError with fixed safe messages (raw text logged only). `backend/v2/sources.py`: `POST .../test` (fixed health + `SELECT 1`), `GET .../capabilities`, `POST .../catalog/refresh`, `GET .../catalog` (allow-listed objects only), `GET .../catalog/all` (admin), `POST .../preview` (allowlist + catalog columns + typed filters; no SQL text accepted; audited incl. denials/errors).
- Config: `UETL_SPICE_ALLOWED_HOSTS=10.153.90.17:8091,10.153.90.17:50051` in git-ignored `.env`.
- Bug found by test: pyarrow raises `ArrowInvalid` (not FlightError) when SPICE rejects SQL; it would have been a 500 leaking text. Now mapped to a safe 502. A test used a float literal and mis-blamed precision: DataFusion parses unquoted decimals as float64 - test now casts from a string.
- UI: "Sources (SPICE)" page in `v2-ui.js` (connections, test, catalog refresh, allowlist picker, preview). [Syntax-checked only; NOT exercised in a browser this round.]
- Tests: `tests/v2/test_sources.py` (10; 8 live against SPICE read-only) -> **44 passed**.
- Still NOT tested: SPICE write/DDL rejection, server-side cancel, TLS, large real tables, secret-canary for token auth (SPICE has none), RSS-flat soak.

## 2026-10-27 — Owner UI test finding: preview rejected for some datasets [TESTED LIVE]
- Owner's preview of some objects returned "The source rejected the request." Reproduced: SPICE pushes `LIMIT n` down to the underlying database; **SQL Server-backed datasets (`alarm`, `tooling_log`, `cim_machine_profile`) fail with "Incorrect syntax near 'n'"**. Subquery-LIMIT and FETCH FIRST are rejected too. Without LIMIT the Flight stream starts at once and `run_bounded` cuts it (0.3–1.5 s for 3 rows).
- Fix: preview retries without LIMIT when the first attempt is `rejected`; row/byte/time budgets still bound the read. Live test added. Residual risk: for such sources the remote query is not row-limited server-side; only the 10 s / 1 MB stream cut applies (server-side cancel remains untested).
- Disclosure: while reproducing, I ran `SELECT * ... LIMIT 3` against all 24 datasets, including the non-`_mock` ones, and printed only table names, column counts and row counts - no row values.
- Test fix: `test_change_password_flow` counted all `password.change` audit rows in the shared DB and broke once the owner changed the real admin password; it now counts the test user's rows only.

## 2026-10-27 — Dataset requests ("add a table to SPICE" from the UI) [TESTED LIVE (DB), MOCKED (catalog), UI not browser-tested]
- Decision (owner): SPICE stays the only gateway; U-ETL does not connect to source databases and takes no DB credentials. Findings from the SPICE host report: datasets live in a read-only-mounted `spicepod.yaml`; reload behaviour unknown; no write API -> U-ETL files a request and renders the entry for the operator.
- Migration 0004 `dataset_request` (+ trigger: only pending -> applied/cancelled, fields immutable; partial unique index on pending names). Down->up tested.
- `backend/v2/dataset_requests.py`: profiles `pg` / `scada` only; remote object and dataset name are whitelist-regex validated before they can reach the rendered YAML; name clash with latest catalog -> 409; workspace-scoped, audited. `catalog/refresh` closes matching pending requests.
- UI: request form + list + copyable entry on the Sources page (syntax-checked only).
- Tests: `tests/v2/test_dataset_requests.py` -> full suite **71 passed**. YAML/SQL injection cases (quotes, newlines, `;`, `: `, extra dots) all rejected.
- Not done: Oracle profiles (need sample from host), reload/restart result (needs the SPICE host test), automatic writer on the host (deferred, SPICE has no auth).

## 2026-10-27 — Gate 2 self-review finding [fixed, TESTED]
- A `secret_ref` accepted any env-style name, and the SPICE client resolved it through `config.get`, so a workspace admin could register `UETL_APP_PASSWORD` (or any process env var) as a "token" and have it sent as a Bearer header to the allow-listed SPICE host. Fix: secret names must match `^SPICE_[A-Z0-9_]{1,55}$` at creation and the client refuses to resolve anything else. Tests added (72 passed).
