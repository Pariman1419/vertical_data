# 08 — Plan summary (Phase 0 → 4)

Date: 2026-10-26. Branch: `v2/phase-0-review`. Baseline tag: `v1-pilot-baseline` (legacy pilot, rollback point). Remote: `Pariman1419/vertical_data`.

## 1. Decisions taken (owner, this session)
| Item | Decision |
|---|---|
| Repo | `git@github.com:Pariman1419/vertical_data.git`; `main` = pilot baseline, work on `v2/phase-N-*` branches |
| Stack | FastAPI, PostgreSQL, Redis, Docker Compose (dev on this machine first), React + Vite + TypeScript, local login with argon2id |
| Source | Existing SPICE on `10.153.90.17` (REST `:8091`, Flight SQL `:50051`); vLLM deferred to Phase 5 |
| Owner authorisation | Read-only and write-rejection probes of SPICE authorised. Server administration **not** yet scoped (see §5) |

## 2. Verified facts (details: `01-capability-matrix.md`)
- REST `POST /v1/sql` with `$1` binds works; result is one whole JSON array (no streaming).
- Flight SQL streams in record batches (20,000 rows → 5 batches, 0.93 s) → **worker extraction uses Flight; Gate 3 not blocked**.
- DDL/DML rejected by SPICE config (read-only datasets). Client-side cancel works. `CancelQuery` needs a JSON body (schema unknown). Async queries unsupported (cluster mode only).
- No authentication on SPICE → U-ETL must enforce object allowlists; network restriction recommended.
- Oracle NUMBER surfaces as Float64 → precision fixture required before Gate 3.
- Dev host: Docker Desktop 28.4, 12 CPU, ~16 GB. **Host port 5432 is taken → compose Postgres on 15432.** Containers can reach SPICE.

## 3. Architecture in one line
UI → FastAPI control plane (auth, RBAC, registry, approvals, bounded preview, enqueue) → Redis (work only) → independent worker (Flight read → PG run staging → validate → atomic generation-swap publish); PostgreSQL is authoritative for runs/attempts/approvals.

## 4. Phases
| Phase | Scope | Gate (evidence required) | Notes |
|---|---|---|---|
| 1 `v2/phase-1-foundation` | Compose (api/worker/redis/postgres/ui), migrations + DB roles/schemas, argon2id login, sessions, CSRF, RBAC + workspace isolation, revision-bound approvals, audit, health/readiness, structured logs, Light Luxury login/shell/users UI | Cross-workspace and forged-approval requests rejected server-side; backup/restore + rollback tested; cookies/CSRF/secrets tested | Legacy UI kept at `/legacy`; no SPICE needed |
| 2 `v2/phase-2-spice` | `SpiceAdapter` (REST for catalog/preview, Flight for extraction), connection refs, allowlisted catalog, bounded preview, budgets, Settings/Connections/Catalog UI | Fixture `lot_dm_mock` metadata matches; limits respected; auth/network/timeout/leak tests; no bulk download via API | Never expose raw `/v1/datasets` to browser; Oracle adapter off by default |
| 3 `v2/phase-3-worker` | 1-day Dramatiq crash spike, then worker: lease/fencing in PG, Flight batches → staging, validation, generation-swap publish, retry/DLQ, cancel, Jobs UI | API/browser restart does not lose runs; crash at each commit boundary recoverable; duplicate delivery safe; bounded memory on 372k-row fixture; Float64 precision decision | Full-load only |
| 4 `v2/phase-4-studio` | Dataset wizard, visual canvas (typed nodes), SQL editor with AST validation (sqlglot), shared immutable pipeline definition, approval, queue submit, lineage | SQL ≡ Visual results; injection/DDL/DML/budget/approval-bypass tests; edit invalidates approval; only approved revision runs; a11y + reduced-motion | Compile both modes to one execution plan |

Each phase ends with: summary, changed files, test commands + results, verified capabilities, blockers, gate status, rollback, **STOP for review**. Test labels: TESTED LIVE / ISOLATED / MOCKED / BLOCKED.

## 5. Open items
| # | Item | Owner |
|---|---|---|
| S1 | SPICE server hardening: restrict LAN access to dev/worker IPs or enable API-key auth; confirm all U-ETL datasets read-only. Choose: (A) owner RDPs and runs supplied commands, (B) read-only SSH inspection by Claude. Needs dev + worker IPs | Owner |
| S2 | `CancelQuery` JSON body schema; whether upstream query stops | SPICE admin / Phase 3 |
| S3 | Fixture choice (default `lot_dm_mock`, 372,248 rows) | Owner |
| S4 | Design references (kexsio, threeui, kitbitz) not fetched → NOT VERIFIED | Owner |
| S5 | Prod Linux host, Postgres backup owner, SSO | Phase 7 |
| S6 | Server credentials were pasted in chat; they are **not** stored anywhere. Rotate after use | Owner |

## 6. Risks (top)
1. SPICE unauthenticated and shared (host RAM cap 5 GB, results cache `shared`) → allowlists, low worker concurrency.
2. Float64 for Oracle NUMBER → typed CAST + precision fixture.
3. Queue semantics unproven → crash spike first.
4. Server-side cancel unverified → statement timeouts + client cancel as fallback.
