# Dataset Request / Candidate / Definition API contract — design only

Blueprint checked: **v1.3**, 9 October 2026. This file specifies future Backend contracts; it does not claim these routes or durable records exist.

## Implemented API boundary (local Oracle read-only spike only)

`backend/spike/server.py` currently implements `POST /api/login`, `GET /api/session`, `POST /api/test`, `POST /api/catalog`, `POST /api/discover`, `POST /api/sample`, `GET /api/jobs/{id}`, and `POST /api/logout`. These use a local single-owner HTTPS session and memory-only jobs/Worker thread. Owner-reported live Oracle Test/Discovery/Sample covers `BIDPITDBA.DP_WIP_DATA`; the new broad catalog code is tested with fake adapters only. There is no persistent Dataset Request API, Candidate service, approval API, real Registry, AI service, Target or ETL endpoint.

The TypeScript domain interfaces in `backend/contracts.ts` are compile-time design types only. A Python offline SQLite Foundation harness exists separately and processes synthetic records; it is not the spike's real-source service.

## Multi-engine connector direction (design / profile UI only)

The product must not be Oracle-only. `DatabaseEngine` is an engine-neutral contract (`oracle`, `sqlserver`, `postgresql`, `mysql`, `mariadb`) and each connector declares its adapter version and capabilities. This is a design boundary, not evidence those adapters are installed. At present, only the local Oracle Source Test/Discovery/bounded Sample spike exists. Other engines are profile-only choices with no credentials accepted and no Test/Connect path. The former SQL Server Demo fixture is not a SQL Server connector. Target engine support is also unimplemented and requires a separate confirmed Target decision.

Before another adapter is implemented, confirm vendor/version, Source or Target use, authentication/runtime identity, TLS/network policy, driver deployment/licensing, test endpoint, permissions and bounded-read/write acceptance. A connector must fail closed when its engine/capability is unavailable; the UI must not infer success from profile configuration.

## Design invariants

- Dataset Request is the entry point; Source connection setup/discovery is selected from the request workflow. Request/Definition versions are immutable snapshots after use.
- Every mutation authenticates/authorizes server-side, accepts an idempotency request ID and expected revision/ETag, and returns `409 revision_conflict` if stale. UI role state is not authority.
- Candidate sources identify Source config revision and discovery metadata snapshot; no profile/sample data is used unless a separate scoped profile reference and budget were explicitly approved.
- **Owner clarification after v1.3:** AI-assisted schema/table/column ranking is a required target capability, but the provider remains disabled until its runtime and metadata-egress policy are approved. Deterministic ranking may remain a labelled fallback, not a substitute for the requested AI capability. Provider output must identify version/evidence and remains a recommendation requiring human review. Never pass credentials or row samples; never execute model-generated SQL.
- Discovery scope is all catalog metadata granted to the configured Source identity, with future workspace/user exclusions. Oracle spike uses paged `ALL_OBJECTS` for TABLE/VIEW/MATERIALIZED VIEW and keyset cursor (OWNER, OBJECT_NAME, OBJECT_TYPE, OBJECT_ID); no DBA catalog, full count or row reads. It has not yet been live-verified across schemas. Selected-object metadata is a separate call; row sample is another explicit bounded call.
- Matching Score is an uncalibrated ranking value with explanation, not a probability/percent. Semantic evidence, datatype compatibility and join confidence are separate fields.
- Field review is auditable and revision-bound. Override/Reject/No suitable match requires rationale. Ambiguous candidate cannot be silently approved. Request/source/dictionary/provider revision changes mark candidates/reviews/definitions stale.
- Dataset Definition contains request/source snapshots, business fields and mappings, grain/join plan, filters, quality rules, evidence/reviewer, dictionary/provider versions, Target/generation and refresh policy. Approval requires all configured blockers resolved. It does not itself publish data.
- No arbitrary SQL from the UI/AI. Catalog object names come only from the driver's visible `ALL_OBJECTS` results; selected identifiers are validated/quoted and values are bound. Source stays read-only.

## Proposed routes (not implemented)

| Route | Purpose | Optimistic concurrency / output |
|---|---|---|
| `POST /api/dataset-requests` | Create a versioned request with name, purpose, requested business fields, Source refs, time/filter request, grain, Target preference | Idempotency key; returns request ID/revision/status; validates field list and source scopes |
| `GET /api/dataset-requests/{id}` | Read request and current state | Returns current revision and staleness reason |
| `PATCH /api/dataset-requests/{id}` | Edit request into a new revision | `If-Match` revision; invalidates candidate/review/definition outputs |
| `POST /api/dataset-requests/{id}/candidate-evaluations` | Rank requested fields against selected discovery snapshots | Async job receipt if expensive; includes provider/dictionary versions, evidence refs and uncalibrated points |
| `GET /api/candidate-evaluations/{jobId}` | Poll ranking job/result | Sanitized state and candidate list; no sample values in logs/job summaries |
| `POST /api/dataset-requests/{id}/field-reviews` | Approve/override/reject/no-suitable-match a requested field | Request revision + candidate ID/evidence + reviewer/rationale; 409 if stale; audit event |
| `POST /api/dataset-requests/{id}/definitions` | Materialize an immutable draft Dataset Definition | Captures all source/config/dictionary/provider/review revisions; returns definition version and readiness blockers |
| `POST /api/dataset-definitions/{id}/approval` | Approve a Definition version | Role, revision, no unresolved blockers, reviewer and time; immutable approval/audit |
| `GET /api/dataset-definitions/{id}` | Read immutable version/readiness | Stale/approved state and lineage refs |
| `POST /api/dataset-definitions/{id}/preview` | Future bounded preview/quality calculation | Only approved input snapshot or an explicit review-preview policy; target generation scoped; async job |

## Candidate response (illustrative shape, not a live API response)

```json
{
  "requestId": "opaque-id",
  "requestRevision": 2,
  "provider": {"id": "metadata-rule-baseline", "version": "starter-template-1", "isAi": false},
  "requestedField": "Lot number",
  "status": "ambiguous",
  "candidates": [{
    "sourceId": "opaque-source-id", "schema": "authorized-schema", "table": "selected-table",
    "column": "BATCH_NO", "sourceType": "VARCHAR2",
    "matchingScore": {"value": 58, "unit": "ranking_points", "calibrated": false,
      "explanation": "Curated alias; domain ambiguity lowers rank; this is not probability."},
    "datatypeCompatibility": "unknown",
    "joinConfidence": "not_assessed",
    "evidence": [{"kind": "dictionary_alias", "snapshotId": "opaque-discovery-id", "sampleRowsUsed": false}],
    "ambiguity": ["Could mean lot, production batch or job; owner confirmation required."],
    "decision": "pending"
  }]
}
```

## Failure and invalidation

Errors use stable codes (`unauthenticated`, `forbidden`, `invalid_request`, `revision_conflict`, `source_scope_denied`, `candidate_stale`, `definition_blocked`, `unsupported_strategy`, `rate_limited`) and sanitized user-facing messages. Do not return raw driver errors, secret values, raw data rows or credential-bearing connection strings.

Any source endpoint/auth/config revision, selected table/discovery snapshot, request fields/time/filter/grain, dictionary/provider version, or target/generation change invalidates downstream candidates/review/preview/approval as appropriate. Historical Run/Definition keeps its original referenced versions. Mapping changes do not silently backfill published data.

Existing incremental/load API remains governed by `incremental-backend-contract.md`: immutable run boundaries, commit-late completeness, initial handoff, staging checkpoint vs committed watermark, atomic publish/recovery, idempotency, durable quarantine/reprocess and explicit unsupported Incremental. Scheduler/CDC remain later roadmap.
