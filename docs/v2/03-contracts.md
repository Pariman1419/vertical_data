# 03 — Contracts (draft for Gate 0)

All routes under `/api/v2`, JSON, session cookie + `X-CSRF-Token` on non-GET. Errors: `{"error":{"code","message","correlation_id"}}`, no stack/SQL/secret text. Every route checks (a) authenticated, (b) workspace membership, (c) permission, (d) object ownership/state.

## RBAC
Roles (per workspace): `viewer`, `author`, `reviewer`, `operator`, `admin`. Permissions: `connection.read|manage`, `catalog.read`, `preview.run`, `pipeline.read|write`, `pipeline.submit_review`, `approval.decide`, `run.submit|cancel|retry`, `run.read`, `settings.manage`, `user.manage`. Approver ≠ author of the revision (D11). Platform role `superadmin` only for bootstrap.

## API (Phase 1–4)
| Phase | Route | Purpose | Permission |
|---|---|---|---|
| 1 | `POST /auth/login`, `POST /auth/logout`, `GET /auth/me` | session | — |
| 1 | `GET /healthz`, `GET /readyz` | probes | public (no detail) |
| 1 | `GET/POST /workspaces`, `GET/POST/DELETE /workspaces/{w}/members` | tenancy | user.manage |
| 1 | `GET /audit-events` | audit | admin |
| 2 | `GET/POST/PATCH /workspaces/{w}/connections` | SPICE refs (secret_ref only) | connection.manage |
| 2 | `POST /connections/{c}/test` | fixed health check, **no SQL input** | connection.manage |
| 2 | `GET /connections/{c}/capabilities` | negotiated flags | connection.read |
| 2 | `GET /connections/{c}/catalog?path=` / `POST …/catalog/refresh` | catalog snapshot | catalog.read |
| 2 | `POST /connections/{c}/preview` | bounded sample of an allowlisted object (typed filter, limit≤cap) | preview.run |
| 2 | `GET/PUT /workspaces/{w}/infra/{redis|postgres|llm}` + `/test` | settings; secrets write-only | settings.manage |
| 3 | `POST /pipelines/{p}/revisions/{r}/runs` (Idempotency-Key header) | submit approved revision | run.submit |
| 3 | `GET /runs`, `GET /runs/{id}`, `GET /runs/{id}/events` (SSE/poll), `POST /runs/{id}/cancel|retry` | monitoring | run.read / cancel / retry |
| 4 | `GET/POST /pipelines`, `POST /pipelines/{p}/revisions`, `GET …/revisions/{r}`, `GET …/compare?to=` | authoring | pipeline.* |
| 4 | `POST /revisions/{r}/validate` (AST + allowlist + plan compile), `POST /revisions/{r}/preview` (bounded) | | pipeline.write / preview.run |
| 4 | `POST /revisions/{r}/submit-review`, `POST /revisions/{r}/decision {decision, comment, revision_checksum}` | approval | approval.decide |
| 4 | `GET /datasets`, `GET /datasets/{d}/lineage` | registry | pipeline.read |

Approval request must echo `revision_checksum`; server rejects if it differs from the stored checksum or revision is not `in_review`. Approved revisions are immutable (DB trigger blocks UPDATE of spec columns); edit = new revision with `parent_revision_id`.

## Registry tables (PostgreSQL `registry` schema)
`user`, `workspace`, `membership(role)`, `permission_grant(object_type,object_id,…)`, `secret_ref(name,provider,rotated_at)` (no values), `connection(workspace_id,kind rest|flight,base_url,tls_verify,auth_mode,secret_ref_id,scope,timeout_s,capabilities jsonb,last_test_at,status)`, `catalog_snapshot(connection_id,revision,fetched_at,payload jsonb)`, `pipeline`, `pipeline_revision(spec jsonb,checksum,state draft|in_review|approved|rejected|superseded,parent_id,created_by)`, `approval_decision(revision_id,checksum,decided_by,decision,comment,decided_at)` append-only, `dataset(target_schema,table,current_generation)`, `dataset_generation`, `job_run`, `job_attempt`, `job_event`, `audit_event` append-only, `session`, `setting(kind,config jsonb)`.

## Queue payload
```json
{"v":1,"run_id":"uuid","attempt":1,"correlation_id":"uuid","enqueued_at":"iso8601"}
```
Nothing else. Worker loads revision, connection and secrets from PG/secret store.

## Source capability contract (SpiceAdapter)
```
capabilities(): {rest:bool, flight:bool, binds:bool, streaming:bool, cancel:bool, catalog:bool,
                 max_rows:int|null, max_bytes:int|null, dialect:str, version:str}   # each from a live probe
test(): Health          list_catalog(path): CatalogPage        describe(obj): Columns(type,precision,scale,nullable)
preview(obj|plan, binds, Budget): BoundedResult      # API process
read_batches(plan, binds, Budget) -> Iterator[ArrowBatch]   # worker only; raises Unsupported if !streaming
cancel(query_id)  # only if capability
```
Errors classified `auth | network | timeout | unauthorized_object | invalid_query | budget_exceeded | unsupported | transient`; only `network|timeout|transient` are retried. No fallback to another adapter.

## Pipeline Definition (immutable JSON, schema_version 1)
```json
{
 "pipeline_id":"…","revision_id":"…","workspace_id":"…","authoring_mode":"visual|sql|hybrid",
 "source_connection_ref":"…","source_catalog_revision":12,
 "source_object_allowlist":["schema.table"],"dialect":"spice",
 "plan":{"nodes":[{"id":"n1","type":"source|select|join|filter|project|derive|aggregate|validate|sql|target","params":{}}],
         "edges":[["n1","n2"]]},
 "extract_sql": "optional verbatim text","typed_parameters":[{"name":"d","type":"date","default":"…"}],
 "transforms":[],"output_schema":[{"name","type","precision","scale","nullable"}],
 "grain_and_business_keys":["id"],"target":{"schema":"published","table":"…"},
 "write_mode":"replace_generation","quality_rules":[{"type":"not_null|unique|range|rowcount_min","…":"…"}],
 "query_budgets":{"max_rows":0,"max_bytes":0,"timeout_s":0},"schedule_policy":{"eligible":false},
 "approval_state":"…","approver_evidence":{"decision_id":"…"},"lineage":{"inputs":[],"outputs":[]},
 "checksum":"sha256 of canonical JSON excluding approval_state/approver_evidence/checksum"
}
```
Node params are typed enums/expressions from a closed grammar (no JS). Expressions are restricted to a function allowlist and parsed, not eval'd.
