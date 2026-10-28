# Implementation review and execution decisions

Plan: `docs/superpowers/plans/2026-10-27-load-hardening-and-tanstack-ui.md`.
Reviewed range: `dcaf65c..0ae4187`, followed by one author fix pass with reproducing tests. No merge or push performed.

## Final independent review

The fresh-context reviewer found no Critical issues and five Important issues. Its initial verdict was **not ready to merge**. All five were reproduced before their fixes:

| Finding | Fix and verification |
|---|---|
| Old POST/401/error completions could reset or alter another session/workspace; filters survived logout | Guard API/session and every mutation completion, clear preview inputs at session boundaries; actual `v2-ui.js` event-handler tests cover old 401, late DELETE success/error and logout |
| A pending preview could show object A beneath newly selected object B | Object change advances the response generation and resets its busy flag; actual UI regression rejects A's late rows |
| Invalidating a pending GET could cache and install the pre-mutation response indefinitely | Remove/cancel matching QueryClient entries and version the UI callbacks; real QueryClient and actual UI refresh tests prove the fresh revision wins |
| Lease cleanup Busy replaced successful reads and source timeouts with misleading 429 | Bounded DB-cleanup failures log only their class; TTL reclaims capacity; original result/error preserved in both regressions |
| Concurrent generic-pool reads could both learn LIMIT, or publish old learning into a refreshed source | Nonblocking PG advisory transaction lock per connection/dataset; known policies remain concurrent; publication checks the original latest revision and kind; external-connection contention and refreshed-identity tests cover both |

The final fix pass is validated by author tests, not a second independent review. The original reviewer verified all 42 vendor manifest hashes, the native ESM dependency closure, lease atomicity/expiry structure, bounded DOM rendering, SQL shape guard and absence of automatic preview/mutation retry.

Final validation: 166 whole-project Python tests, 25 UI tests and 39 pilot tests passed; static build and diff check passed. The final Chrome smoke also passed with `cycletime` (477 rows × 286 columns, byte-truncated, 72 DOM cells), Back, one preview for a double submit, local TanStack exports, inert hostile text and the mocked Retry-After banner. The row-budget boundary regression was observed failing before its one-pass fix. Source availability recovered without SPICE-host changes.

## Decisions made while executing

| Decision | Reason | Cost / limit |
|---|---|---|
| Work on the existing feature branch in place | Owner decision D1 names this branch; checkout was clean | No extra worktree isolation |
| Record skill task boundaries in a Windows ledger | Git Bash skill scripts unavailable | Bookkeeping adapted, same task/test/commit record |
| Bound PG lease waits and share the source deadline across Flight calls/retry | Otherwise source capacity and 10 s budget could overrun | Slow operations may fail earlier |
| Replace the five-billion-row live aggregate with a controlled Flight timeout | Server cancellation is unproven on the shared host | Real heavyweight-query timeout/cancel remains untested |
| Preserve exception headers and commit session updates before source I/O | Needed Retry-After and independent concurrent requests for a login | Session touch commits even if the subsequent source read fails |
| Bound decimal input/exponents before formatting | Avoid enormous fixed-point literal allocation | Extreme exponents rejected |
| Retain the pilot CSP unsafe-inline exception | Existing pilot handlers depend on it | Strict whole-app self-only CSP remains open; new code has no inline handlers |
| Use approved form-core 1.0.0/store 0.7.0 | Newer form versions introduced additional dependencies | Deliberately older exact pins; no unapproved packages |
| Use explicit Node test globs | Node 24 does not accept the plan's directory test argument | Test command is `node --test tests/ui/*.test.js` |
| Use verified-empty owned staging schema for disposable fixture records | Migrator cannot CREATE a new schema | Would conflict with a simultaneous staging worker; none was active; only fixture-created objects removed |
| Increase request pool from 8 to 16 and serialize initialization | Real failing test showed ten previews exhausted control capacity | Up to eight more PG connections; not a reservation/SLO guarantee |
| Include v2 ESM/vendor assets in static build/server | Dependency-closure regression found omitted runtime files | Larger static artifact |
| Format out-of-Python-range Arrow dates using Arrow ISO text | Controlled regression reproduced the overflow; live diagnostic later confirmed two date32 columns | Extended ISO years may be displayed |
| Treat catalog revision as the identity for learning publication | Prevent an old read from disabling LIMIT on a refreshed/replaced source | Refresh during learning may require a new probe on the next request |
| Make cleanup failure use TTL fallback | Source result/error must survive a saturated cleanup pool | The slot can remain busy until its 30 s expiry |

## Review areas deliberately left open

- Upstream server cancellation, first-batch allocation, host RSS/soak, million-row extraction throughput, write/DDL rejection and TLS/auth fixtures require operational evidence; client budgets do not prove these. Risk: unmeasured upstream resource use. The initially unverified real wide-source success was subsequently verified in Chrome; its earlier date-conversion/TCP failures and final result are retained in the load-test record.
- SCADA load and SPICE host changes were expressly outside authorization/scope. Risk: their operational behavior is not established.
- A hard login SLO was not inferred from provisional capacity assumptions. Risk: observed login latency under load exceeded the proposed 300 ms target.
- Old snapshots require the documented deployment catalog refresh before kind-aware pooling is relied on. Risk: the generic pool is used before that refresh.
- Legacy CSP and the recovered pilot bootstrap exception remain documented. Risk: inherited inline-handler exposure and a transient console error.
- Desktop Chrome evidence does not certify broad accessibility, every browser or a long memory soak. Risk: untested environments/assistive paths.
- Existing non-preview/non-dataset form submission behavior was not broadly redesigned. Risk: inherited forms may still allow duplicate mutations.
- Vendored code was reviewed for packaging, integrity and imports, not exhaustively audited upstream. Risk: normal third-party library risk remains despite pins.

## Deferred minor

The existing `sync-ui.js:33` bootstrap invokes rendering before `datasets` is defined. Later scripts recover and the v2 UI works. This pre-existing console error was excluded from new-module smoke failures and left unchanged.
