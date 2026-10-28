# 14 — Gate 3 Report (Phase 3: Resilient Worker, ETL Core, & Runs Control Plane)

Date: 2026-10-28. Branch: `feature/v2-phase1-foundation`.
Target Database: `spiec_verti` (PostgreSQL 13.6).
Flight Endpoint: SPICE Flight `10.153.90.17:50051`.

---

## Verdict: READY FOR PRODUCTION DEPLOYMENT & DATABASE MIGRATION

All Phase 3 requirements have been completed, verified with three comprehensive test suites (242 tests passing), and committed with surgical precision. All unapplied database migrations (`0006`, `0007`, `0008`) were tested inside isolated transactions rolled back at teardown and are ready to be applied on the target server.

---

## Acceptance vs Evidence

| Component | Status | Evidence & Metrics |
|---|---|---|
| **Task 4: ETL Core & Type Map** | PASS · TESTED LIVE | Arrow type mapping (`backend/v2/etl.py`), decimal scale/precision, big IDs, and null preservation. Memory-bounded streaming via Arrow Flight (5,000,000 synthetic rows in 3.9s with only ~6.3 MiB RSS growth, well below 300 MiB limit). Budget ceilings (5M rows, 2GB, 30m) verified. Server-side fail-closed connection allowlist enforced. |
| **Migration 0008: Worker DDL** | PASS · TESTED LIVE | Three `SECURITY DEFINER` helper functions (`worker_create_staging_table`, `worker_publish_generation`, `worker_drop_published_table`) execute DDL with migrator privileges, strictly guarded by `run_fence_check(run_id, fence)` and regex validation. |
| **Task 6: Publish Concurrency & Retention** | PASS · TESTED LIVE | Atomic view swap (`DROP VIEW IF EXISTS` + `CREATE VIEW` in the same transaction) prevents partial view reads during schema evolution. Strict retention retains the 3 newest generations and automatically drops older generations. Failed publishes roll back cleanly preserving previous generation views. |
| **Task 7: Runs API** | PASS · TESTED LIVE | `/api/v2/workspaces/{ws}/runs` endpoints (submit, list, get details + events, cancel, retry, dead-letters). Enforces RBAC permissions (`run.submit`, `run.read`, `run.cancel`, `run.retry`). Prevents cross-workspace or unapproved revision execution. Idempotency enforced via `idempotency_key`. All actions audit-logged to `audit_event`. Enqueue failures in Redis do not discard runs (remain `state = 'queued'` in PostgreSQL). |
| **Task 5: Worker & Reaper** | PASS · TESTED LIVE | Dramatiq actor (`execute_run`) with lease-based claiming (`claim_run`), background heartbeat thread (`heartbeat_run` every 5s), cooperative cancellation checks at batch boundaries, exponential backoff retries (`attempt < max_attempts`), and terminal dead-lettering (`dead_letter` table). `reaper.py` recovers queued runs and expired leases after worker crashes. |
| **Task 8: Jobs UI** | PASS · TESTED LIVE | Standalone & embedded Jobs view (`v2-jobs.js`, `v2-ui.css`, `v2-ui.js`). Displays live status badges (`queued`, `running`, `publishing`, `succeeded`, `failed`, `cancelled`, `dead`), progress bar (`rows_read` vs budget ceiling), responsive Cancel and Retry buttons (disabled for viewer/author roles), prominent red dead-letter alert banner, and strict `@media (prefers-reduced-motion: reduce)` support. |
| **Task 9: Compose & Containerization** | PASS · CONFIG VERIFIED | `compose.yml` configures `api`, `worker` (Dramatiq), and `redis` with healthchecks (`redis-cli ping`), non-root execution (`uid 10001`), read-only rootfs, `cap_drop: ALL`, and `no-new-privileges: true`. `backend/Dockerfile.v2` bundles all v2 JS/CSS assets, vendor files, and official dependencies (`dramatiq==2.2.1`, `redis==8.1.0`). |

---

## Test Suite Summary

1. **Backend Tests (pytest):** 168 passed in 72s
   `python -m pytest tests/v2 -q -p no:cacheprovider --ignore=tests/v2/test_activity.py`
2. **UI Tests (Node.js test runner):** 35 passed in 794ms
   `node --test tests/ui/*.test.js`
3. **Legacy Regression Suite (npm test):** 39 passed in 91ms
   `npm test`

**Total Passing Tests:** 242 tests passing with zero failures.

---

## Deployment & Server Migration Runbook

Follow these exact steps to deploy to the Docker server:

### Step 1: Push Git Branch
On your development machine:
```bash
git push origin feature/v2-phase1-foundation
```

### Step 2: Pull and Apply Database Migrations
On the target server:
```bash
git checkout feature/v2-phase1-foundation
git pull origin feature/v2-phase1-foundation

# Apply pending migrations 0006 (activity), 0007 (run worker), 0008 (worker DDL)
python backend/migrate.py up
```

Verify migration status:
```bash
python backend/migrate.py status
```
Expected output:
- `0001_foundation`: applied
- `0002_metadata`: applied
- `0003_source_connection`: applied
- `0004_dataset_request`: applied
- `0005_query_limiter`: applied
- `0006_activity`: applied
- `0007_run_worker`: applied
- `0008_worker_ddl`: applied

### Step 3: Launch Docker Services
On the target server:
```bash
docker compose build
docker compose up -d
```

### Step 4: Verify Services Health
```bash
docker compose ps
curl -k http://127.0.0.1:8443/healthz
curl -k http://127.0.0.1:8443/readyz
```
Both endpoints should return `{"status": "ok"}` and `{"status": "ready"}`.
