# Load hardening and TanStack UI — 2026-10-28

Implementation plan: `docs/superpowers/plans/2026-10-27-load-hardening-and-tanstack-ui.md`, base `dcaf65c`.

## Scope and evidence

- **TESTED LIVE:** PostgreSQL leases, migration 0005 up/down/up, bounded SPICE reads and the preview endpoint.
- **TESTED ISOLATED:** temporary application users, sessions, connections and audit events in the verified-empty, migrator-owned `uetl_staging` schema. The migrator cannot create a new schema. Fixture objects are removed after the test; normal `uetl_meta` records are untouched. No superuser or new Python dependency used.
- **TESTED IN CHROME:** installed Chrome headless, controlled over local CDP with Node's built-in WebSocket. Both computer-use runtimes failed to initialize their kernel assets. Screenshots were inspected locally. This is desktop Chrome evidence, not a cross-browser test.
- **MOCKED:** browser 429 response with `Retry-After: 7`, and hostile 300-column × 1000-row display fixture. The real API 429/header/audit behavior is separately covered by PostgreSQL-backed API tests.
- **NOT RUN:** ODBC/SCADA load test, server-side cancel verification, SPICE host RSS, long RSS soak, TLS/auth failures on a source that has neither TLS nor auth.

## 10-user preview load

`scripts/loadtest_preview.py --users 10 --seconds 60 --object machine_map`, 100 rows per request. Source access only through the authenticated preview endpoint. Credentials came from environment variables; temporary test credentials were never printed. Each virtual user used a separate login session.

| Measurement | Result |
|---|---:|
| Requests | 773 |
| HTTP 200 | 232 |
| HTTP 429 | 541 (70.0%) |
| Other HTTP/network errors | 0 |
| All-request p50 | 637.3 ms |
| All-request p95 | 1240.2 ms |
| Maximum sampled live SPICE leases | 2 |
| Maximum sampled health latency | 71.5 ms |
| Login probes | 6 |
| Maximum sampled login latency | 1326.7 ms |

Percentiles include successful and busy responses. Lease sampling is observational; the eight-thread race test separately proves the last slot has exactly one winner. Health remained responsive; the proposed non-preview 300 ms target is **not established**: login samples were 119.4, 367.2, 503.3, 895.6, 1326.7 and 1053.3 ms. No claim is made about a successful-preview-only p95 or the SPICE host's memory.

The load assumptions remain planner defaults, **not owner-confirmed capacity requirements**: 10 simultaneous users, approximately 1M source rows and 300 columns. A 60-second bounded preview run does not establish million-row extraction throughput.

## UI checks

All five approved TanStack globals loaded from local, hash-pinned ESM files. Login reaches the v2 Sources screen. Back restored the previous selected connection. Each GET resource was requested once per connection; two immediate preview submissions sent one POST. A live `machine_map` preview returned 1000 rows and five columns while rendering 60 cells.

For the controlled 300-column × 1000-row fixture, the initial viewport rendered 72 cells; after selecting all columns and scrolling far right/down it rendered 165, below the 3000-cell limit. The first column remained visible. Case-insensitive column search returned the expected names. `<script>` in a header/value remained text; long cell text was shortened with the full title. The busy banner included `7 s`. Keyboard focus and scroll controls are implemented; screen-reader certification and a broad browser memory soak are not claimed.

The retained pilot bootstrap logs a pre-existing `ReferenceError: datasets is not defined` from `sync-ui.js:33` before the later dataset script loads. Later bootstrap recovers and the v2 checks pass. It is recorded separately from new-module exceptions.

## Live wide-source limitation

The real `cycletime` preview initially encountered a Python `OverflowError`. When connectivity recovered, a bounded diagnostic confirmed `date32[day]` conversion failures in `OUTBOUND_ATA_CUST` and `OUTBOUND_ETD_BKK`; only metadata/error classes were printed. Arrow now formats dates outside Python's year 1–9999 range as exact ISO text. A separate regression also found that an exact-full batch caused an unnecessary next read after the row budget; reaching the cap now cancels immediately and conservatively marks the result truncated.

Intermittent `FlightUnavailableError: End of TCP stream` and a short health timeout occurred during the earlier probes. **The final Chrome live retest passed:** requesting 1000 rows from `cycletime` returned 477 rows × 286 columns, truncated at the byte budget, with 72 mounted cells. The full 1000-row × 300-column DOM case is covered by the controlled browser fixture. No SPICE-host changes or heavyweight aggregate were attempted. These transient source failures are not evidence of verified upstream cancellation or host memory stability.

## Controls and remaining Gate 2 items

- PG is the lease authority across processes: SPICE 2 (`UETL_SPICE_CONCURRENCY`), ODBC 1, TTL 30 s. Short independent transactions, bounded DB lock/statement waits, expiry recovery, unconditional lease cleanup on normal/error paths. HTTP 429 retains `Retry-After` and a denial audit.
- Catalog stores only source kind and columns, never the source `from` path. Learned LIMIT policy survives a refresh of the same kind. Preview retry shares one 10 s deadline; learned LIMIT-less reads remain client-bounded, not server-bounded.
- Preview rows, Arrow/JSON row bytes and call duration are bounded. Oversized rows are excluded. Integers at or beyond `2^53` and decimals reach JS as strings. First-batch allocation and server cancellation remain properties of the upstream Flight/source implementation.
- A closed single-table SELECT grammar plus 2000 seeded hostile inputs covers literal/identifier safety. Decimal exponent expansion is bounded before rendering.
- UI uses query/table/virtual/form/store cores, with no React, bundler, CDN or automatic preview/mutation retry. Five package versions were explicitly approved in chat and each tarball's SHA-512 and final file's SHA-256 are pinned. `.gitattributes` preserves asset bytes on Windows.
- The legacy CSP `unsafe-inline` exception remains for the retained pilot handlers (audit R06). New modules use event listeners and local assets. The plan's stricter whole-app `script-src 'self'` therefore remains a documented deviation.
- Open: source write/DDL rejection, server-side cancellation, auth/TLS fixtures, RSS soak/host observations, and proposed login-latency target. **Gate 2 is not declared fully closed.**

## Automated validation before final review

- Healthy-source checkpoint: 106 v2 tests passed. After the additional date regression, the final run passed 100 and skipped seven live-source tests because SPICE was unreachable; no test failed.
- UI: 18 tests passed, including real FormApi validation, query deduplication/no retry, routing, table ranges and build dependency closure.
- Retained pilot: 39 tests passed; `npm run build` and `git diff --check` passed.

After the independent review and its single fix pass: **166 Python tests passed across the whole project, 25 UI tests passed, 39 pilot tests passed, build and diff check passed.** All five Important review findings have reproducing regressions and are addressed; the original review verdict and execution decisions are preserved in `11-load-hardening-review.md`. Final desktop Chrome smoke passed with the real wide source plus the controlled hostile fixture. Fixture objects and metadata leases were checked empty again after shutdown.
