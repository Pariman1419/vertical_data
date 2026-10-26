# Frontend and API inventory

Audit date: 2026-10-26. Static source findings; all runtime behavior NOT VERIFIED. Paths below are relative to repository root. Status definitions: [00](00-executive-summary.md).

## Navigation and feature inventory

Default menu: `Database Connection` (`sources`), `U-ETL Database` (`copies`), `AI Data Bridge` (`create`), `Data Set` (`datasets`). `activity` is reached from Data Set. The masthead uses U-ETL Data Bridge branding; there is no additional independent DataBridge backend. Evidence: `app.js:M/page/navPage/layout`.

`?demo=1` exposes Overview, Data Sources, Data Mapping, Relationships, Transform & Load, Data Explorer, Data Quality, Run History and Settings. The final `prototype.js:render` redirects those legacy pages to `create` outside demo mode. Earlier function declarations are overridden later; assessing `app.js` alone would overstate functionality.

The following 24 rows are the counting units used in all audit summaries. Implemented means the narrow source behavior exists, not production completeness.

| ID / Feature | UI | Backend | Database | Status | Evidence |
|---|---|---|---|---|---|
| F01 Application shell/navigation | Four default pages, activity and demo menu | Static serving | None | Implemented | `app.js:M/DEMO_M/page`; `index.html` |
| F02 Connection profile management | Create/edit/remember non-secret profile | Test runtime config only; no profile CRUD registry | Browser localStorage; active backend memory | Partial | `prototype.js:saveConnection/persist`; `Service.submit` |
| F03 Local application authentication | Sign in/out | Passphrase/session/CSRF | Memory only | Implemented | `realSourceLogin`; `Service.login/session`; logout caveat in risk R08 |
| F04 Oracle connection test | Real HTTPS test controls | `/api/test` | Read-only Oracle identity query | Implemented | `realSourceTestProfile`; `OracleReadAdapter.test_connection` |
| F05 Oracle profile activation/disconnect | Controls and status | `/api/profile/connect`, `/disconnect` | Config in memory; no persistent Oracle handle | Implemented | `realSourceConnectProfile`; `Service.connect_profile/disconnect_profile` |
| F06 Catalog discovery/filtering | Load pages then client filtering | `/api/catalog`, `/api/catalog/cache` | Oracle dictionary; SQLite snapshot cache | Implemented | `realSourceLoadAllCatalog`; `discover_catalog_page`; `CatalogStore` |
| F07 Object structure/keys | Checked-object discovery and row structure preview | `/api/discover` | Oracle dictionary; SQLite object metadata | Implemented | `realSourceDiscoverChecked/realSourcePreviewObject`; `discover_table` |
| F08 Column-name object search | Auto-select all/any names | `/api/match_columns` | Oracle ALL_TAB_COLUMNS; cached catalog intersection | Implemented | `realSourceAutoSelectByColumns`; `find_objects_by_columns`; `Service._run` |
| F09 Source row sample | Explicit limited columns/acknowledgment | `/api/sample` | Oracle rows; result memory | Implemented | `realSourceReadObjectPreview/realSourceSample`; `adapter.sample` |
| F10 Local extract/load | Bounded manual load | `/api/extract_load` | PK upsert in local SQLite | Partial | `runLocalExtractLoad`; `Service._run`; `load_rows` |
| F11 Stored-data preview | View data | `/api/local-target/preview` | Registered local SQLite table, <=100 rows | Implemented | `viewStoredData`; `local_target_preview`; `preview` |
| F12 Load groups/order | Save/edit group; sequential run | Separate extract job per table; no group API | Group in localStorage; individual data in SQLite | Partial | `runLocalCollectionGroup/saveCollectionLoadGroup` |
| F13 Dataset request | Name, purpose, fields, source refs, grain/time/filter descriptions | None | Browser memory | Partial | `submitDatasetRequest`; `activeDatasetRequest` |
| F14 Deterministic candidate mapping | Candidates, evidence, ambiguity | None | Browser metadata input | Partial | `dataset-workflow.js:rankDatasetField/buildDatasetReview` |
| F15 Mapping/definition approval | Review decisions, rationale, grain confirmation | None | Browser memory; demo mappings in localStorage | Partial | `recordDatasetReview/approveDatasetDefinition`; `applyDatasetReview` |
| F16 Dataset creation/publication | Preview/Publish wizard | None | Session-only simulated item | Mock | `syntheticPreviewMarkup/createDatasetSimulation/datasets` |
| F17 Analytics target profiles | Form and target preference | No connector test/write | Session-only profile objects | Partial | `saveTargetProfile`; `window.datasetWorkflowTargets` |
| F18 Incremental/full refresh/recovery | Demo controls and timers | No live implementation | Synthetic arrays/localStorage only | Mock | `demo-sync.js:DemoSync`; `prototype.js:startSync` |
| F19 Monitoring/activity/history | Real polling/last-load plus simulated activity | `/api/jobs/{id}`, `/api/local-target/status` | Real jobs in memory; last load in SQLite | Partial | `Service.job`; `activity/refreshLocalTargetStatuses` |
| F20 User management/RBAC | Demo role selector; no user CRUD page | No real user/role endpoints | None; synthetic roles separate | Mock | `prototype.js:P.role/canEdit/canRun`; `core.py:authorize` |
| F21 Settings/policies | Legacy demo settings | No settings API | Some demo localStorage preferences | Mock | `prototype.js:settings/persist`; final `render` redirect |
| F22 SQL ETL authoring/query preview | No SQL editor; business filter is description only | No SQL execution endpoint | No SQL version registry | Planned — NOT IMPLEMENTED | `datasetRequestPanel`; `server.py:do_POST`; `contracts.ts` lacks executable SQL definition |
| F23 SPICE data access | No operational integration controls | No adapter | None | Planned — NOT IMPLEMENTED | `README.md`; imports/routes; report [04](04-spice-integration-readiness.md) |
| F24 Local LLM mapping | AI-labelled wizard explicitly says AI not connected | No inference provider | None | Planned — NOT IMPLEMENTED | `datasetWizardChrome`; `AiCandidateProvider` design type |

Counts: **9 Implemented + 8 Partial + 4 Mock + 3 Planned = 24**. Seventeen contain real executable behavior of some kind; four simulate the principal capability; three have no implementation. Foundation harness capabilities are not extra user features.

## Shared API rules

Authoritative code: `backend/spike/server.py:handler_for/Handler.do_GET/Handler.do_POST` and `backend/spike/service.py:Service`.

- All API requests require exact local Host and loopback client checks. All POSTs require same Origin, JSON content type and body size 1..16,384 bytes.
- `POST /api/login` is the only API without an existing authenticated session; other APIs require the `utl_session` cookie. Other POSTs also require `X-CSRF` matching the session. No real per-role/per-object authorization layer exists.
- Login cookie is Secure/HttpOnly/SameSite=Strict, Max-Age=1800. Sessions expire in memory; successful profile activation/submission renews server expiry. Cookie expiry is not refreshed on every action.
- JSON errors use `{error: message}`. Explicit statuses include 400 invalid request, 401 session/login, 403 guard/CSRF/column rejection, 409 busy/prerequisite conflict, 413 size, 415 content type, 429 login throttling, 503 absent local target and generic 500.
- Success for action submission is HTTP 202 `{job_id,state:'running'}`. Failed Oracle work is reported later in HTTP 200 job polling with `state:'failed'`, not an ETL success response.

## Implemented API inventory: 15 method/route pairs

In the Auth column, S = session and local Host/client guard; M = S plus same-Origin, JSON-size and CSRF mutation checks. L = local guard, same-Origin and JSON-size checks without an existing session. These are local-owner controls, not RBAC.

| # | Method / route | Request contract | Success response / purpose | Auth | Implementation / dependencies | Blocking and concurrency |
|---|---|---|---|---|---|---|
| 1 | POST `/api/login` | Exactly `{passphrase}`; value excluded from reports | 200 `{csrf}` plus session cookie | L | `do_POST` → `Service.login`; scrypt, memory sessions | Synchronous hash under service RLock; 5 attempts/min/process; login replaces idle owner session, rejects busy session |
| 2 | GET `/api/session` | Cookie; no body | 200 `{csrf,discovery_scope:'all_granted_catalog',profiles}`; profile tested/connected/revision flags | S | `do_GET` → `session/profile_statuses` | Small synchronous memory read; profile iteration not fully locked |
| 3 | POST `/api/logout` | UI sends `{}`; handler does not strictly validate fields | 200 `{credential_state:'credentials_required'}`; clears cookie/session | M | `do_POST` → `logout` | Synchronous; 409 if work busy; UI currently swallows failure |
| 4 | POST `/api/profile/connect` | Exactly `{profile_id}` | 200 `{profile_id,connected:true}` | M | `connect_profile`; previously tested config in memory | RLock; logical activation, no network test or retained DB connection |
| 5 | POST `/api/profile/disconnect` | Exactly `{profile_id}` | 200 `{profile_id,connected:false}` | M | `disconnect_profile` | RLock; 409 for active same-profile job, removes profile credentials/state otherwise |
| 6 | POST `/api/test` | Optional `profile_id`, exact `{config,timeout}`; exact legacy flat config+timeout also accepted | 202 receipt; eventual identity/database/version, database_connected true, simulation/publish flags | M | `submit` → `_run` → `oracle_factory` → `test_connection` | Oracle work in single executor thread; admission rejects overlap; config validation/hash/source state in API |
| 7 | POST `/api/catalog` | Optional `profile_id`; `{cursor,page_size,timeout}`; cursor null or `{owner,name,kind,object_id}`, page 1..100 | 202; job result objects, next_cursor, page_size, limits; final page adds snapshot_id/refreshed_at/object_count | M | `submit/_run` → `discover_catalog_page`; `CatalogStore.begin_refresh/append_page/complete_refresh` | Oracle/page persistence in worker; begin_refresh synchronous under service lock; serialized local reads, not distributed-safe |
| 8 | GET `/api/catalog/cache` | Query `profile_id`; tested and connected profile | 200 available snapshot with objects and metadata or `{available:false,objects:[],metadata:[]}` | S | `catalog_cache` → `current_snapshot`; hydrates profile metadata | Synchronous complete SQLite snapshot read/JSON decode under locks; unbounded total response size |
| 9 | POST `/api/match_columns` | Optional `profile_id`; `{keynames,match_mode,timeout}`; 1..20 simple names, mode all/any | 202; matched objects/columns, truncated flag, normalized names/mode, catalog timestamp/limits | M | `submit/_run` → `find_objects_by_columns`; cached catalog intersection | Single worker; <=10,000 matched dictionary rows; complete cache materialization adds memory/CPU |
| 10 | POST `/api/discover` | Optional `profile_id`; `{schema,table,timeout}` | 202; object/columns/keys/foreign_keys tuple arrays, limitations | M | `submit/_run` → cache lookup or `discover_table`; `save_metadata` | Worker; may return cached metadata; up to 1,000 entries per dictionary result; no automatic cache freshness guarantee |
| 11 | POST `/api/sample` | Optional `profile_id`; `{schema,table,timeout,sample_rows,batch_size,columns,budget_ack}` | 202; columns/rows/sample_count, sample profiles, flags/limitations | M | `submit/_run` → `sample`; discovered scalar-column validation | Worker; 1..100 rows, batch 1..25 and <= rows, <=200 selected cols, explicit ack; results retained in memory |
| 12 | POST `/api/extract_load` | Optional `profile_id`; `{schema,table,timeout,row_limit,columns,budget_ack}` | 202; source/columns/primary_keys/rows_received/rows_written/target_rows/last_load_at/row_limit/target/limitations | M | `submit/_run` → `extract_bounded` → `load_rows` → `record_source_status` | Worker does read and write; 1..2,147,483,647 rows, <=200 caller cols before auto-added PK; not streaming or crash-idempotent |
| 13 | GET `/api/jobs/{id}` | Session-scoped job ID; no body | 200 job including action/profile/schema/table/revision/limits/state/result/timestamps; failed jobs include sanitized error | S | `job`; in-memory session dictionary | RLock; at most 20 retained jobs; no global/history/list API; repeated polls resend full result |
| 14 | GET `/api/local-target/status` | Cookie; no body | 200 `{tables:{profile|schema|name: {last_load_at,rows_received,target_rows}}}` | S | `local_target_status` → `target_store.statuses` | Synchronous SQLite read/mapping; store lock; session/profile iteration not fully service-locked |
| 15 | GET `/api/local-target/preview` | Query profile_id/schema/object; limit defaults 100, range 1..100 | 200 schema/object/target_rows/last_load_at/columns/rows/preview_limit | S | `local_target_preview` → `statuses/preview`; hashed physical table | Synchronous SQLite; serialized with writes by store RLock, so HTTP read may wait for load; no streaming |

`config` field names are host, port, identifier_type, identifier, username, password, protocol, tcp_ack and readonly_ack. No values are reproduced here. Simple host syntax; port 1..65535; Service Name/SID; tcp/tcps; required read-only acknowledgement; explicit TCP acknowledgement. Per-action timeout is 1..30 seconds. Source protocol TCP is therefore allowed under an acknowledgement, not always TLS.

Other `/api/*` POST paths reach `submit` but are rejected as unsupported, not implemented endpoints. Only test/catalog/match_columns/discover/sample/extract_load are accepted actions. Static document/asset serving is excluded from the 15 count. Query strings are parsed only on the relevant GET branches; the handler is not a general REST router.

## End-to-end workflow traces

1. **Connection test:** HTTPS form → `realSourceTestProfile` → `realSourceRun('test')` → POST test → `config_validate`/`submit` → `_run` → fresh Oracle connection, read-only transaction, identity SELECT → memory job → GET job polling. Then `realSourceConnectProfile` calls profile/connect, which only marks a tested profile active. Test success does not guarantee later availability or verified least-privilege grants.
2. **Metadata discovery:** activate profile → `realSourceLoadAllCatalog` sequentially requests bounded catalog pages → Oracle ALL_OBJECTS → persistent loading snapshot → final-page head publication. Checked objects call discover one at a time → cached metadata or dictionary queries → `object_metadata` and profile memory → metadata-only browser snapshots. Cache GET restores previous complete snapshots. Client filtering is not source-side catalog paging of the final browser list.
3. **Dataset request:** `submitDatasetRequest` validates browser inputs/source revisions → assigns `activeDatasetRequest` → `buildDatasetReview`. **No request API or durable request row exists.**
4. **Mapping review:** `recordDatasetReview` → `applyDatasetReview` → decisions/rationale → `approveDatasetDefinition` copies decisions/source refs. **No server-authenticated approval, immutable history or publication authority exists.** UI passes the current revision as both expected and actual revision; it is not cross-client optimistic concurrency.
5. **Data preview:** source preview explicitly submits sample and polls; catalog inline preview restricts UI examples to 1..5 rows, backend supports <=100. Local stored preview GET returns SQLite rows. Dataset wizard preview uses `syntheticPreviewMarkup`, even though the request may reference real metadata; it does not execute joins/transforms.
6. **ETL execution:** real extract_load performs a bounded single-table copy/upsert; group loop runs separate table jobs sequentially in the browser and stops submitting on failure. Closing browser stops group orchestration, not an already submitted thread. Visual rules are not consumed by this loader. Full staged ETL exists only in DemoSync simulation/design.
7. **Dataset publishing:** `createDatasetSimulation` appends a session item with `published:false` and simulated activity. **No Dataset publishing endpoint, target generation, scheduled run or materialized business dataset exists.** The local warehouse load is a separate real action, not Dataset approval-driven publishing.

## Contract boundaries

`docs/api-contract.md:Proposed routes` lists dataset-request create/get/patch, candidate evaluation, field review, definition creation/get/approval and definition preview. They are explicitly **Planned**, absent from Handler routes. `backend/contracts.ts` is not loaded/compiled by `scripts/build.cjs` and does not enforce Python request/response shapes. For example the design `JobReceipt` uses jobId/statusUrl while the real API returns job_id; design RunState differs from real read_completed. Treat v2 contract reconciliation as explicit design work.
