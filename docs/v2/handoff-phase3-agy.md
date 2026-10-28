# Phase 3 handoff — implementer: agy; reviewer: Claude (read-only)

Date: 2026-10-28. Branch `feature/v2-phase1-foundation`. Read first: `docs/superpowers/plans/2026-10-28-phase3-queue-and-worker.md`, `docs/v2/decision-log.md` (2026-10-28 entries), `docs/v2/implementation-log.md`, `docs/v2/12b-queue-spike-results.md`, `docs/v2/13-etl-type-map.md`.

## Rules (unchanged, from the owner)
- One writer in the repo at a time. Commit only your own files (never `git add -A`). Leave no processes, containers, or scratch folders behind.
- Secrets only in git-ignored `.env`; never print or commit them. No source-DB credentials in U-ETL; SPICE is the only source gateway.
- Ask the owner BEFORE: applying migrations (0006, 0007, later 0008) to the shared PostgreSQL; `docker compose up`; installing packages; downloading files; granting DB privileges; removing the legacy ETL path. Tests must stay isolated / rolled back.
- Test data: synthetic SPICE (`generate_series`) and `_mock` tables only. No SCADA/real tables.
- Label evidence TESTED LIVE / ISOLATED / MOCKED / BLOCKED. After each task: run the 3 suites, commit, stop for review.
- Suites: `python -m pytest tests/v2 -q -p no:cacheprovider` · `node --test tests/ui/*.test.js` · `npm test`.

## Done (commits)
| Task | Commit | State |
|---|---|---|
| 0 leftovers, limiter waits 2 s | 64b2a15 | reviewed OK |
| 1 Source activity (migration 0006) | 550f3da | reviewed OK; 15 migration tests need the Docker fixture (owner approval unconfirmed) |
| 2 Dramatiq spike | 888057c | reviewed OK; "Dramatiq confirmed" (PG16 + WSL Redis, isolated) |
| 3 Run schema (migration 0007) | a72fb39 | reviewed OK; tests roll back; not applied to shared DB |
| 4 ETL core `backend/v2/etl.py` | 363ec11 | **review: NOT passed, fix list below** |

Baseline: Python 148 pass + 15 errors (Docker-gated), UI 31, legacy 39.

## Task 4 fixes required first (Claude review)
1. `publish_generation`: `CREATE OR REPLACE VIEW` fails when column names/order/types change between generations. Use `DROP VIEW IF EXISTS` + `CREATE VIEW` in the same transaction. Test: generation 2 with an added / retyped column publishes.
2. `extract_batches`: never pass `spec["sql"]` straight to Flight; route through `spice.assert_select_shape`. No hand-built column quoting; use `spice.build_select` with escaping. Enforce the dataset allowlist like `sources.py` preview. Tests: injection via `"`, `;`, DML in columns/sql is rejected before reaching SPICE.
3. `limiter.lease` TTL is 30 s but an extract can run up to 30 min: renew the lease while reading (or the cap of 2 is violated). Test: slot still counted after the TTL.
4. `uetl_app` cannot CREATE in `uetl_staging` / `uetl_published` (verified: CREATE=False) but `ensure_staging_table`, `ALTER TABLE ... SET SCHEMA`, `CREATE VIEW` need it. Do NOT grant privileges. Proposed: migration `0008` with `SECURITY DEFINER` functions that perform only whitelisted DDL (names matched against `^[a-z][a-z0-9_]{0,62}$`). **Owner has not yet confirmed this approach: ask before writing.**

## Remaining plan (order recommended by Claude)
| Order | Task | Output |
|---|---|---|
| 1 | Task 4 fixes (above) | tests for each; commit |
| 2 | Task 6 publish depth | readers see only old-or-new full set during swap; swap rollback keeps old; retention 3; schema change between generations |
| 3 | Task 7 Runs API `backend/v2/runs.py` | `POST /runs {revision_id, idempotency_key}`, list/get, cancel, retry, dead-letters; operator/admin only (`run.submit/cancel/retry`); revision must be approved; same key returns same run; audit every action incl. denials; enqueue failure leaves run `queued` for the reaper |
| 4 | Task 5 worker `backend/v2/worker.py`, `reaper.py` | Dramatiq actor `execute_run(run_id)` (payload = run_id only), `claim_run`/`heartbeat_run`/`run_fence_check` from 0007, retry backoff 5 s·2^n, max 3 then `dead` + `dead_letter`, cooperative cancel, reaper re-enqueues stuck `queued` (>60 s), expires leases; failure-injection tests at every commit boundary. **Needs owner approval to add `dramatiq==2.2.1`, `redis==8.1.0` as app dependencies.** Spike lessons: prefetch=1; Redis redelivery can arrive before PG lease expiry (becomes a no-op) so the reaper is mandatory; broker heartbeat and PG heartbeat are both required. |
| 5 | Task 8 Jobs UI `v2-jobs.js` | polling 2 s while active; virtualized table; progress vs budget; red dead-letter banner + count; cancel/retry only with permission; honour `prefers-reduced-motion`; no innerHTML of data; UI tests + headless Chrome smoke |
| 6 | Task 9 | `worker` service in `compose.yml`; Gate 3 evidence (restart API / kill worker at each boundary); `docs/v2/14-gate-3-report.md`; legacy ETL removal only after owner approval |

## Decided by the owner (do not re-ask)
Limiter waits 2 s then 429 + `Retry-After` · Dramatiq · Docker Compose api+worker+redis · publish = table per generation + view, keep 3 · budget 5 M rows / 2 GB staging / 30 min · retry/cancel operator/admin only, audited · dead-letter alert only on the Jobs page · Source activity page separate from Audit.

## Still waiting on the owner
Docker fixture for Task 1 migration tests · `dramatiq`/`redis` as dependencies · the `.deb` download made in Task 2 · applying migrations 0006/0007 to the shared DB · Docker `compose up` · the 0008 `SECURITY DEFINER` approach · removing the legacy ETL path.
