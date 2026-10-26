# Security, reliability and performance risks

Audit date: 2026-10-26. Static inspection only. No penetration tests, scans, stress tests, production queries or runtime exploit verification. Current intended load: one local owner. Shared v2 deployment is proposed, not observed.

Severity: **P0 Critical** immediate catastrophic exposure established; **P1 High** important integrity/availability risk or blocker before proposed shared operation; **P2 Medium** bounded pilot reliability/security gap; **P3 Low** maintainability/verification issue. No P0 finding is established. Conditional v2 blockers are labelled rather than presented as active production incidents.

## Existing protections

- HTTPS loopback binding, exact Host/client/Origin checks, secure cookie, CSRF, JSON/body cap, static file allowlist and cache-control/security headers: `server.py:handler_for`.
- Minimum application passphrase, scrypt hash, random sessions, 30-minute server expiry, one-owner session policy and 5 login attempts/minute/process: `Service.__init__/login/session`.
- Driver TLS server DN matching for tcps; TCP requires explicit acknowledgement; retry_count=0: `oracle_factory/config_validate`.
- Fresh source transaction marked READ ONLY, generated SELECTs, quoted restricted identifiers and bound values, call deadlines and close-on-exit: `OracleReadAdapter.session/_query`.
- One in-process operation and sanitized errors: `Service.active`, `ReadGate`, `safe_source_error`.

Actual source grants, OS file ACL/encryption, target backups, identity delegation and physical query budgets remain NOT VERIFIED. A checkbox is not evidence of a least-privilege Oracle account.

## Prioritized findings

### R01 — P1: extraction can exhaust shared process memory

**Evidence:** `service.py:19,326` allows row_limit up to 2,147,483,647; `oracle_read.py:_query` appends rows; `extract_bounded` builds safe_rows; `_run` then writes them.

**Trigger/impact:** A fast, wide extract can consume available RAM before the deadline. The API and all jobs share that memory and fail together. Batch fetching is not streaming.

**Suggested mitigation:** enforce server-side row/byte budgets; stream bounded batches into staging under a separate worker memory budget. Measure peak RAM and reject over-budget work. No load test was run.

### R02 — P1: committed data can be reported as a failed/unregistered load

**Evidence:** `Service._run` calls `load_rows` then `record_source_status`; each opens and commits a separate connection/transaction in `target_store.py`.

**Trigger/impact:** Crash/disk/registry failure between calls leaves data committed while job fails or preview cannot find the table. A manual retry has no durable attempt to reconcile.

**Suggested mitigation:** commit data plus status in one transaction for the pilot; for v2 define stage/publish/progress atomicity and durable attempt recovery. Do not advance committed watermarks independently of publication.

### R03 — P1: exact numeric values and keys can lose precision

**Evidence:** `extract_bounded.scalar` stringifies Decimal; `sqlite_type` maps NUMBER/FLOAT to NUMERIC; PK uses those same column definitions.

**Trigger/impact:** High-precision decimals or sufficiently large numeric identifiers can be coerced to floating point. Distinct keys may compare as the same stored numeric value, causing incorrect upsert results. This is an integrity risk even for a small pilot.

**Suggested mitigation:** define precision/scale and key representation explicitly; preserve exact identifiers/decimals with validated target types. Add focused future acceptance cases for large keys and decimal round trips. No production values were inspected.

### R04 — P1: live jobs and credentials disappear on API restart

**Evidence:** `Service.sessions/submit/job`; executor is in process; jobs capped at 20; no live Registry dependency.

**Trigger/impact:** Process interruption during a load loses status and execution authority; client cannot distinguish unstarted, failed or committed work. Shared operation and scheduling cannot depend on this model.

**Suggested mitigation:** durable job/attempt registry and queue, separate workers, fenced leases, immutable definition/source refs and idempotent publish recovery. Reuse synthetic tests as examples, not a production guarantee.

### R05 — P1 before shared v2: approvals and RBAC have no server authority

**Evidence:** `prototype.js:P.role/canEdit/canRun/recordDatasetReview/approveDatasetDefinition`; HTTP `Service` has one owner and no per-user roles; `core.py:authorize` is synthetic-only.

**Trigger/impact:** Exposing the service to multiple users would let an authenticated local-owner equivalent perform all supported actions; browser role/approval changes have no trustworthy identity or audit. Current code intentionally binds locally; no shared deployment was observed.

**Suggested mitigation:** server-authenticated identity and object-scoped authorization, durable immutable approvals, reviewer identity and separation of approval/run permissions before shared access.

### R06 — P1: HTML escaping does not protect JavaScript event context

**Evidence:** `sync-ui.js:safe` escapes HTML characters; `prototype.js:datasetCandidateReviewPanel` interpolates user-entered requestedField inside quoted onclick/oninput JavaScript arguments; `server.py:Handler.reply` enables unsafe-inline scripts.

**Trigger/impact:** A business field containing an apostrophe can break handler syntax after HTML entities are decoded; crafted field content can reach same-origin script execution when an affected control is used. This could act with the active local session. Exploitability was not exercised.

**Suggested mitigation:** use event listeners/data values instead of interpolated JavaScript attributes; tighten CSP after removing inline handlers. Test ordinary apostrophes as well as untrusted field text in an authorized later phase.

### R07 — P2: abandoned catalog refresh can permanently block refresh attempts

**Evidence:** `CatalogStore.begin_refresh` rejects any existing state=loading; persistent rows survive reopen; fail_refresh only runs in handled `_run` failure branches; no abandon/lease/startup recovery path.

**Trigger/impact:** Browser closes between pages or API crashes after begin_refresh. Later refresh attempts hit conflict until external repair, while old complete metadata remains available but potentially stale.

**Suggested mitigation:** refresh owner/lease expiry and explicit safe abandonment/reconciliation; retain previous complete head. Existing tests cover head preservation, not abandoned-refresh recovery.

### R08 — P2: UI can claim sign-out while backend still retains a session

**Evidence:** `real-source-ui.js:realSourceLogout` catches and ignores logout errors, then clears client state and announces credentials cleared; `Service.logout` returns 409 during a read.

**Trigger/impact:** Logout while a read is busy or request fails. Backend session/cookie/config may remain valid until expiry, despite UI assurance. Credential memory is not securely erased by merely dropping a reference.

**Suggested mitigation:** distinguish pending/failed logout from confirmed revocation; support safe revocation/cancellation lifecycle; reflect server state accurately. This was traced statically, not reproduced.

### R09 — P2: target schema drift and row counts are insufficiently governed

**Evidence:** `target_store.py:load_rows` only CREATE IF NOT EXISTS, no layout/key validation; rows_written is total_changes delta; `Service._run` derives selected columns from discovered metadata.

**Trigger/impact:** Add a selected source column after initial load: INSERT references a missing target column. Type/key changes can leave incompatible old layout. Re-upserting unchanged values may still be reported as written, so counts are not insert/update/unchanged reconciliation.

**Suggested mitigation:** schema fingerprint and explicit evolution policy; validate compatibility before writing; use precise count semantics and target generation when replacement is required.

### R10 — P1 before full/incremental ETL: capped unordered reads are not a complete extraction strategy

**Evidence:** `extract_bounded` uses WHERE ROWNUM <= :row_cap without ordering, continuation or snapshot pinning. No live watermark/checkpoint/delete path exists; `docs/incremental-backend-contract.md` is requirements only.

**Trigger/impact:** Repeated loads can reread the same subset, miss other rows or observe changed values. Upsert alone cannot establish completeness, late-commit safety or delete reconciliation. Small explicitly bounded samples are an intended use; treating them as full sync would be incorrect.

**Suggested mitigation:** certify source-specific snapshot/paging and initial-to-incremental semantics; persist in-flight versus committed progress separately; block unsupported incremental modes.

### R11 — P2: insufficient durable audit and operational diagnostics

**Evidence:** `Handler.log_message` is disabled; generic exception branches return sanitized errors without server diagnostics; jobs are memory-only; P.audit/activity are client memory; audit table exists only in synthetic Registry.

**Trigger/impact:** A driver/write failure or unauthorized action investigation lacks correlated durable actor/run/attempt records. Sanitization is valuable but currently removes operational visibility too.

**Suggested mitigation:** structured redacted server events with correlation IDs, authenticated actor, source/definition refs, timings and counters; safe metrics/alerts and retention. Never log credentials, complete query parameters or row payloads by default.

### R12 — P2: admission controls do not cover all HTTP/concurrency paths

**Evidence:** `ThreadingHTTPServer` has no configured request-thread cap/read timeout; API gate is per Service; `profile_statuses/local_target_status/local_target_preview` read mutable session/profile state without one service-level critical section. Catalog/target stores have their own locks.

**Trigger/impact:** Concurrent local requests may block on storage or race profile mutation; adding API processes multiplies source concurrency because gates are not distributed. A slow local body read can occupy an HTTP thread. No stress/penetration test was performed.

**Suggested mitigation:** bounded HTTP hosting/timeouts, coherent state snapshots, centralized durable admission before multiprocess workers, per-source connection budgets. Current one-reader policy should remain until replaced deliberately.

### R13 — P2: local data/cache growth lacks retention and byte budgets

**Evidence:** `CatalogStore` retains historical snapshot/object rows with no pruning routine; `current_snapshot` materializes all metadata; browser loads entire catalog; warehouse files have no retention/encryption configuration in code.

**Trigger/impact:** Large/repeated catalogs consume disk/RAM, and raw locally copied records persist without application-managed retention. OS encryption/backup controls are Unknown, not assumed absent.

**Suggested mitigation:** agreed data classification, cache retention, storage/response byte caps, paged cache retrieval, target backup and ownership policy. Keep metadata and business data access controls explicit.

### R14 — P2: approval staleness and JOIN evidence are client-only

**Evidence:** `recordDatasetReview` passes the same current revision twice; `approveDatasetDefinition` checks profile revisions, not immutable metadata fingerprints; `approveDatasetRelationships` sets a boolean; `datasetGrainSuggestion` is heuristic.

**Trigger/impact:** Different clients or changed metadata cannot be reliably coordinated. An approved-looking plan has no server evidence that joins preserve the declared grain. No current live ETL consumes the plan, so this is a governance blocker rather than an observed corrupted published Dataset.

**Suggested mitigation:** server-side optimistic concurrency and immutable catalog/pipeline versions; typed JOIN/cardinality validation and owner review before execution authority.

### R15 — P3: verification and documentation are not portable or fully aligned

**Evidence:** browser suites require hardcoded external Playwright paths; npm test loads four unit/source suites only; `scripts/start-source-spike.ps1` references an absent usage doc; source module headers/API docs lag extract_load behavior; render/page functions are repeatedly overridden.

**Trigger/impact:** A receiving team can mistake mock/source-string checks for browser integration or follow stale startup guidance; UI changes are difficult to trace.

**Suggested mitigation:** document actual test tiers/prerequisites, align runtime contract and docs, separate UI modules by responsibility in a later authorized change. No dependency installation or refactor was performed.

## Review coverage and limits

Authentication/RBAC, source access, secret lifecycle, generated SQL boundaries, timeout/pooling, concurrency, recovery, storage and observability were reviewed from active source. No durable secret adapter exists; `UnavailableSecretStore` deliberately refuses resolution/persistence. Current oracle_factory uses fresh connections rather than a pool, which is acceptable for a one-reader pilot but needs explicit future capacity/lifecycle decisions.

No external dependency advisories, production deployment, OS security policy, real service metrics, browser exploit, Oracle execution plan or recovery-under-crash result was verified. Future LLM hallucination/GPU risks are design requirements in [06](06-sql-etl-ai-mapping-audit.md), not present runtime incidents.
