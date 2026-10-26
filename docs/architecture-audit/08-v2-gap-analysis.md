# U-ETL v2 gap analysis

Audit date: 2026-10-26. Current-state evidence is source-based; target capabilities are proposals, not confirmed implementations or approved designs. Runtime NOT VERIFIED. See [00](00-executive-summary.md).

Priority in this matrix is sequencing for v2: P1 = prerequisite/high consequence, P2 = next capability, P3 = later polish. Security finding severity is separately defined in [07](07-security-performance-risks.md).

## Current versus target

| Capability | Current State | Evidence | Gap | Reuse Potential | Priority |
|---|---|---|---|---|---|
| Web Control Plane | Partial: working local shell/API, single owner, browser business state | `app.js:M/page`; `server.py:handler_for`; `prototype.js:activeDataset*` | Shared identity/RBAC, authoritative versioned state, durable API contracts, bounded production hosting | Existing screens/workflows, validation concepts, API client patterns | P1 |
| SPICE Adapter | Planned — NOT IMPLEMENTED | README; no SPICE imports/dependencies/routes | Verify actual service; transport/auth/capability/cursor/limits adapter | ConnectorDescriptor/DiscoveryScope design vocabulary; cache concepts | P1 contract, P2 implementation after verification |
| Direct Connector | Partial: Oracle test/catalog/sample/bounded extract; other engines profile-only | `oracle_factory`; `OracleReadAdapter`; `SCALAR_TYPES` | Stable batch/stream interface, typed results, source policy, cancellation, pool/admission design; additional engines conditional | Oracle SQL/identifier/deadline/error patterns and mock tests | P1 |
| ETL Worker | Partial across repo: real thread in API; independent synthetic CLI only | `Service.pool/_run`; `foundation/worker.py` | Independently running worker, authorized credentials, durable attempts/staging/publication | Synthetic lease/fencing/cancel tests and adapter functions | P1 |
| Durable Job Queue | Not implemented for live jobs; synthetic Registry only | `Service.sessions`; `Registry.enqueue/claim` | Atomic enqueue, leases, scope locks, retry identity, restart recovery and queue visibility | Registry state-machine patterns; not production schema as-is | P1 |
| SQL ETL Editor | Planned — NOT IMPLEMENTED | No editor or SQL route; `datasetRequestPanel` description field | Dialect-aware editor, typed parameters, safe preview, query versions/approval, execution plan | Read budgets/session safety; Dataset definition concepts | P2 |
| Local LLM Mapping | Planned — NOT IMPLEMENTED; deterministic matching is real | `rankDatasetField`; `AiCandidateProvider` design type | Isolated service, retrieval/policy/output validation, model/prompt versions and evaluations | Rule baseline, ambiguity handling, evidence UI | P2 |
| Dataset Registry | Partial UI, no durable live registry | `submitDatasetRequest/approveDatasetDefinition/createDatasetSimulation` | Durable immutable request/definition/pipeline versions, ownership, lineage and lifecycle APIs | Dataset domain fields and draft UI | P1 |
| Approval Workflow | Partial: browser checks/rationale/grain; no server authority | `applyDatasetReview/datasetDefinitionReadiness`; `recordDatasetReview` | Authenticated reviewer, revision conflict handling, immutable evidence and execution gate | Existing blocker and ambiguity rules/tests | P1 |
| Incremental Loading | Mock for product; requirements only for live source | DemoSync; `incremental-backend-contract.md`; `extract_bounded` | Source-specific commit-aware boundary, initial handoff, update/delete policy, checkpoints vs watermarks, backfill | Acceptance cases and synthetic scenarios | P1 design; enable only after certification |
| Monitoring | Partial: session polling and last-load status | `Service.job`; `local_target_status`; browser activity | Durable attempts, progress/counts, metrics, logs/traces/alerts and safe operator controls | Polling UI, safe error categories, table summary | P1 basic; P2 dashboards |
| Recovery | Partial PK upsert; mock/synthetic retry/cancel/lease semantics | `load_rows`; Registry; DemoSync | Crash-safe stage/replay, pinned boundaries, atomic publish/progress, idempotent attempts, restore procedure | Existing synthetic failure tests and incremental contract | P1 |

Scheduling is a separate missing cross-cutting capability: the cadence saved by `createDatasetSimulation` is a session preference, not a schedule. It depends on durable jobs, unattended credentials, timezone/missed-run policy, scope locks and operator authorization. No cron/dispatcher was found.

## Reuse versus redesign

| Module / asset | Recommended treatment | Reason / limitation |
|---|---|---|
| Existing default screens and wizard | Retain product flow; incrementally connect to authoritative APIs | Users already have connection/catalog/request/review vocabulary; browser memory cannot be authority |
| `dataset-workflow.js` | Retain labelled deterministic baseline and rule test cases | Useful exact/alias/ambiguity behavior; improve language/type/evaluation limits deliberately |
| `real-source-ui.js` | Reuse interaction behavior; replace transport/contracts incrementally | Current polling/session/global coupling assumes local service and memory jobs |
| `oracle_read.py` | Adapt into explicit connector boundary | Good read-only/bind/deadline patterns; `_query` must not serve as large-data streaming implementation |
| `read_budget.py` | Reuse budget concepts/validation; replace single-instance admission where needed | Sample row and timeout limits are useful, but no bytes/distributed policy |
| `CatalogStore` | Reuse snapshot/head/DDL invalidation concepts, assess repository implementation | Add recovery/retention/freshness/permissions and shared deployment strategy |
| `SQLiteTargetStore` | Keep as bounded local pilot adapter after integrity decisions | Not a shared target abstraction; atomicity/precision/schema issues block generic production reuse |
| `foundation/core.py` | Reuse state-machine and acceptance examples; redesign production schema/auth | Explicitly synthetic-only, fixed fixture/checkpoint range, bundles only revision IDs |
| `contracts.ts` and API/incremental docs | Reconcile into a versioned executable contract specification | Design types differ from real Python payloads and do not include full SQL pipeline semantics |
| DemoSync and Node/Python tests | Keep isolated fixtures and expand focused integration acceptance later | Demonstrate intended behavior, not real snapshot/CDC correctness |
| `server.py` hosting/session model | Retain as pilot; harden/replace hosting and auth for shared control plane | Standard-library local server and owner passphrase are not shared platform governance |
| Windows launcher/static build | Keep for local pilot/onboarding where useful | No deploy topology, managed secrets, service supervision or HA |

## Three architecture approaches

| Approach | Benefits | Costs / risks | Fit |
|---|---|---|---|
| 1. Extend current monolith | Least immediate code movement; convenient local pilot; existing Python/JS retained | Durable queue/registry/auth still needed; ETL/AI compete with HTTP resources; difficult worker-independent scaling/restarts; process memory isolation absent | Reasonable only for explicitly bounded manual pilot; fails the proposed independent-engine boundary if retained long term |
| 2. Separate ETL engine and AI mapping, retain Web/API | Reuses UI/Oracle concepts while removing heavy work from API; independent worker/inference budgets; one governance owner; staged migration | Needs durable registry/queue, secret references, service authentication and explicit publication protocol; current API still needs substantial hardening | **Recommended least disruptive viable v2 direction** |
| 3. Fully decompose into independent services | Fine-grained ownership/scaling and deployment boundaries | Highest operational complexity; more contracts, failure modes and distributed transactions before volume/team needs are known; broad rewrite risk | Defer until measured scale, ownership or isolation requires further decomposition |

Option 2 means a modular control plane plus independently running ETL/inference processes. It does not require separate services for every catalog, dataset or approval table, nor a broker/vector database merely because they are common platform components. Registry and queue technology remain open until capacity and deployment constraints are known.

## Top ten architecture gaps

1. No live durable job/attempt queue or independent ETL process (`Service.submit/_run`).
2. No server-owned versioned Dataset/Pipeline registry (`activeDataset*`, design-only contracts).
3. No shared identity, object authorization or enforceable approvals (`P.role`, local-owner Service).
4. No verified SPICE adapter/capability contract (README, actual imports/routes).
5. No bounded-memory batch data path or byte quotas (`_query/extract_bounded`).
6. No atomic target publication/progress or certified recovery (`load_rows/record_source_status`).
7. No SQL authoring, versioning, validation or shared visual/SQL execution definition (API inventory, contracts).
8. No isolated Local LLM provider/output governance/model lineage (`rankDatasetField`, AiCandidateProvider type).
9. No certified incremental strategy, staging, delete handling or initial handoff (`extract_bounded`, incremental contract).
10. No durable monitoring/scheduler/unattended secret lifecycle (`Service.jobs`, simulation cadence, UnavailableSecretStore).

## Refactor versus rebuild verdict

Use a controlled incremental redesign around authoritative state and execution boundaries, not a full UI rewrite. Preserve interaction flows and adapter/test knowledge. Replace browser-owned governance and in-process execution assumptions. Build a single bounded, approved definition-to-publish acceptance slice before adding more engines, autonomous AI behavior or scheduling. This is a recommendation only; no refactor/rebuild/migration was started.
