# 05 — Phase test plan

Evidence labels used in reports: `TESTED LIVE` / `TESTED ISOLATED` / `MOCKED` / `BLOCKED`. Tests run only in an isolated compose project (`compose.test.yml`) with throwaway PG/Redis and a **fixture SPICE** (either a disposable spiced container from the existing image with a fixture spicepod, or a labelled mock). Production SPICE is touched only with explicit approval.

## Fixtures
- `fx_small`: 100 rows, mixed types, NULLs. `fx_precision`: NUMBER(38,10), values > 2^53 as IDs, timestamps with TZ. `fx_large`: 5–10 M synthetic rows (generated in SPICE via generator or DuckDB file). `fx_wide`: 200 columns. `fx_perm`: object not in workspace allowlist. Users: viewer, author, reviewer, operator, admin in workspaces A and B.

## Gate 1
Cross-workspace read/write → 403/404 for every route (generated route-matrix test iterates the OpenAPI schema). Forged approval (wrong checksum, author self-approval, viewer role, direct DB-less POST) → rejected + audited. CSRF missing → 403. Cookie flags. Password hash params. Migration up/down on empty and seeded DB; `pg_dump`/restore round-trip; UPDATE/DELETE on `audit_event`, `approval_decision`, approved revision rejected by DB. Logs contain no secrets (grep canary secret). Health/readiness with dependencies down. Legacy pilot still launches (`Start U-ETL Test.bat`, existing tests unchanged and green).

## Gate 2
Per transport: connect, auth fail, unreachable host, TLS verify fail, timeout. Capability flags match probe. Catalog matches fixture metadata incl. precision/scale. Preview: row, byte, time caps enforced; unauthorized object → 403; test-connection endpoint rejects any SQL field and internal-IP URLs (SSRF cases: loopback, link-local, metadata IP, DNS rebinding). Secret canary never appears in responses/logs/audit. API process RSS flat under repeated previews. Legacy Oracle adapter off by default; SPICE failure never triggers it.

## Gate 3
Kill API during run → run completes. Kill worker at each boundary (before first batch, mid-staging, after staging/before publish, inside publish txn, after commit/before ack) → recovers, no duplicate/partial published rows. Duplicate delivery ×3 → one published generation. Lease fencing: zombie worker's late writes rejected. Memory ceiling test on `fx_large` (worker RSS < configured limit, e.g. 512 MB). Precision/ID/NULL round-trip equals source. Unauthorized run/cancel/retry. Dead-letter after max attempts visible in UI. Status == committed data (reconciliation query). Redis flush → outbox re-enqueue.

## Gate 4
SQL vs Visual equivalence on ≥5 logic fixtures (filter, join, derive, aggregate, validation) → identical result hash. SQL negative suite: DDL, DML, `;` multi-statement, comments hiding statements, unicode tricks, UNION to unauthorised object, function denylist, huge LIMIT, cartesian join under budget, bind injection. Cross-workspace object reference → rejected. Editing approved revision creates new draft; old approval does not carry. Only `approved` revision submit succeeds. Reviewer self-approval blocked. E2E: Login → Connection → Catalog → Wizard → Pipeline → Approval → Queue → Worker → Publish → Monitoring. UI: axe zero serious violations, keyboard-only walkthrough, reduced-motion snapshot, 200-node canvas + 500-row table performance measured, no AI behaviour claimed.

## Load budgets (initial proposals)
API p95 < 300 ms non-preview; preview ≤ 1000 rows / 1 MB / 10 s; worker batch 10k rows; max 2 concurrent runs per SPICE (shared-host RAM 5 GB cap); staging disk quota per run configurable.
