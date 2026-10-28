# Phase 3 Task 1 — Source activity

Status: implemented, pending Claude/owner review. Migration **has not been applied to the shared database**. Only Task 1 is in this change; no queue/worker services are implemented or started.

## Behavior

The Source activity menu opens `#/source-activity`, separate from Audit trail. It displays preview capacity waits, HTTP 429 busy replies, timeouts and read success/error by workspace, connection, dataset and user UUID. Filters cover time range, event kind and dataset; refresh resets pagination. Each UI page requests 100 events. Next-page cursors remain strings and preserve the original time cutoff. Rows are replaced rather than accumulated. Destroying a view aborts its pending requests; late responses/401s cannot affect another workspace/session. Data is rendered with textContent, including dataset/user text and large numeric strings.

`GET /api/v2/workspaces/{workspace_id}/source-activity` requires `connection.read`. Nonmembers receive 404. Supported parameters: `since` (ISO datetime), `kind` (closed enum), `dataset` (validated identifier), `cursor` (positive bigint), `limit` (1–500, default 100). Response: `{items: [...], next_cursor: string|null}`. IDs, counts and metrics are strings to preserve JS precision; missing metrics are null. Pagination uses `id < cursor ORDER BY id DESC`, not offsets.

Only these fields exist in storage/API: id, at, kind, workspace_id, connection_id, dataset, user_id, waited_ms, rows, bytes. Kinds are `queue_wait`, `busy_429`, `timeout`, `read_ok`, `read_error`. There is no free-text message, SQL, filter value, token, connection URL or detail JSON field. Dataset names and UUIDs are validated before insertion. `bytes` measures JSON row-payload bytes; it is not a claim about upstream network/Arrow bytes. Wait duration measures source-capacity acquisition, including PG round trips; it is not total query latency. Preview reads are instrumented here; metadata health/catalog requests and future worker reads are not claimed as instrumented.

## Best-effort boundary

`activity.record` uses a savepoint on the request transaction, with a 250 ms statement timeout and 100 ms lock timeout while inserting; previous settings are restored. An insertion/validation/pool failure returns false and never poisons the caller transaction. Activity-writer diagnostics log only a fixed message and exception class. Standalone callers may omit `db` to borrow/commit/return a short app connection. Limiter wait observers are optional and isolated from the source operation. Source outcomes and existing audits/Retry-After headers are preserved if event recording fails.

If migration 0006 is not installed, preview continues through this best-effort path; the activity GET returns a sanitized 503. Do not mistake this pending deployment state for an installed Log page.

## Append-only and retention

`0006_activity.up.sql` grants app SELECT/INSERT and revokes UPDATE/DELETE/TRUNCATE. Triggers also reject normal mutations by the table owner. The explicitly privileged maintenance exception permits `uetl_migrator` to delete rows already older than 30 days. The fixed-cutoff SECURITY DEFINER `prune_source_events()` exposes only that safe expiry operation to the app/reaper, with a fixed search path and no caller-supplied cutoff. It cannot prune recent events; user-supplied settings are not used to bypass the trigger.

`reaper.prune_source_events(db)` is the retention entry point. Scheduling/re-enqueue orchestration is deferred to Task 5; no background reaper is left running in Task 1. Historical UUIDs deliberately have no cascading entity FK, so deleting a connection cannot mutate/delete its event history. The service supplies scope from the authenticated connection/workspace, not request-provided event metadata.

Migration naming is `0006_activity`, so later `0006_runs` sorts after it without editing an already applied migration. Down removes the new table/functions only. Applying up or down on the shared server still requires explicit owner approval.

## Isolated verification

Native PostgreSQL 17 binaries were present but their server catalog resources (`postgres.bki`) were missing; initdb could not run. The owner explicitly approved the separate `compose.activity-test.yml` PostgreSQL 13 fixture in chat. It starts only `postgres:13` in a unique `uetl-activity-test-*` project, bound to a random loopback port with throwaway tmpfs data, and never consumes the main .env or starts api/worker/Redis. Fixture credentials are synthetic/trust-only on that temporary local endpoint. Finally always runs Compose down for that exact project; no host scratch directory is created.

After the Task 1 test-Compose approval, run in PowerShell:

```powershell
$env:UETL_ACTIVITY_TEST_COMPOSE = '1'
try { python -m pytest tests/v2 -q -p no:cacheprovider --tb=short }
finally { Remove-Item Env:UETL_ACTIVITY_TEST_COMPOSE -ErrorAction SilentlyContinue }
node --test tests/ui/*.test.js
npm.cmd test
```

Without the explicit opt-in, isolated migration tests fail clearly rather than using shared PG. Existing regression tests retain their established rolled-back test workspaces; new activity/migration tests always target the isolated PG13 instance. No real/SCADA source data is used.

Evidence: RED was observed for the missing backend module and UI component before implementation, and for a source-originated busy response initially misclassified as read_error. ISOLATED tests cover up/down/up, trigger/role immutability, privileged old-only retention, cross-workspace 404, one busy event, safe fields, 500-row cap/keyset pagination and exact bigint metrics. Injected PostgreSQL division-by-zero covers logging failure with success/timeout/rejection/busy outcomes while the main request and audit remain valid. DOM-fixture tests cover inert text, badge styles, filters, bounded pages, stable time cutoff, refresh and stale workspace/session responses. No live browser certification or Gate 3 completion is claimed.

Final results: **149 v2 tests passed** (15 new isolated activity cases), **31 UI tests passed**, **39 legacy tests passed**, static build dependency-closure test and `git diff --check` passed. The activity fixture exercises migration up/down/up only in disposable PG13. Cleanup checks found zero test containers, test networks, native-test scratch folders, live_fixture processes and shared source leases. A read-only catalog check confirmed `uetl_meta.source_event` is absent on the shared DB.
