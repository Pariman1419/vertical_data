# SPICE integration readiness

Audit date: 2026-10-26. Repository discovery only. **SPICE integration: NOT IMPLEMENTED. Actual SPICE service: NOT VERIFIED.** No external service was queried or service credentials accessed.

## Existing integration evidence

`README.md` explicitly calls this a handoff for SPICE review and states there is no SPICE adapter/API integration. References to SPICE in README/blueprint/summary describe product intent. `backend/contracts.ts` describes an engine-neutral Connector, not a SPICE implementation. Real backend imports and routes are limited to Oracle, SQLite, sessions and standard-library hosting. Frontend `realApi` calls same-origin `/api/` routes only.

The inspection searched active source, package/requirements files, scripts, configuration filenames and docs for SPICE, Flight, ODBC, JDBC, pooling, SQL query adapters and AI providers. Generated dist/analysis archives were not counted as additional integrations. There is no SPICE-specific configuration, client dependency, authentication provider, metadata adapter or query executor in the active application.

| Capability | Existing source | SPICE assessment |
|---|---|---|
| Service configuration | `.env.example` has PORT only; `server.py:main` local paths/port | NOT IMPLEMENTED |
| SQL/ODBC/JDBC/Arrow Flight | No SPICE client/driver or protocol implementation | NOT IMPLEMENTED; service protocol Unknown |
| Metadata catalog | `OracleReadAdapter.discover_catalog_page/discover_table`; `CatalogStore` | Oracle-specific; not SPICE metadata |
| Query execution | Hardcoded Oracle dictionary/sample/extract SQL | No SPICE execution adapter |
| Pooling | `oracle_factory` opens fresh connections | No SPICE pool/lifecycle |
| Authentication | Local passphrase/session and in-memory Oracle config | No SPICE identity/delegation/token flow |
| Pagination | Oracle keyset metadata pages; capped source rows | Not evidence of SPICE cursor/resume/streaming |
| Timeout/retry | Oracle call/connect deadlines, retry_count=0 | No SPICE timeout/cancel/retry contract |
| Limits | Oracle row/page/column/time limits | No SPICE quotas, byte limits or concurrency budget |

## Where SPICE should fit — recommendation, not existing behavior

Use one data-access contract for capability discovery, source identity, scoped catalog access, bounded preview and batch extraction. A SPICE adapter can implement verified capabilities; the direct Oracle adapter can remain an explicitly authorized alternative. The Web API should not contain protocol-specific query logic or pass user credentials to the browser as a shortcut.

Potential reuse: `ConnectorDescriptor`, `DiscoveryScope`, `DiscoveredObject`, `Connector` and source revision concepts in `contracts.ts`; `ReadBudget`/identifier policy patterns; metadata snapshot repository concepts. These need explicit schema/version alignment and SPICE semantics. Oracle ALL_OBJECTS/ALL_TAB_COLUMNS queries and Oracle cursor fields cannot be reused unchanged for SPICE.

Avoid duplication: if SPICE owns source credentials, connection pooling and catalog discovery, U-ETL should reference SPICE connection IDs and consume its catalog, rather than independently scraping the underlying source and maintaining contradictory connection status. U-ETL's cache can hold versioned snapshots for reproducibility, with freshness/permission rules. U-ETL's ETL run ID, Dataset approval and target publication remain separate concepts from a SPICE query ID.

Do not silently fall back from SPICE to direct database access after an authorization/availability failure. A direct path needs its own approved capability/scope and audit record. Unsupported capabilities should block clearly. Choice of routing policy and failure behavior is an open architecture decision.

## Required verification with actual service owners

| Question / evidence required | Decision affected |
|---|---|
| What exact product/service does SPICE mean here, and what deployed version/API contract applies? | No assumption that a similarly named public platform is the organization's service |
| Supported protocols, endpoint shape, SDK/driver/version and sandbox? | Adapter transport and deployment dependencies |
| Service identity, user delegation, scopes, tenant isolation, secret ownership and rotation? | Authorization and unattended worker authentication |
| Is access virtualized/federated, cached or materialized? How are sources/catalog objects identified/versioned? | Consistency, freshness, lineage and cache identity |
| Are columns, precision/scale, PK/FK, view definitions and permissions exposed? | Mapping evidence and target typing |
| Can rows be streamed or paged with bounded memory? What are cursor lifetime/order/resume guarantees? | Large extraction and restart recovery |
| Is a consistent source boundary/snapshot available across pages? | Initial handoff and repeatable retry |
| Which SQL dialect, bound parameters, read-only query controls and query cancellation exist? | SQL ETL editor/preview validation |
| What are row/byte/time/concurrency limits, backpressure and query-cost controls? | Capacity and admission budgets |
| Does bulk extraction have a supported contract distinct from interactive query? | Whether SPICE can serve ETL extraction at all |
| Are change streams/CDC, updates/deletes and commit positions available? | Incremental strategy; absent evidence means unsupported |
| Does SPICE own jobs, schedules, retries or target writes, and under what guarantees? | Lifecycle ownership; never inferred from query support |
| Errors, retryable categories, idempotency, query IDs, metrics and audit linkage? | Recovery and observability |
| Target support, transaction/publication semantics, availability/SLA and network topology? | End-to-end consistency and operational design |

All above are **Unknown / NOT VERIFIED**. Generic SQL access does not establish bulk throughput, CDC, orchestration or atomic target publishing. `docs/incremental-backend-contract.md` already requires commit-aware source strategy evidence; the same requirement applies if access is virtualized through SPICE.

## Readiness verdict

The repository offers useful boundary vocabulary, but no operational integration. Next deliverable should be a jointly reviewed capability/identity/consistency contract and an approved sandbox verification plan. No implementation, connector installation or live verification was attempted in Phase 0.
