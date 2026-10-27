# 08 — Gate 1 report (Phase 1)

Date: 2026-10-27. Branch `feature/v2-phase1-foundation`. Evidence labels: TESTED LIVE (real `spiec_verti`, 10.151.28.2, PG 13.6), TESTED ISOLATED, MOCKED, BLOCKED, UNTESTED.

## Verdict: NOT PASSED — 4 acceptance items open (see "Open"). Do not start Phase 2 without owner decision.

## Acceptance vs evidence
| Gate 1 criterion | Status | Evidence |
|---|---|---|
| Unauthorized requests fail server-side | PASS · TESTED LIVE | OpenAPI-driven matrix: every non-public route → 401 without a session |
| Cross-workspace requests fail | PASS · TESTED LIVE | Every `{workspace_id}` route → 404 for a non-member; viewer/author → 403 on admin routes; denials written to `audit_event` |
| Forged browser approval rejected | PARTIAL · TESTED LIVE at DB level only | Triggers reject author self-approval, checksum mismatch, wrong state, edits of approved revisions. The HTTP approval route does not exist yet (Phase 4), so API-level forgery is untested |
| Migrations tested | PASS · TESTED LIVE | up → down (0002) → up, tests re-run green |
| Backup/restore tested | **BLOCKED** | no `pg_dump`/`psql` on the machine |
| Rollback to old pilot | PASS (by construction) | tag `baseline-pilot`; pilot files unchanged except two include lines in `index.html`; pilot launcher untouched. Not re-run end to end |
| Sessions, CSRF, secure cookies | PASS · TESTED LIVE | HttpOnly/Secure/SameSite=Strict; CSRF + Origin enforced on every unsafe method; logout and password change revoke sessions; lockout after 5 failures |
| Audit trail | PASS · TESTED LIVE | append-only via trigger (UPDATE/DELETE/TRUNCATE rejected); UI shows events |
| Secret handling | PASS · TESTED LIVE | canary password absent from responses and logs; `.env` git-ignored; passwords argon2id; only `secret_ref` names stored |
| Dependency health | PASS · TESTED LIVE | `/readyz` pings PG and Redis; 503 on failure (unit-tested path: PG down not simulated → **not tested**) |
| Docker Compose services | UNTESTED | `compose.yml`, `backend/Dockerfile.v2` written; no Docker available |
| Separate DB roles/schemas | PASS · TESTED LIVE | `uetl_migrator` (DDL) vs `uetl_app` (DML, DDL denied); `postgres` used once for bootstrap |
| Light Luxury UI (login/shell/workspace/users) | PASS (scope-adjusted) · manual Chrome check | Owner changed scope to "extend existing UI"; verified login, workspaces, members, audit, users, account pages. No axe/keyboard audit run |

Tests: `tests/v2` — 26 passed (DB guards 6, API 20). Legacy pilot test suite (`npm test`) NOT re-run in this phase.

## Defects found and fixed this phase
`inet` rejects non-IP client host; psycopg2 UUID adapter; UUID in log JSON; tables missing pilot `class="table"`; Users menu built too late; first workspace not selected; **transaction committed after the HTTP response** (FastAPI dependency scope) — fixed with function scope, guarded by a structural test only.

## Open
1. Backup/restore (install PostgreSQL client tools, then test round-trip in a throwaway schema).
2. Docker compose never run.
3. API-level forged-approval test (needs Phase 4 route) — DB-level only for now.
4. `/readyz` failure path, axe/keyboard checks, and the legacy `npm test` not run.

## Known risks carried forward
- Shared PG server: default `PUBLIC CONNECT` on other DBs lets `uetl_*` roles connect to them (DBA action).
- Superuser password and the bootstrap `admin` password were exposed in chat → rotate both.
- CSP keeps `unsafe-inline` for the legacy shell (audit R06 open for legacy screens).
- A locked account answers 429 while an unknown user answers 401: reveals that a locked username exists.
- Redis (WSL) does not auto-start.
- Pre-existing pilot console error `datasets is not defined` on first paint.

## Rollback
`git checkout baseline-pilot`; run `Start U-ETL Test.bat`. Optional DB cleanup: `python -I backend/migrate.py down --yes` twice (drops v2 tables; they hold only the `admin` user and workspace `main` today).

## STOP — awaiting owner review of Gate 1.
