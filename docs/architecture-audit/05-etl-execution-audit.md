# ETL execution audit

Audit date: 2026-10-26. All execution behavior below is inferred from source; no jobs or database queries were run. See [00](00-executive-summary.md).

## Current execution model

```mermaid
sequenceDiagram
    participant B as Browser
    participant H as HTTP request thread
    participant S as Service memory state
    participant W as Executor thread in same process
    participant O as Oracle
    participant T as Local SQLite
    B->>H: POST /api/extract_load
    H->>S: Validate session, profile, metadata, limits
    S->>W: submit _run; one active operation
    H-->>B: 202 job_id, running
    W->>O: Fresh connection; READ ONLY; capped SELECT
    O-->>W: fetchmany batches accumulated in RAM
    W->>T: Upsert all converted rows; commit data
    W->>T: Separate load-status transaction
    W->>S: Set result and read_completed/failed
    B->>H: GET /api/jobs/id every ~300 ms
    H-->>B: Complete in-memory job snapshot
```

Evidence: `server.py:Handler.do_POST`; `Service.submit/_run/job`; `real-source-ui.js:realSourceWaitForJob/realSourceWaitForProfileJob`; `OracleReadAdapter.session/_query/extract_bounded`; `SQLiteTargetStore.load_rows/record_source_status`.

The HTTP extraction request does **not** synchronously wait for Oracle completion. It returns a receipt after validation and dispatch. However, extraction, conversion and target writes run in a thread of the Web/API process, so memory, CPU, process uptime and deployment remain shared. Cache/status/preview GETs and catalog begin_refresh perform synchronous storage work in HTTP paths.

## Execution capability assessment

| Question | Current real-source answer | Evidence |
|---|---|---|
| Threads or processes? | One ThreadPoolExecutor worker, plus HTTP threads and credential-expiry thread | `Service.__init__`; `ThreadingHTTPServer` |
| Durable queue? | No; immediate submit and active flag; overlaps rejected with 409 | `Service.submit` |
| Survive browser close? | Current submitted job can continue while API stays alive; later group tables cannot be submitted by a closed browser | `_run`; `runLocalCollectionGroup` |
| Survive API restart? | No live execution continuation; job/session/credentials lost; already committed SQLite data remains | `Service.sessions`; `server.py:main` |
| Persisted job status/history? | No; max 20 memory jobs. Warehouse registry stores last table load only | `submit/job`; `record_source_status` |
| Independently deployable worker? | No real worker service. Synthetic worker CLI is independent but processes fixtures only | `worker.py:main`; `process_one` |
| Concurrency limit? | One read/load at a time per Service plus ReadGate. No cross-process admission control | `self.active`, executor max_workers=1; `ReadGate` |
| Shared source connection? | No persistent pool or handle; each adapter operation opens/closes a fresh Oracle connection | `oracle_factory`; `OracleReadAdapter.session` |
| Profile Connect? | Sets connected flag on previously tested config, not physical connection or current health | `connect_profile` |
| Retry? | Manual resubmit only; no durable request identity or original snapshot replay | `submit`; job failure messages |
| Idempotent? | Upsert of equivalent PK rows reduces duplicates, but no job-level idempotency or pinned run boundary | `load_rows`; `extract_bounded` |
| Checkpoint/watermark? | None for Oracle extraction; ROWNUM cap has no cursor/order/snapshot | `extract_bounded` |
| Staging/transform? | Complete extracted list in RAM, then direct table upsert. Dataset visual mapping is not applied | `_run` extract_load branch |
| Atomic publish? | Per-table data DML transaction, then separate status transaction. No Dataset-wide publication | target store methods |
| Failed group recovery? | Prior successful tables remain committed; later tables stop; no durable group attempt/resume | `runLocalCollectionGroup` |
| Deletions/full refresh? | No source delete reconciliation or production replacement generation | upsert-only SQL; DemoSync is separate |
| Streamed large datasets? | Driver fetches batches, but all batches are appended into memory before load | `_query`, `extract_bounded` |
| Cancel? | No real cancel endpoint or driver-cancel path; only deadline and connection disposal | API inventory; adapter session |

## Resource risks

**RAM:** `_query` builds rows up to an extract limit of 2,147,483,647. `extract_bounded` creates another converted list while raw rows are live. Batch size controls each fetch, not total retained memory. Timeout alone does not prevent a fast, wide result from exhausting RAM. Catalog cache reads and browser arrays also materialize entire snapshots. Sample results remain in retained job results.

**CPU:** row conversion, JSON encoding, sample distinct/null summaries and large catalog matching occur in the shared process. scrypt authentication is intentionally expensive and happens under service lock. No separate CPU/memory quotas exist. There is no GPU integration today; future LLM work must not share an unconstrained execution budget.

**Source connections/network:** one active operation limits connection pressure locally, and each operation closes its connection. Multiple future API processes would each have their own limit, multiplying source load. Driver connect timeout is separate from the query clock; row limits do not prove physical scan cost. Metadata column search caps returned matches at 10,000 but may still require source work beyond that count. Source query plans, IO cost and network throughput are NOT VERIFIED.

**SQLite/storage:** target store RLock serializes reads/writes in process; preview/status can wait for loads. Every load counts the entire target table. There is no disk-byte budget, staging quota or retention cleanup for historical catalog snapshots. Warehouse data and status writes are separate; SQLite NUMERIC conversion can alter exact data.

## Existing recovery patterns that can be reused carefully

`Registry.enqueue` has request identity/signature and scope locking. `claim/_owned/heartbeat/checkpoint` demonstrate lease expiration, stale worker fencing and progress. `complete/fail/cancel` demonstrate state transitions. `tests/test_foundation.py` includes crash/reopen/subprocess cases, but only over the fixture. `DemoSync.begin/finish` demonstrates frozen boundaries, retry scope, watermark and quarantine semantics over arrays.

These are conceptual/test assets. Live data recovery additionally needs a source boundary or durable stage, atomic target publication, worker credentials, run attempts and observable state. Fixture checkpoint 1..3 is not an Oracle cursor. Existing `docs/incremental-backend-contract.md` is a stronger starting acceptance contract than assuming monotonically increasing source IDs imply commit order.

## Proposed service boundary — no implementation

Keep API responsible for authentication/authorization, request validation, immutable definition approval, run submission and status retrieval. Move extraction, transforms, stage validation and target writes to an independently running ETL worker with a durable job claim. Jobs reference source/target/definition revisions and secret references, never session dictionaries or plaintext credentials in queue payloads.

Introduce durable attempt/lease/cancel/checkpoint state with scope locks and bounded per-source admission. Use at-least-once delivery plus idempotent processing and a tested publish protocol rather than claiming exactly-once execution. A database-backed queue may be sufficient initially; a separate broker is an open capacity decision, not a Phase 0 requirement.

Stream validated batches into run-scoped staging, with row/byte/disk/time budgets and durable manifests. Publish data and committed progress in a single supported atomic boundary or a documented recovery protocol. Persist a separate in-flight checkpoint and committed watermark. SQL and visual plans should reach this same worker interface. Unsupported incremental semantics must block execution.

Before worker separation, decide authorized unattended credentials: current credentials expire with an interactive owner session and cannot support schedules. Retain a controlled manual pilot until identity, queue, target and failure semantics have acceptance criteria. No extraction code or service was moved during this audit.
