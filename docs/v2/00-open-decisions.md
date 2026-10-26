# 00 — Open decisions (Phase 0)

Date: 2026-10-26. Status vocabulary: OPEN (needs owner), PROPOSED (recommendation awaiting Gate 0), BLOCKED (needs access/evidence).

| # | Owner | Question | Risk if wrong | Status | Proposal |
|---|---|---|---|---|---|
| D1 | Owner | Which repo root is the U-ETL baseline? The prompt file sits in `D:\CIM Project\spice` (SPICE VDL config repo, git) and `spice-etl-web`; the code + audits are in `D:\CIM Project\handoff-spice-ai` (**no `.git`**). | Feature branches/rollback impossible without VCS | OPEN | Treat `handoff-spice-ai` as app baseline; `git init` it (or move into a git repo) before Phase 1; keep `spice` repo as SPICE infra reference only. |
| D2 | Owner | Permission to run read-only SPICE capability checks (`/health`, catalog, tiny `SELECT`), who owns credentials, which test source? | Gate 2 cannot be passed on guesses | BLOCKED | See capability matrix §SPICE; checklist in `01`. No probe was run in Phase 0. |
| D3 | Owner/Infra | Linux Docker host: which host, existing PostgreSQL/Redis (reuse vs new), backup owner, network/firewall for worker→SPICE:8091/50051? | Wrong topology, port conflicts (host already uses 8090) | BLOCKED | New `postgres` + `redis` containers in the U-ETL compose project; SPICE/vLLM external. |
| D4 | Owner | Backend stack: keep Python (reuse `oracle_read`, `read_budget`, `foundation/core.py` patterns) vs rewrite. | Re-write cost | PROPOSED | Python 3.12 + FastAPI (API) + SQLAlchemy/Alembic + psycopg3; same image for worker. |
| D5 | Owner | Frontend migration: React + Vite + TypeScript (+ React Flow, CodeMirror 6) vs keep vanilla JS. | Prototype uses inline handlers/innerHTML (audit risk) | PROPOSED | React/Vite/TS; strangler: legacy UI stays at `/legacy` until parity (see 06). |
| D6 | Owner | Queue library: Dramatiq vs Celery vs arq vs custom PG-lease + Redis list. | Lease/ack semantics differ; wrong choice = lost/duplicated work | PROPOSED | Dramatiq (late-ack, retries, DLQ) **with PG as lease/fencing authority**; Phase 3 starts with a 1-day spike that crash-tests ack/redelivery before committing. |
| D7 | Owner | Secret management: Docker secrets/env-file injection vs Vault/other. | Plaintext leakage | PROPOSED | `secret_ref` rows hold *names only*; resolved from mounted secret files/env in API+worker. Vault is a later swap behind a `SecretResolver` interface. |
| D8 | Owner | SQL dialect for authoring: SPICE (DataFusion-flavoured) vs source-native pass-through. | AST validator mismatch with real engine | BLOCKED on D2 | Author in SPICE SQL only; validate with AST parser (sqlglot/sqlparser) + SPICE-side read-only; confirm dialect from live checks. |
| D9 | Owner | Target publish semantics. | Partial publish visible | PROPOSED | Generation-swap inside one PG transaction (see 02 §Publish). Full-load only in Phase 3–4. |
| D10 | Owner | Auth: local password (argon2id) vs corporate SSO. | Rework of identity | OPEN | Local users in Phase 1 behind an `IdentityProvider` seam; SSO later. |
| D11 | Owner | Self-approval policy (reviewer approving own revision). | Separation-of-duties gap | PROPOSED | Forbidden by default; workspace-level flag, off by default, audited. |
| D12 | Owner | Legacy Oracle direct adapter: keep (disabled by default, feature flag) for parity tests? | Silent bypass of SPICE | PROPOSED | Keep, isolated module, `LEGACY_ORACLE_ENABLED=false`; never used as fallback. |
| D13 | Owner | Per-user source authorization: does deployed SPICE enforce per-user grants, or is it one service identity? | Catalog "permission-aware" cannot be honoured | BLOCKED on D2 | If single service identity, enforce object allowlists in U-ETL (workspace → allowed datasets); document as compensating control. |
| D14 | Owner | Schedules in Phase 3–4? | Needs unattended credentials | OPEN | Define `schedule_policy` field and eligibility flag only; no dispatcher. |
| D15 | Owner | Design references: `kitbitz.art` not inspected (see 04). | Fabricated inspiration | OPEN | Mark NOT VERIFIED; owner may supply screenshots. |
