# Phase 3 — Redis queue and independent ETL worker: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox syntax. **Writer = Codex; Claude = read-only reviewer who runs the suite independently** (decision-log 2026-10-28). One writer in the repo at a time; commit only your own files (never `git add -A`).

**Goal:** Approved immutable pipeline revision -> Redis (Dramatiq) -> independent worker -> bounded SPICE read -> run-scoped PostgreSQL staging -> quality checks -> atomic generation-swap publish, observable on Jobs and Source activity pages.

**Architecture:** PostgreSQL is the only source of truth (runs, attempts, leases, generations, watermarks). Redis/Dramatiq only wakes workers: payload = `{run_id}` and nothing else. A worker claims a run by a fenced PG lease (token increments on every claim); every write to staging/metadata carries the token and fails if it is stale. Publish = new generation table + view swap in one transaction.

**Tech Stack:** Python 3.12, FastAPI (existing), Dramatiq + Redis 7 (Compose), psycopg2, pyarrow 25.0.1 Flight (existing `spice.run_bounded`), vanilla-JS UI with vendored TanStack (existing).

**Spec:** `U-ETL-V2-IMPLEMENTATION-PROMPT-LIGHT-LUXURY.md` §Phase 3 + Gate 3; `docs/v2/decision-log.md` entries 2026-10-28 (rounds 1 and 2).

## Global Constraints
- Owner decisions (verbatim): limiter waits up to **2 s** then 429 + `Retry-After`; **Dramatiq**; **Docker Compose api+worker+redis**; test data = **synthetic SPICE (`generate_series`) + `_mock` tables only, no SCADA/real tables**; publish = **table per generation + view to latest**; keep **3** generations; budget **5 M rows / 2 GB staging / 30 min** per run; retry/cancel = **operator/admin only**, all audited; dead-letter alert = **Jobs page banner only**, nothing sent outside.
- Queue payload never contains data, SQL, credentials. Worker reads the revision and connection server-side. Secrets only from git-ignored `.env`.
- No source DB credentials in U-ETL. Reads only through SPICE Flight with existing allowlist, typed literals, `assert_select_shape`, limiter.
- Numbers reach the browser as strings. No `eval`, no innerHTML with data (existing rules).
- Full load only. No incremental/CDC. Legacy ETL path stays routed until Task 9 is approved by the owner.
- Evidence labels: TESTED LIVE / ISOLATED / MOCKED / BLOCKED. Tests never touch real `uetl_published`/`uetl_meta` rows of the `main` workspace; use the isolated fixtures pattern of `tests/v2/test_api.py` and the throwaway schema approach of `scripts/loadtest_preview.py`. No stray processes or scratch folders left behind (previous round left `live_fixture.py` running).
- Python tests: `python -m pytest tests/v2 -q -p no:cacheprovider`; UI: `node --test tests/ui/*.test.js`; legacy `npm test`.

## Review Focus (not covered by obvious tests)
1. Worker killed between `COMMIT` of staging and publish swap -> restart must publish exactly once, never twice, never half.
2. Redis flushed/lost while PG says `queued` -> a reaper re-enqueues; duplicate delivery of the same `run_id` is a no-op.
3. Two workers claim the same run after a lease expiry -> the old one's late writes must be rejected by the fence token.
4. `generate_series` of 5 M+ rows -> memory stays bounded (batch streaming), run stops at the budget with a clear reason.
5. Cancel arriving mid-batch, mid-publish, and after publish -> published data and run status always agree.
6. Decimal(38,x), BIGINT > 2^53, NULL in every column type survive staging -> publish -> API as exact strings.
7. Jobs page with 10 k runs and a 300-col dataset stays responsive (virtualized table already exists).

## File Structure
- `backend/migrations/0006_runs.up.sql/.down.sql` — `pipeline_revision`(minimal), `run`, `run_attempt`, `run_event`, `dataset_generation`, `published_pointer`, `dead_letter`; DB triggers for immutability and fence checks.
- `backend/v2/runs.py` — API router: submit, list, get, cancel, retry, events (SSE-free polling), dead-letter list.
- `backend/v2/worker.py` — Dramatiq actor `execute_run(run_id)`, claim/heartbeat/fence, orchestration.
- `backend/v2/etl.py` — pure pipeline stages: `extract_batches`, `stage_batch`, `quality_checks`, `publish_generation` (no queue knowledge; unit-testable).
- `backend/v2/reaper.py` — re-enqueue stuck `queued`, expire dead leases, retention (drop generations > 3).
- `backend/v2/activity.py` — Source activity API (queue wait, 429, timeouts, reads) from new `source_event` table (in 0006).
- `backend/Dockerfile.v2` (modify: worker command), `compose.yml` (add `worker`, healthchecks).
- `v2-ui.js` / new `v2-jobs.js` — Jobs/Monitoring page and Source activity page.
- Tests: `tests/v2/test_runs_api.py`, `test_worker_recovery.py`, `test_etl_types.py`, `test_publish_atomic.py`, `test_activity.py`, UI `tests/ui/jobs.test.js`.

---

### Task 0: Close the two leftovers + limiter wait
**Files:** Modify `backend/v2/spice.py` (literal formatter), `backend/v2/limiter.py`, `backend/v2/sources.py`, `v2-forms.js`; Test `tests/v2/test_sql_guard.py`, `tests/v2/test_limiter.py`, `tests/ui/forms.test.js`, `tests/v2/test_sources.py`.
**Interfaces:** Produces `limiter.acquire(pool, ttl_s=30, wait_s=2.0)` — polls PG (50-100 ms jittered), raises `Busy(retry_after)` after `wait_s`.
- [ ] Failing tests: string filter value containing `\` -> 422 (server) and form validation error (UI); fuzz case with `\` added to the 2000-case guard; limiter test: with 2 leases held, third caller waits ~2 s then `Busy`; with a lease released at 0.5 s the third caller succeeds.
- [ ] Implement: reject `\` in string literals in `spice` formatter and `v2-forms.js`; add `wait_s` loop to `acquire` (default from `UETL_LIMITER_WAIT_S`, 2.0).
- [ ] Live-SPICE tests (`test_exact_numbers_survive`, `test_errors_never_leak_source_text`) must not fail when leases are busy: wrap with a helper `pytest` fixture that retries on `Busy` up to 10 s; document why.
- [ ] Run all three suites; expected: all pass. Commit `fix: reject backslash in filters, limiter waits 2 s, live tests tolerate busy`.

### Task 1: Source activity log (the owner's "Log page")
**Files:** Create `backend/migrations/0006_*` part A (`source_event`), `backend/v2/activity.py`; Modify `limiter.py`, `sources.py` (emit events); UI page in `v2-jobs.js`; Test `tests/v2/test_activity.py`.
**Interfaces:** `activity.record(kind: Literal["queue_wait","busy_429","timeout","read_ok","read_error"], *, workspace_id, connection_id, dataset, user_id, waited_ms, rows, bytes)`; `GET /api/v2/workspaces/{ws}/source-activity?since=&kind=&dataset=` (permission `audit.read`... use `connection.read`), paged, max 500.
- [ ] Failing tests: a 429 produces one `busy_429` event; waited_ms recorded; response never contains raw SPICE text, SQL, tokens; workspace isolation (other workspace gets 404); retention: events older than 30 days pruned by reaper.
- [ ] Implement; events written best-effort (a logging failure must not fail the request); append-only trigger.
- [ ] UI: table with filters (time range, dataset, kind), badge colors, refresh control, empty state. Test with fixtures.
- [ ] Commit.

### Task 2: Dramatiq spike (1 day, throwaway branch, decides the framework)
**Files:** `scripts/spike_queue.py` (labelled spike), `docs/v2/12-queue-spike-results.md`.
- [ ] Compose Redis only (`docker compose up redis`); Dramatiq with `max_retries=0` in the broker (retries are PG-driven), `acks_late=True`.
- [ ] Experiments, each with a recorded result: (a) kill -9 worker mid-job -> message redelivered?; (b) duplicate delivery -> PG fence makes second a no-op; (c) Redis restart with AOF -> messages kept?; (d) Redis flushed -> reaper re-enqueues from PG; (e) visibility timeout vs a 5-minute job (heartbeat extends?); (f) memory of a worker streaming 5 M synthetic rows.
- [ ] Decision gate: if (a)-(d) cannot be made correct with PG as authority, write the result and STOP; owner chooses between "custom Redis list + PG lease" and another library. Otherwise record "Dramatiq confirmed". Commit doc only (spike code removed or kept clearly labelled).

### Task 3: Run schema and DB guards (migration 0006 part B)
**Files:** `backend/migrations/0006_runs.*`; Test `tests/v2/test_db_guards.py` additions.
**Interfaces (tables):**
- `pipeline_revision(id, workspace_id, connection_id, name, spec jsonb, spec_sha256, approved_at, approved_by, created_by)` — **Phase 3 minimal spec** `{dataset, columns[], filters[], target_name}`; immutable once `approved_at` set (trigger); Phase 4 extends `spec`. Phase 3 test fixtures insert approved revisions directly (labelled).
- `run(id, workspace_id, revision_id, idempotency_key unique per (workspace, revision), status in queued|running|publishing|succeeded|failed|cancelled|dead, cancel_requested, fence bigint, lease_owner, lease_until, heartbeat_at, attempt, max_attempts, rows_read, bytes_staged, error_code, created_by, ...)`
- `run_attempt`, `run_event(append-only, safe messages only)`, `dataset_generation(id, workspace_id, target_name, generation int, table_name, run_id, row_count, created_at, dropped_at)`, `published_pointer(workspace_id, target_name, generation_id, swapped_at)`, `dead_letter(run_id, reason, at)`.
- [ ] Failing guard tests: approved revision spec cannot change; terminal run status cannot move; a write with a stale fence is rejected (function `run_fence_check(run_id, fence)` used by every worker write); `uetl_app` cannot DDL; worker role limited to its schema.
- [ ] Implement migration (up/down, applied by `uetl_migrator` — **ask the owner before applying to the shared DB**; tests use the isolated pattern). Commit.

### Task 4: ETL core (pure functions)
**Files:** `backend/v2/etl.py`; Test `tests/v2/test_etl_types.py`.
**Interfaces:** `extract_batches(conn, spec, *, budget) -> Iterator[pa.RecordBatch]` (uses `spice` Flight + limiter lease per read, honours cancel callback); `stage_batch(cur, run_id, fence, table, batch)` (COPY into run-scoped table `uetl_staging.r_<run>_<n>`); `quality_checks(cur, table, spec) -> list[Finding]` (row count > 0 unless allowed, not-null columns, duplicate key); `publish_generation(cur, run_id, fence) -> int`.
- [ ] Failing tests with synthetic SPICE data: Decimal128(38,10), int64 max, uint64, NULL per type, timestamps with tz, out-of-range dates (ISO text as in the preview fix) round-trip exactly; 5 M rows via `generate_series` finishes with RSS growth < 300 MB (measure, record) and stops at budget with `error_code=budget_rows`; 2 GB/30 min budgets enforced by fakes.
- [ ] Implement; type map documented in `docs/v2/13-etl-type-map.md`. Commit.

### Task 5: Worker, lease fencing, retry, cancel
**Files:** `backend/v2/worker.py`, `reaper.py`; Test `tests/v2/test_worker_recovery.py`.
**Interfaces:** `execute_run(run_id: str)` Dramatiq actor; `claim(run_id) -> int fence | None`; heartbeat every 5 s extends `lease_until` (30 s); retry = exponential backoff 5 s*2^n with jitter, `max_attempts=3`, then `dead` + `dead_letter` row; cancel = cooperative at batch boundary and before swap.
- [ ] Failure-injection tests (kill points as env-controlled hooks, test-only): after claim; mid-extract; after staging commit before checks; after checks before swap; after swap before status update; after status update. Expected for each: restart converges to exactly one generation, status matches data, no orphan staging table beyond TTL cleanup.
- [ ] Tests: duplicate delivery no-op; stale-fence write rejected; reaper re-enqueues `queued` older than 60 s; Redis-flush scenario; backoff schedule; dead-letter after 3 attempts.
- [ ] Implement; commit.

### Task 6: Publish (generation swap)
**Files:** `etl.publish_generation`; Test `tests/v2/test_publish_atomic.py`.
- [ ] Failing tests: reader loop querying the view during publish sees only old-or-new full row sets (never mixed, never empty); rollback of swap leaves old generation; retention keeps newest 3, drops older after commit; view name stable; target name whitelist `^[a-z][a-z0-9_]{2,60}$`; roles: published schema SELECT for readers only.
- [ ] Implement in one transaction: `CREATE TABLE ... AS`/`ALTER TABLE ... SET SCHEMA` from staging into `uetl_published.<target>_g<N>`, `CREATE OR REPLACE VIEW uetl_published.<target>`, pointer update, run status. Commit.

### Task 7: Runs API
**Files:** `backend/v2/runs.py`, wire in `app.py`; Test `tests/v2/test_runs_api.py`.
**Interfaces:** `POST /runs {revision_id, idempotency_key}` (perm `run.submit`, revision must be approved, enqueues `{run_id}`); `GET /runs`, `GET /runs/{id}` (+ events); `POST /runs/{id}/cancel` (`run.cancel`); `POST /runs/{id}/retry` (`run.retry`, only failed/dead); `GET /dead-letters`.
- [ ] Failing tests: viewer/author get 403 on submit/cancel/retry; unapproved revision 409; cross-workspace 404; same idempotency key returns the same run; audit event for every action incl. denials; enqueue failure leaves run `queued` for the reaper (no 500 lost run).
- [ ] Implement; commit.

### Task 8: Jobs/Monitoring UI (TanStack)
**Files:** `v2-jobs.js`, `v2-ui.css`, route in `v2-main.js`; Test `tests/ui/jobs.test.js`.
- [ ] Uses existing query client (polling every 2 s while any run active, backs off otherwise), virtualized table (`v2-table.js`), form-core for submit/retry confirm; states: queued/running/publishing/succeeded/failed/cancelled/dead; progress bar from `rows_read/bytes_staged` vs budget; subtle progress animation honouring `prefers-reduced-motion`; red dead-letter banner + count (decision); cancel/retry buttons shown only with permission, busy-state double-click guard, answers from old workspace ignored (existing pattern).
- [ ] Tests: renders 10 k runs with bounded DOM cells; keyboard navigation; reduced-motion disables animation; no innerHTML of data. Browser smoke in headless Chrome (record result). Commit.

### Task 9: Compose, docs, Gate 3 evidence, legacy path (needs approval)
**Files:** `compose.yml`, `backend/Dockerfile.v2`, `docs/v2/14-gate-3-report.md`, `docs/v2/runbook-phase3.md`, implementation-log.
- [ ] Add `worker` service (same image, `dramatiq` command, `restart: unless-stopped`, read_only, no caps), Redis healthcheck. **Ask the owner before first `docker compose up` that builds/starts containers; do not publish ports.**
- [ ] Gate 3 evidence run: close browser / `docker compose restart api` mid-run -> run completes; `docker kill worker` at each boundary -> recovers (Task 5 tests TESTED ISOLATED + one TESTED LIVE on compose); memory soak; unauthorized attempts; rollback procedure (stop worker, drop generations, `down` migration 0006).
- [ ] Legacy ETL removal: write the parity table only; **removal itself is BLOCKED until the owner approves** (plan step 6). Report + STOP for review.

## Self-review notes
- Spec coverage: tasks 1-6 of Phase 3 map to Tasks 2,4,5,6,7,8,9; idempotency/fencing/heartbeat/budgets in 3,5; atomic publish in 6; Gate 3 bullets in 5,9.
- Phase 3 has no pipeline authoring yet; `pipeline_revision` is minimal and extended in Phase 4 (my call, flagged for owner).
- Other calls of mine (owner may override): `max_attempts=3` with 5 s exponential backoff; heartbeat 5 s / lease 30 s; source events kept 30 days; Source activity needs `connection.read`; polling (not SSE) for live status.
