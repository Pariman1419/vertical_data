# 07 — Phase 0 review and Gate 0 request

Date: 2026-10-26. No application code, config, dependency, database or infrastructure was changed; only files in `docs/v2/` were created. No test/build was run; no service (SPICE, Redis, PG, vLLM) was contacted.

## Summary
- Audits 00–09 read (00,01,03,04,05,08 fully; 06,07,09 skimmed via gap analysis — **re-read 02, 06, 07, 09 in detail before Phase 1 contract freeze**; stated honestly).
- Audit facts re-checked statically: confirmed (see 01). Key new finding: **the prompt lives in the `spice` git repo, but the app is in `handoff-spice-ai`, which has no git history** (D1).
- SPICE: config shows a custom Spice.ai OSS v2.0.1 build, HTTP `:8091`, Flight `:50051`, shared host with 5 GB RAM cap. Every capability that matters (streaming, binds, cancel, auth, precision) is **UNKNOWN**. "ODBC" in this stack is SPICE's outbound connector, so client-side ODBC to SPICE is probably unsupported.
- Design references: **NOT VERIFIED** (not fetched).

## Recommendation
Proceed with audit option 2 (separate worker, retain/harden control plane): FastAPI + PostgreSQL registry + Redis/Dramatiq worker with PG-authoritative leases, generation-swap publish, React/Vite/TS Light Luxury UI, legacy pilot kept as rollback.

## Biggest risks
1. SPICE may not support bounded streaming → Gate 3 blocks (decision needed, not workaround).
2. SPICE likely has no per-user auth → authorization must be enforced in U-ETL via object allowlists.
3. Shared SPICE host memory → low worker concurrency.
4. Queue library semantics unproven → 1-day crash-test spike first.
5. No VCS on the app → rollback/branching impossible until D1 resolved.

## Approvals requested (Gate 0)
1. D1: confirm repo root and allow `git init` + baseline tag.
2. D2/D13: authorise read-only SPICE probes (checklist in 01) and name the fixture source + credential owner. Without it Gate 2 is blocked.
3. D3: confirm Docker host and that new `postgres`/`redis` containers are acceptable.
4. D4–D7, D9–D12: accept proposals in `00-open-decisions.md` (or amend).
5. Whether to fetch the three design references now (D15).

**STOP — awaiting explicit Gate 0 approval. Phase 1 not started.** `implementation-log.md` / `decision-log.md` will be created when Phase 1 begins.
