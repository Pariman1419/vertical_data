# 06 — Migration and rollback

## Module migration matrix
| Old module | Decision | New component | Tests | Rollout / rollback |
|---|---|---|---|---|
| `index.html`, `app.js`, `prototype.js`, `styles*.css` | Retire after parity | React/Vite UI | Reuse flows as e2e scripts | Legacy served at `/legacy` until Gate 4; delete only after owner sign-off |
| `real-source-ui.js` | Retire | typed API client | – | same |
| `dataset-workflow.js` | Retain logic as deterministic candidate baseline (port to TS or keep Python) | Wizard suggestions (non-AI, labelled) | `dataset-workflow.test.cjs` ported | – |
| `demo-sync.js`, `sync-ui.js` | Retire (mock) | – | – | Keep in legacy only |
| `backend/spike/server.py` | Retain as isolated pilot | FastAPI app (new) | `test_spike.py` stays green | Pilot launcher unchanged = rollback path |
| `backend/spike/service.py` (in-API ETL) | Retire from active routing after Gate 3 parity | worker + run service | parity: same table loaded via worker equals pilot output | Feature flag `LEGACY_ETL_PATH` |
| `backend/foundation/oracle_read.py` | Refactor → isolated `legacy_oracle` adapter, default disabled | `adapters/legacy_oracle` | `test_oracle_read.py` | `LEGACY_ORACLE_ENABLED=false` |
| `backend/foundation/read_budget.py` | Refactor | `Budget` in SpiceAdapter | `test_read_budget.py` + bytes | – |
| `backend/foundation/core.py` (Registry) | Reuse patterns only | PG `job_run/attempt` | port lease/fencing tests to PG | – |
| `backend/spike/catalog_store.py` | Refactor concepts (snapshot/head) | `catalog_snapshot` PG | port tests; add stale-loading recovery | – |
| `backend/spike/target_store.py` (SQLite) | Retire for v2 | PG staging/published | precision tests | Pilot SQLite files untouched |
| `backend/contracts.ts` | Supersede | `03-contracts.md` + OpenAPI | contract tests | – |

## Rules
- Nothing in the pilot is deleted or migrated in Phase 0–4. SQLite files are not imported; if wanted, a separate read-only import tool is a later owner decision.
- New work on feature branches in a git repo (**D1**); tag `pilot-baseline` before Phase 1.
- Each phase: DB migrations are forward-only Alembic with tested `downgrade` in isolated env; production never auto-migrates (manual `alembic upgrade` step with backup).
- Backup: `pg_dump -Fc` (registry + published) nightly + before migrations; restore drill documented and run in test env at Gate 1. Redis is non-authoritative (AOF only for convenience).
- Rollback per phase: stop new compose project (`docker compose -p uetl down`, volumes kept), start legacy pilot with its BAT launcher; restore PG dump if a migration must be undone.
- Parity exit criteria for retiring a legacy path: the same fixture table loaded by pilot and by v2 worker yields equal row hashes; owner signs off.
