# 01 — Capability matrix

Date: 2026-10-26. **No live service was contacted in Phase 0** (no permission yet). "Config evidence" = what files in `D:\CIM Project\spice` state; it is *not* a runtime check. Statuses: VERIFIED (live evidence) / UNKNOWN / UNSUPPORTED. Nothing below is VERIFIED yet.

## Repository facts re-checked in the current checkout (`handoff-spice-ai`)

| Audit claim | Re-check (static) | Result |
|---|---|---|
| Vanilla JS UI, Python stdlib API | `package.json` has no deps; `backend/spike/server.py` uses `ThreadingHTTPServer` | Confirmed |
| ETL thread inside API, in-memory jobs | `backend/spike/service.py` (473 lines) | Confirmed by file layout; not re-read line-by-line |
| No SPICE adapter / SQL ETL / LLM | No such files under `backend/` | Confirmed |
| No `.git`, no `AGENTS.md`/`CLAUDE.md` | `ls` | Confirmed (**D1**) |
| No Docker/CI in app repo | none present | Confirmed |
| Tests exist (Py + Node) | `tests/` has 9 Python/Node suites + 4 browser scripts | Present; **not executed** in Phase 0 |

## SPICE (existing deployment — config evidence from `D:\CIM Project\spice`)

| Capability | Status | Evidence / what is needed |
|---|---|---|
| Product & version | UNKNOWN (live) | Config: custom image `vdl-spice-odbc:latest`, built from Spice.ai OSS **v2.0.1** source with 2 local patches (`docker/README.md`). Need `spiced --version` / API response. |
| REST/HTTP endpoint | UNKNOWN | Compose maps host `8091 → container 8090` (`--http 0.0.0.0:8090`); health URL `http://localhost:8091/health` documented. Need live GET. |
| OpenAPI / SQL route (`/v1/sql`, `/v1/datasets`) | UNKNOWN | Upstream Spice documents these; not confirmed on this build. Do not code against them until probed. |
| Arrow Flight SQL | UNKNOWN | Compose maps `50051:50051`, `--flight 0.0.0.0:50051`, build features include `flightsql`. Advertised ≠ bulk extraction proven. |
| ODBC *server-side* (client→SPICE) | UNKNOWN / likely UNSUPPORTED | `odbc` feature in the build is SPICE's **outbound connector** (to SQL Server SCADA). A client ODBC driver *to* SPICE is a different thing (Arrow Flight SQL ODBC driver); no evidence it exists here. Prompt's "Flight SQL/ODBC" = Flight SQL client; treat ODBC as UNSUPPORTED until shown. |
| Auth / tenants | UNKNOWN | Compose/pod show no API-key setting. Assume **none** → network-level control only; confirm (**D13**). |
| Catalog | UNKNOWN | Spicepod datasets (Postgres `sixmonth.*`, Oracle `BIDPITDBA/PROMIS`, ODBC SQL Server `AssySCADADB1`) are *configured*, so the catalog is spicepod-defined, i.e. static per pod rather than per-user. |
| Type/precision metadata | UNKNOWN | Oracle NUMBER → Arrow decimal mapping must be tested with fixtures (audit risk: precision). |
| Parameter binds | UNKNOWN | Flight SQL prepared statements may support; REST SQL likely not. Probe. |
| Streaming / pagination | UNKNOWN | Flight is stream-capable by design; REST `/v1/sql` returns a full result. Worker must prefer Flight **only if** a bounded-memory read is demonstrated. |
| Cancellation | UNKNOWN | Treat as unsupported; rely on timeout + row/byte budgets. |
| Limits / quotas | UNKNOWN | Container `mem_limit: 5120m` (config). Result cache disabled in the bench pod (`caching.sql_results.enabled: false`) — production pod unseen. |
| Snapshot semantics | UNKNOWN | Datasets are *live federated* in bench pod (each query reads source); acceleration (DuckDB, refresh 15 m) only on `equip_reg`. No cross-page consistency assumed. |
| CDC / incremental | UNSUPPORTED (assumed) | Not claimed anywhere; full-load only. |
| Shared host risk | Known | Compose comment: shared host, port 8090 occupied; RAM tight → worker concurrency must be low. |

### Read-only verification checklist (to run after D2 approval; each step logged in `implementation-log.md`)
1. `GET /health` (and `/v1/status` if present). 2. Enumerate datasets (`/v1/datasets` or `information_schema`). 3. `SELECT` of ≤10 rows from a **fixture** dataset via REST. 4. Same via Flight SQL (pyarrow `flight`) incl. `GetFlightInfo` endpoints. 5. Decimal/large-ID/NULL round-trip on a fixture table. 6. Bind-parameter test. 7. Row-streaming memory test (e.g. 1M synthetic rows, observe RSS). 8. Timeout/cancel behaviour. 9. Auth-failure and unreachable-host error shapes. Nothing writes; no DDL.

## Redis, PostgreSQL, vLLM

| Item | Status | Notes |
|---|---|---|
| Linux Docker host & Compose | UNKNOWN | The SPICE host runs Docker (compose file exists); U-ETL host/ports/firewall not given (**D3**). |
| PostgreSQL roles/schema/backup | UNKNOWN | Phase 1 will create *new* instance; `pg_hba`, TLS, backup job to be designed (see 02). SPICE's own Postgres sources are separate. |
| Redis TLS/ACL/persistence | UNKNOWN | New instance proposed: AOF `everysec`, ACL user per service, TLS optional on internal network (decision D3). |
| Redis queue semantics | N/A until spike | See D6. |
| vLLM/LiteLLM | UNKNOWN / out of scope | Settings placeholder only; no call in Phase 0–4. |

## Live probe 2026-10-26 (read-only, owner-authorised, from dev machine) — TESTED LIVE

Target: `10.153.90.17` (SPICE host, LAN). Commands limited to health, `SELECT 1`, one TCP connect and two GETs.

| Capability | Result | Evidence |
|---|---|---|
| HTTP health `:8091/health` | VERIFIED | `200 ok` |
| HTTP SQL `POST /v1/sql` | VERIFIED | body requires `sql` **and** `parameters` (array); `{"sql":"SELECT 1 AS one","parameters":[]}` → `200 [{"one":1}]` |
| Typed bind parameters | PARTIAL — field exists; binding semantics/types not tested | 400 `missing field parameters` without it |
| Response shape | VERIFIED: whole result is one JSON array, **not streamed/paginated** | single `content-length` body |
| Authentication | UNKNOWN: no credentials were sent and none were required for these calls | no 401 |
| Result cache | NOTE: header `results-cache-scope: shared` — cache is shared across callers; cache-isolation/staleness to be assessed |
| `/v1/openapi.json` | UNSUPPORTED at that path (404) | |
| `/v1/datasets` | route exists (200); contents not read | |
| Flight SQL `:50051` | PORT OPEN only. Protocol/auth/streaming NOT verified | TCP connect succeeded |
| Cancellation, limits, snapshot semantics | UNKNOWN | |

Implication for Gate 3: REST returns a full array per call, so bounded extraction over REST must be done with SQL-level paging (`ORDER BY` + keyset/`LIMIT`), or Flight SQL streaming, which is still to be tested. Plain REST bulk fetch stays blocked.
