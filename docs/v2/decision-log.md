# Decision log (Phase 1+)

## 2026-10-28 — Load hardening execution

- PG lease authority: `spice=2` (environment override), `odbc=1`; 30 s expiry, separate short DB transactions. Request pool increased from 8 to 16 to leave control capacity at the planner's 10-user load. These load assumptions (10 users, ~1M source rows, 300 columns) remain planner defaults, not confirmed owner capacity requirements.
- Owner explicitly approved npm-registry downloads of `@tanstack/query-core@5.90.4`, `table-core@8.21.3`, `virtual-core@3.13.12`, `form-core@1.0.0`, `store@0.7.0`. The older form/store pair avoids extra dependencies. Self-hosted ESM, exact versions, pinned tarball/file hashes; no Router/React/CDN/production bundler.
- Preview GET caching/deduplication is separate from explicit POST submissions. No automatic preview/mutation retry. 429 is a busy response requiring a user retry; no server queue is implied.
- Execution deviation: retain the pilot CSP `unsafe-inline` exception while all new code uses event listeners; strict whole-app CSP would disable existing pilot handlers. An extreme synthetic aggregate was replaced by a controlled transport-timeout test because server-side cancel is unproven. ODBC load remains unapproved and was not run.
- Evidence and remaining Gate 2 gaps: `10-load-test-results.md`. Real source availability failed during the wide-source diagnostic; host changes are out of scope. No capacity/SLO claim is inferred from the short load test.

Gate 0 approved by owner on 2026-10-27 ("approve ตาม proposal"). Entries below record what changed from or was decided beyond `00-open-decisions.md`.

| Date | ID | Decision | Why / consequence |
|---|---|---|---|
| 2026-10-27 | D1 | App baseline = `vertical_data` (git repo, tag `baseline-pilot`). Work on `feature/v2-phase1-foundation`. | Rollback = checkout tag; legacy launcher untouched. |
| 2026-10-27 | D4,D6,D7,D9,D11,D12 | Accepted as proposed. | — |
| 2026-10-27 | D10 | Local users, argon2id, behind an `IdentityProvider` seam. | SSO later. |
| 2026-10-27 | D14 | No schedule dispatcher; only `schedule_policy.eligible` field. | — |
| 2026-10-27 | D15 | Design references not fetched. | — |
| 2026-10-27 | D5 (changed) | **Keep the existing vanilla-JS UI and extend it**; no React/Vite rewrite, no full redesign. New screens follow current look; new code uses event listeners, no inline handlers (audit R06). | Owner instruction. `04-light-luxury-design.md` tokens apply only as incremental polish. |
| 2026-10-27 | D3 (changed) | PostgreSQL = existing shared server `10.151.28.2:5432`, DB `spiec_verti` (PG 13.6). Docker not installed; Redis 7.0.15 installed in WSL Ubuntu-24.04, bound to 127.0.0.1 with password, AOF on. | Owner supplied; Docker compose files are written but cannot be run here (Gate evidence = TESTED ISOLATED only for what actually ran). |
| 2026-10-27 | schema names | Doc names `registry/staging/published` are implemented as `uetl_meta/uetl_staging/uetl_published`. | Server is shared with 35 other DBs; prefix avoids ambiguity. |
| 2026-10-27 | roles | `uetl_migrator` (owns schemas, runs migrations) and `uetl_app` (DML only, no CREATE). Superuser `postgres` used only for `scripts/db/bootstrap_roles.py`. | Least privilege. |
| 2026-10-27 | migrations tool | Small in-repo runner `backend/migrate.py` with paired `.up.sql/.down.sql` and stored checksums, instead of Alembic. | Alembic not installed; avoids new dependency for a SQL-only schema. Revisit if ORM models are added. |

## Risks recorded
- **Shared PG server:** default `PUBLIC` CONNECT on other databases means `uetl_*` roles can connect to them (not changed by us; DBA should restrict via `pg_hba.conf`/REVOKE). App always connects with a fixed DB name.
- **Superuser password was pasted in chat** — recommend rotating after Phase 1.
- Redis in WSL does not auto-start after reboot.
- `pg_dump` / client tools not present locally: Gate 1 backup/restore may be `BLOCKED` unless installed.

| 2026-10-27 | D2/D13 resolved (partly) | Owner supplied SPICE `10.153.90.17` (HTTP 8091, Flight 50051) and asked for a probe. Results in `09-spice-probe-results.md`. SPICE has **no authentication**; U-ETL allowlist is the compensating control for U-ETL users only. | Gate 2 unblocked for read paths. |
| 2026-10-27 | D8 resolved | Dialect = Apache DataFusion (SPICE SQL). | AST validator must target it. |
| 2026-10-27 | Transport (proposed) | Worker + bounded preview use **Flight**; REST only for health/catalog. Numerics never via JSON numbers. | Streaming and early stop proven live; REST has no cap. Pending owner OK. |
| 2026-10-27 | New dependency (proposed) | `pyarrow` (already on the dev machine, v25.0.1) for the Flight client; pin in `requirements-v2.txt` when the client is written. | Large wheel; Docker image grows. |

## 2026-10-27 — Owner risk acceptances for the TEST phase (SPICE host 10.153.90.17)
- **Firewall stays open (Any) on 8091/50051 during testing.** Accepted by owner. Revisit before any non-test use: restrict to U-ETL + known clients (e.g. 10.153.93.177) and add auth in front of SPICE.
- **Source DB users are not independently verified read-only** (verified only for Postgres `spice_vdl_ro`; Oracle/SQL Server unknown). Owner: access is controlled through SPICE; no DBA confirmation requested now. U-ETL itself sends only SELECT/DESCRIBE and cannot reach the DBs directly. Residual risk: anyone able to reach SPICE can send any SQL the DB user permits (SPICE write/DDL rejection is untested).
- **Windows admin password on the SPICE host not rotated** (it appeared in chat). Accepted by owner for now.
- Dataset onboarding design: U-ETL generates a spicepod entry that references existing source profiles (`*pg`, `*scada`); no DB credentials pass through U-ETL; a human applies it on the host (backup -> edit -> validate -> reload/restart -> Refresh catalog). Automatic writer on the SPICE host deferred until SPICE has authentication.

## 2026-10-28 — Owner decisions for the Phase 3 start (grill-me round 1)
| Decision | Choice | Notes |
|---|---|---|
| Order of work | Close the two small leftovers first, then Phase 3 | Leftovers: reject `\` in string filter values (server + UI validator, with tests); make live-SPICE tests tolerate a full lease pool |
| Limiter behaviour when the SPICE slot is full | Wait up to **2 s**, then answer **429** with `Retry-After` | Plus a new **Source activity** page (queue waits, 429s, timeouts, reads per dataset/user), separate from the Audit trail; no raw SPICE text or secrets in it |
| Who writes Phase 3 code | **Codex writes; Claude reviews and runs the suite independently** | One writer in the repo at a time; reviewer is read-only; commit only own files (no `git add -A`) |
| Queue framework | **Dramatiq** (Redis = transport, PostgreSQL = lease authority) | Start with the planned 1-day crash/redelivery spike before locking the choice |
| Redis / worker hosting (test phase) | **Docker Compose: api + worker + redis in one stack** | Replaces the WSL Redis (no autostart) for tests; WSL Redis stays only as a fallback |
| ETL test data | **Synthetic data on SPICE (`generate_series`) + `_mock` tables only** | No real/SCADA tables in Phase 3 tests |
| Publish mechanism | **Table per generation + a view pointing at the latest generation**, swapped in one transaction | Retention of old generations: N to be decided |
