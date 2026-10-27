# Load Hardening and TanStack UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make source reads and the preview UI hold up under concurrent use and very wide/large tables, and close the open Gate 2 gaps.

**Architecture:** A PostgreSQL-backed lease limiter (PG is the lease authority per the v2 plan) caps concurrent SPICE reads per pool (`spice`, `odbc`). The catalog records, per dataset, its source kind and whether it accepts a pushed-down `LIMIT`, so the LIMIT-less retry happens at most once per dataset and ODBC reads are serialized. The browser UI stays vanilla JS and adopts the framework-agnostic TanStack cores (query, table, virtual, form, store) as vendored, hash-pinned files; TanStack Router is not used (it requires React/Solid, contradicting the owner's "keep the vanilla UI" decision).

**Tech Stack:** Python 3.12, FastAPI, psycopg2, PostgreSQL 13, pyarrow Flight, pytest; vanilla JS + vendored `@tanstack/query-core`, `table-core`, `virtual-core`, `form-core`, `store`.

**Spec:** Conversation design of 2026-10-27 (brainstorming: "Retry / literal / concurrency / TanStack UI"), plus `docs/v2/09-spice-probe-results.md`, `docs/v2/decision-log.md` (2026-10-27 risk acceptances), `docs/v2/05-phase-test-plan.md` (Gate 2). No separate spec file exists; the Global Constraints below restate the decisions.

## Global Constraints

- Load assumptions (**the planner's defaults, NOT confirmed by the owner**): at most 10 concurrent users, tables up to ~1M rows, up to 300 columns. Recorded in `decision-log.md` in Task 9; the owner may override.
- Caps: SPICE pool = 2 concurrent reads (`UETL_SPICE_CONCURRENCY`), ODBC pool = 1. Preview budgets stay 1000 rows / 1 MB / 10 s.
- The browser UI stays vanilla JS: no React, no bundler, no inline handlers. `script-src 'self'`: TanStack files are self-hosted under `vendor/tanstack/`, pinned by exact version and sha256, never loaded from a CDN.
- Downloading TanStack packages needs explicit owner approval in chat before Task 5 Step 1 (state package names, versions and source: the npm registry).
- No UI-side automatic retry of preview/mutating requests (`retry: false`); a 429 shows "queued/busy" and the user retries.
- Numbers reach the browser as strings when beyond JS-safe range or decimal (existing rule, `spice._jsonable`).
- No new Python dependency. Migrations are additive with a working `down`. Tests run with `python -m pytest tests/v2 -q -p no:cacheprovider` and every DB test rolls back.
- Never print or commit secrets. SPICE host changes are out of scope.

## Review Focus

- Two requests arrive at the same instant when one lease slot is free: exactly one must get it, the other gets 429 with `Retry-After` (never both, never a hang).
- A request crashes or the process dies while holding a lease: the slot must free itself after the TTL (no permanent lock-out of the SQL Server pool).
- A dataset with 300 columns and 1000 rows: the browser must not build more than a screenful of DOM cells.
- A column name or cell value containing `<script>`, quotes or very long text must render inert in the new table.
- A filter value like `x'; DROP TABLE t; --`, a NUL byte, an enormous string or a leading-zero integer must never produce SQL outside the single-table SELECT shape.
- Pool exhaustion must not make `/healthz` or login slow (limiter waits are short and bounded).

---

### Task 1: PostgreSQL lease limiter

**Files:**
- Create: `backend/migrations/0005_source_lease.up.sql`, `backend/migrations/0005_source_lease.down.sql`
- Create: `backend/v2/limiter.py`
- Test: `tests/v2/test_limiter.py`

**Interfaces:**
- Produces: `CAPS: dict[str,int]` (`{"spice": 2, "odbc": 1}`, spice cap read from `UETL_SPICE_CONCURRENCY`); `class Busy(Exception)` with `retry_after: int`; `acquire(pool: str, ttl_s: int = 30) -> uuid.UUID` (raises `Busy`); `release(lease_id: uuid.UUID) -> None`; `lease(pool: str, ttl_s: int = 30)` context manager wrapping both.

- [ ] **Step 1: Write the failing tests** in `tests/v2/test_limiter.py`: `test_cap_is_enforced` (acquire `CAPS["odbc"]` leases, next `acquire("odbc")` raises `Busy` with `retry_after >= 1`); `test_release_frees_slot`; `test_expired_lease_is_reclaimed` (acquire with `ttl_s=1`, sleep 1.2 s, acquire again succeeds); `test_pools_are_independent`; `test_concurrent_acquire_one_winner` (8 threads race for the last slot; exactly one succeeds, others `Busy`); `test_unknown_pool_rejected` (`ValueError`). Each test cleans its leases in a `finally`.
- [ ] **Step 2: Run** `python -m pytest tests/v2/test_limiter.py -q -p no:cacheprovider`; expected: FAIL (module missing).
- [ ] **Step 3: Migration** `source_lease(id uuid pk default gen_random_uuid(), pool text not null check (pool in ('spice','odbc')), expires_at timestamptz not null, created_at timestamptz not null default now())` with index on `(pool, expires_at)`. `down` drops it. Apply with `python backend/migrate.py up`, then `down --yes`, then `up` to prove reversibility.
- [ ] **Step 4: Implement `limiter.py`.** `acquire` uses its OWN short autocommit connection from a small dedicated pool (not the request transaction, so the lease is visible to other requests immediately). Inside one transaction: `pg_advisory_xact_lock(hashtext(pool))`, delete expired rows of that pool, count live rows, insert if below cap else raise `Busy(retry_after=ceil(seconds until earliest expiry), min 1)`.
- [ ] **Step 5: Run the tests**; expected: PASS (6).
- [ ] **Step 6: Commit** `feat: PostgreSQL lease limiter for source reads`.

### Task 2: Catalog records source kind and LIMIT support

**Files:**
- Modify: `backend/v2/spice.py` (`list_datasets`), `backend/v2/sources.py` (`refresh_catalog`, `catalog`, `catalog_all`)
- Test: `tests/v2/test_sources.py`, `tests/v2/test_dataset_requests.py` (adapt the monkeypatched `list_datasets`)

**Interfaces:**
- Produces: `spice.list_datasets(conn) -> list[dict]` where each item is `{"name": str, "kind": "postgres" | "odbc" | "other"}`; `kind` is derived from the prefix of `/v1/datasets[].from` and the `from` string itself is never stored or returned. Snapshot payload per object becomes `{"columns": [...], "kind": str, "limit_pushdown": bool | None}` (`None` = not yet learned).

- [ ] **Step 1: Failing tests:** `test_list_datasets_returns_kind_without_source_path` (live, `@live`): every item has keys `name`,`kind` only and `kind` in the allowed set; `test_refresh_stores_kind_and_hides_from_string` (monkeypatched `list_datasets`): stored payload contains `kind`, the catalog API responses contain no `from`/connection-string text.
- [ ] **Step 2: Run** the two tests; expected FAIL.
- [ ] **Step 3: Implement.** `list_datasets` parses `from` (`postgres:` -> `postgres`, `odbc:` -> `odbc`, else `other`); keep the name filter `OBJECT_RE`. `refresh_catalog` writes `kind` and carries over `limit_pushdown` from the previous snapshot for objects that still exist. Update the existing monkeypatches in `test_dataset_requests.py` to return dicts.
- [ ] **Step 4: Run the full suite**; expected: PASS.
- [ ] **Step 5: Commit** `feat: catalog records source kind and learned LIMIT support`.

### Task 3: Preview uses limiter, learned LIMIT policy and 429

**Files:**
- Modify: `backend/v2/sources.py` (`preview`), `backend/v2/spice.py` (`run_bounded` pool parameter)
- Test: `tests/v2/test_sources.py`

**Interfaces:**
- Consumes: `limiter.lease(pool)` and `limiter.Busy` (Task 1); snapshot `kind`/`limit_pushdown` (Task 2).
- Produces: `spice.run_bounded(conn, sql, ..., pool: str = "spice")` no longer owns the in-process semaphore (remove `_SLOTS`); the caller holds the lease. Preview response gains `"limit_applied": bool`.

- [ ] **Step 1: Failing tests:** `test_odbc_dataset_preview_takes_the_odbc_pool` (monkeypatch `limiter.acquire` to record the pool for `alarm`; expect `"odbc"`); `test_busy_returns_429_with_retry_after` (monkeypatch `acquire` to raise `Busy(3)`; expect 429, header `Retry-After: 3`, an audit row `preview.run` outcome `deny` with detail `reason: busy`); `test_limit_less_retry_happens_once_per_dataset` (live `alarm`: first preview learns `limit_pushdown=false` in the latest snapshot; a spy on `run_bounded` shows the second preview calls it exactly once); `test_lease_released_after_error` (force `SpiceError`, then `limiter` slot count back to 0).
- [ ] **Step 2: Run**; expected FAIL.
- [ ] **Step 3: Implement.** In `preview`: pool = `"odbc"` if object `kind == "odbc"` else `"spice"`; wrap the read in `limiter.lease(pool)`; `Busy` -> commit the deny audit row, raise 429 and set `Retry-After`. Choose the SQL by `limit_pushdown`: `False` -> build without LIMIT directly; `None`/`True` -> current behaviour (try LIMIT, on `rejected` retry without LIMIT) and, after the retry succeeds, `UPDATE catalog_snapshot SET payload = jsonb_set(...)` for that object on the latest revision (uetl_app may update this table; if the grant is missing, add it in Task 1's migration).
- [ ] **Step 4: Run the full suite**; expected: PASS.
- [ ] **Step 5: Commit** `feat: preview leases source capacity and learns LIMIT support`.

### Task 4: SQL shape guard and fuzz tests

**Files:**
- Modify: `backend/v2/spice.py` (add `assert_select_shape`)
- Test: `tests/v2/test_sql_guard.py`

**Interfaces:**
- Produces: `spice.assert_select_shape(sql: str, allowed_object: str, allowed_columns: set[str]) -> None` raising `ValueError`; `build_select`'s result must always pass it (call it inside `build_select` before returning).

- [ ] **Step 1: Failing tests:** `test_generated_sql_always_has_the_expected_shape` (seeded `random.Random(1)`, 2000 cases: random object names, column subsets, ops, and values drawn from a hostile corpus: quotes, `;`, `--`, `/*`, `\x00`, newlines, unicode, 10 kB strings; for every case either `ValueError` is raised or the SQL matches `^SELECT (\*|"[A-Za-z0-9_]+"(, "[A-Za-z0-9_]+")*) FROM "[A-Za-z0-9_]+"(\."[A-Za-z0-9_]+"){0,2}( WHERE .+)?( LIMIT \d+)?$` AND contains no `;` outside a quoted literal AND the literal-stripped text has no keywords from {INSERT, UPDATE, DELETE, DROP, CREATE, ALTER, COPY, GRANT, UNION}); `test_guard_rejects_unknown_column`; `test_guard_rejects_second_statement`.
- [ ] **Step 2: Run**; expected FAIL.
- [ ] **Step 3: Implement** `assert_select_shape` with a small tokenizer that removes single-quoted literals (doubling `''` as the only escape) before checking shape; reject any text left after the literals are stripped that does not match the whitelist grammar.
- [ ] **Step 4: Run** the new tests and the full suite; expected PASS. If the fuzz finds a real escape, fix `literal()` first.
- [ ] **Step 5: Commit** `test: fuzz and shape-guard the generated SELECT`.

### Task 5: Vendor the TanStack cores

**Files:**
- Create: `scripts/vendor_tanstack.py`, `vendor/tanstack/*.js`, `vendor/tanstack/MANIFEST.json`, `vendor/tanstack/LICENSES.md`
- Modify: `backend/v2/app.py` (`STATIC` allowlist entries for each vendored file), `index.html` (script tags before `v2-ui.js`)
- Test: `tests/v2/test_vendor.py`

**Interfaces:**
- Produces: browser globals/ES-module bundles for `query-core`, `table-core`, `virtual-core`, `form-core`, `store` exposed under `window.TanStack` (one tiny `vendor/tanstack/index.js` re-exports them; built from the downloaded ESM files without a bundler step in production). `MANIFEST.json`: `{ "<file>": {"package": str, "version": str, "sha256": str} }`.

- [ ] **Step 1: Get the owner's approval** (stated in Global Constraints) and read each package's current `package.json`/exports from the npm registry to pick exact versions at least two weeks old.
- [ ] **Step 2: Failing tests:** `test_manifest_hashes_match_files` (recompute sha256 of every file in `vendor/tanstack`, compare to `MANIFEST.json`); `test_every_vendored_file_is_served_and_only_those` (GET each path -> 200 with JS content type; an unlisted path under `/vendor/` -> 404); `test_no_external_urls_in_html` (`index.html` has no `http(s)://` script src).
- [ ] **Step 3: Implement `scripts/vendor_tanstack.py`** (downloads the tarballs with a pinned version map, extracts only the ESM build files into a temp dir that is not the project dir, writes files and manifest, prints hashes) and run it; add the `STATIC` entries and script tags; record licenses.
- [ ] **Step 4: Run** the vendor tests and the full suite; expected PASS. Smoke check in Chrome that `window.TanStack.QueryClient`, `createTable`, `Virtualizer`, `FormApi`, `Store` exist (names confirmed from the downloaded type files).
- [ ] **Step 5: Commit** `chore: vendor TanStack cores (pinned, hashed)`.

### Task 6: UI state, query client and hash router

**Files:**
- Create: `v2-store.js` (store + query client wrapper + hash router), add to `STATIC` and `index.html`
- Modify: `v2-ui.js` (replace the `V2` global and `load/invalidate` with the new modules)
- Test: `tests/ui/v2-store.test.js` (run with `node --test`; DOM-free logic only)

**Interfaces:**
- Produces: `window.V2Store` with `get(key)`, `set(patch)`, `subscribe(fn)`; `window.V2Query.fetch(key: string[], path: string, opts?: {staleMs?: number}) -> Promise<any>` (GET only, dedupes in-flight requests, `retry: 0`, accepts an `AbortSignal`); `window.V2Query.invalidate(prefix: string[])`; `window.V2Route` with `current() -> {page, connection?}` and `go(page, params?)` using `location.hash` (`#/sources/<connectionId>`).

- [ ] **Step 1: Failing tests:** `two simultaneous fetch calls with the same key make one request`; `invalidate refetches on next fetch`; `a non-2xx response rejects with status and does not retry`; `route round-trips #/sources/<uuid>`; `a malformed hash falls back to the default page`.
- [ ] **Step 2: Run** `node --test tests/ui`; expected FAIL.
- [ ] **Step 3: Implement** the three modules using `QueryClient` (`defaultOptions.queries.retry = false`), a `Store` for UI state and a ~40-line hash router; port `v2-ui.js` to read state from the store and call `V2Query`, deleting the hand-rolled `load/inflight/invalidate`.
- [ ] **Step 4: Run** `node --test tests/ui` and `node --check v2-ui.js`; then open the Sources page in Chrome and confirm: list loads once (network tab shows one request per resource), browser Back moves between connections.
- [ ] **Step 5: Commit** `feat(ui): central store, deduping query client and hash routes`.

### Task 7: Virtualized preview table

**Files:**
- Create: `v2-table.js` (renderer using table-core + virtual-core, 2-D virtualization)
- Modify: `v2-ui.js` (`previewPanel`), `v2-ui.css`, `backend/v2/app.py` (`STATIC`), `index.html`
- Test: `tests/ui/v2-table.test.js`

**Interfaces:**
- Consumes: preview response `{columns: [{name,type}], rows: string|number|null[][], truncated}`.
- Produces: `window.V2Table.mount(el: HTMLElement, data: PreviewResult, opts?: {maxColumnsShown?: number}) -> {destroy(): void, setVisibleColumns(names: string[]): void}`; initial visible columns = first 20; a "Columns" picker lists every column with a search box; cells are written with `textContent` only.

- [ ] **Step 1: Failing tests (jsdom-free, pure logic exported as `V2Table._model`):** `model for 300 columns x 1000 rows exposes at most visibleColumns*visibleRows cells per window` (assert window size <= 40 x 60 for a 800x600 viewport); `sorting is stable and treats numeric strings numerically for numeric column types`; `hostile values (<script>, quotes, 10k chars) are returned unchanged for textContent rendering and truncated for display at 200 chars with a title`; `column picker search is case-insensitive`.
- [ ] **Step 2: Run** `node --test tests/ui`; expected FAIL.
- [ ] **Step 3: Implement** `_model` with `createTable` from table-core (columns from the response, `getCoreRowModel`, `getSortedRowModel`) and two `Virtualizer`s (rows and columns); renderer creates only windowed cells, fixed row height, sticky header, sticky first column, keyboard focus on the grid with arrow-key scroll; show type under each header; null as a muted "null".
- [ ] **Step 4: Run** the node tests; then in Chrome preview `cycletime` (286 columns) with 1000 rows and confirm: DOM cell count stays under 3000 (`document.querySelectorAll('.v2-cell').length`), scrolling stays smooth, and the page memory does not grow with column count.
- [ ] **Step 5: Commit** `feat(ui): virtualized two-dimensional preview table`.

### Task 8: Forms and busy/queued states

**Files:**
- Modify: `v2-ui.js` (request-dataset form, filter builder, preview submit, busy banner), `v2-ui.css`
- Test: `tests/ui/v2-forms.test.js`

**Interfaces:**
- Produces: `window.V2Forms.datasetRequest()` and `window.V2Forms.previewFilters(columns)` returning form-core `FormApi` instances whose validators mirror the server (`dataset_name` `^[a-z][a-z0-9_]{2,60}$`; remote object by profile; filter value parsed by column type); a preview submit button that disables while a request is in flight (no double submits) and, on HTTP 429, shows "Source is busy, try again in N s" using `Retry-After`.

- [ ] **Step 1: Failing tests:** `dataset name validator accepts and rejects the same strings as the server regex` (shared table of 12 cases, copied from `tests/v2/test_dataset_requests.py`); `integer filter on an Int64 column rejects 1.5`; `submit is ignored while a request is in flight`; `429 maps to a message containing the Retry-After seconds`.
- [ ] **Step 2: Run** `node --test tests/ui`; expected FAIL.
- [ ] **Step 3: Implement** the validators and wire the forms; add a filter builder (up to 5 filters: column, operator from `= != < <= > >=`, value) to the preview form; keep server validation authoritative.
- [ ] **Step 4: Run** node tests, `node --check`, then in Chrome: submit two quick previews (second blocked), trigger a 429 by holding the `odbc` pool lease from a test script and confirm the message.
- [ ] **Step 5: Commit** `feat(ui): form-core validation, filter builder, busy state`.

### Task 9: Gate 2 gap closers, load test and records

**Files:**
- Modify: `v2-ui.js` (show capabilities), `tests/v2/test_sources.py`
- Create: `scripts/loadtest_preview.py`, `docs/v2/10-load-test-results.md`
- Modify: `docs/v2/decision-log.md`, `docs/v2/implementation-log.md`, `docs/v2/runbook-dataset-onboarding.md` (if limits changed)

**Interfaces:**
- Produces: `scripts/loadtest_preview.py --users N --seconds S --object NAME` (logs in with credentials from env vars `LOADTEST_USER`/`LOADTEST_PASSWORD`, never from arguments; prints p50/p95 latency, 429 count, errors; reads only through the preview endpoint).

- [ ] **Step 1: Failing tests:** `test_preview_time_budget_is_enforced` (`run_bounded` with `max_seconds=1` on a synthetic slow query such as `SELECT count(*) FROM generate_series(1, 5000000000)`, expect `SpiceError` code `timeout` within 3 s, and slot released); `test_capabilities_visible_in_connection_row` (UI logic test: the row renders `rest`, `flight`, `streaming`, `bind parameters: no`).
- [ ] **Step 2: Run**; expected FAIL.
- [ ] **Step 3: Implement** capabilities display; write the load-test script.
- [ ] **Step 4: Run the load test** against the real SPICE with `--users 10 --seconds 60 --object machine_map` and a second run with an ODBC table only if the owner approves loading the SCADA database; record numbers, 429 rate and SPICE/host observations in `10-load-test-results.md`, labelled TESTED LIVE or NOT RUN.
- [ ] **Step 5: Update records**: the load assumptions (as the planner's defaults), the Gate 2 checklist status, the limiter design, the vendored-library policy.
- [ ] **Step 6: Run the full suite** (`pytest tests/v2` and `node --test tests/ui`); expected all PASS.
- [ ] **Step 7: Commit** `docs/test: Gate 2 gap closers, preview load test and records`.

---

## Self-review

- **Spec coverage:** retry policy (Tasks 2–3), literal safety (Task 4), concurrency (Tasks 1, 3), TanStack query/table/virtual/form/store (Tasks 5–8), Router decision (Architecture + Global Constraints), Gate 2 gaps (time budget, capabilities display, load test in Task 9). The unconfirmed load numbers are flagged in Global Constraints and Task 9.
- **Types:** `limiter.lease(pool)` / `Busy.retry_after` are used identically in Tasks 1 and 3; `list_datasets` dict shape (Task 2) is the shape monkeypatched in Task 2's test edits; preview `limit_applied` is only produced in Task 3.
- **Not in this plan (deliberate):** Redis-based limiter (PG lease chosen), TanStack Router/Start, automatic UI retry, SPICE host changes, an AST parser dependency.
