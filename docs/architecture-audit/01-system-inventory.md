# System inventory

Audit date: 2026-10-26. Source inspection only; runtime NOT VERIFIED. Definitions and operating limits are in [00](00-executive-summary.md).

## Repository structure

```text
handoff-spice-ai/
├── index.html                       ordered script entry point
├── app.js                           shell, page dispatch, default/demo menus
├── prototype.js                     profile/catalog/dataset/local-load UI orchestration
├── real-source-ui.js                HTTPS API client and Oracle catalog controls
├── dataset-workflow.js              deterministic candidate/review rules
├── demo-sync.js                     synthetic reconciliation model
├── sync-ui.js                       synthetic sync controls and rendering helpers
├── styles.css, ui-reference-theme.css
├── assets/utac-logo-source.png
├── serve.js                         Node static-only loopback server
├── package.json, package-lock.json  scripts; no npm dependencies
├── .env.example, .gitignore
├── Start U-ETL Test.bat              Windows local HTTPS launcher
├── scripts/
│   ├── start-source-spike.ps1        Windows Python launcher
│   ├── build.cjs                    syntax checks and static file copying
│   └── test.cjs                     four Node test suites
├── backend/
│   ├── contracts.ts                 design interfaces, not a running TS backend
│   ├── requirements-spike.lock.txt  pinned Oracle/TLS dependencies
│   ├── requirements-foundation.txt standard-library synthetic harness
│   ├── spike/
│   │   ├── server.py                HTTPS routes and local startup
│   │   ├── service.py               sessions, admission, in-process jobs
│   │   ├── catalog_store.py         metadata snapshots in SQLite
│   │   └── target_store.py          SQLite upsert/status/preview
│   └── foundation/
│       ├── oracle_read.py           live Oracle read adapter
│       ├── read_budget.py           limits and in-process admission lock
│       ├── core.py                  synthetic Registry and fixture processing
│       ├── worker.py                one-shot synthetic worker CLI
│       ├── smoke.py                 synthetic subprocess demonstration
│       └── secrets.py               unavailable secret-store port
├── tests/                           Python, Node and browser-fixture suites
├── docs/                            design contracts, blueprint, current summary
│   └── architecture-audit/          this audit's only write scope
├── dist/                            pre-existing generated static output
├── .ua/                             pre-existing analysis metadata/archive
└── .test-temp/, .foundation-test/, __pycache__/  pre-existing test/runtime artifacts
```

No AGENTS.md was found in the repository or checked ancestor locations. No `.git` directory was present; a commit ID/diff baseline is unavailable. Generated/archive directories were inventoried but not treated as active application implementations. No database content was inspected.

## Technology and responsibilities

| Area | Finding | Evidence |
|---|---|---|
| Frontend framework | Vanilla JS/HTML/CSS; no React/Vue/Angular or UI package dependency | `package.json`, `package-lock.json`, `index.html` |
| Frontend routing | Page dispatch through `S.page`; query `demo=1` chooses demo mode; no URL router | `app.js:M/DEMO_M/go/navPage/page`; `prototype.js:explicitDemoMode` |
| State management | Globals `S`, `P`, `realSourceUI`, active dataset objects, `window.datasetWorkflow*`; browser localStorage for selected config/metadata/demo state | `prototype.js:2–55,149,224–232`; `real-source-ui.js:realSourceUI` |
| Rendering | Template strings/innerHTML and inline event attributes; multiple later overrides wrap `render`, pages and drawers | `app.js:layout/render`; `prototype.js:202,221,309` |
| Backend framework | Python standard-library `ThreadingHTTPServer` and `BaseHTTPRequestHandler`; manual routing and JSON validation | `backend/spike/server.py:handler_for` |
| Drivers/query layer | `oracledb`; standard-library `sqlite3`; hand-written SQL; no ORM or migration framework | `service.py:oracle_factory`; stores; requirements files |
| Authentication | Local passphrase hash using scrypt, session dictionary, secure cookie, CSRF | `service.py:login/session/_hash`; `server.py:do_POST` |
| Authorization | Single local owner; no production RBAC/tenant layer; client role controls and synthetic-only role checks | `prototype.js:P/canEdit/canRun`; `core.py:Principal/authorize` |
| Background work | One executor thread plus expiry thread inside API; separate synthetic CLI only | `service.py:__init__/_reap`; `worker.py:main` |
| Queue/scheduler | No durable queue for real work; no cron/scheduling implementation | `Service.submit`; `createDatasetSimulation`; synthetic `Registry` is separate |
| Configuration | Node `PORT`; Python `LOCALAPPDATA` for local files; fixed loopback address/HTTPS port; UI connection form | `serve.js:6`; `server.py:main`; `prototype.js:connectionDrawer/saveConnection` |
| Environment loading | `.env.example` defines PORT only; no dotenv loader found | `.env.example` keys; `package.json`; `serve.js` |
| Deployment | Windows BAT/PowerShell and local Python/Node commands; no Dockerfile, Compose, Kubernetes, IaC or CI workflow found | repository inventory; startup scripts |
| Logging | HTTP access logging disabled; sanitized client errors; startup console messages | `server.py:log_message/reply/main`; `oracle_read.py:safe_source_error` |
| Monitoring | Browser polling and last-load registry; no metrics/tracing/alerts/central logs | `realSourceWaitForJob`; `Service.job`; `SQLiteTargetStore.statuses` |

`requirements-spike.lock.txt` pins oracledb 26.0.1, cryptography 46.0.3, cffi 2.1.1, pycparser 3.0 and typing_extensions 4.16.0. These are repository declarations, not verified installed versions or a vulnerability assessment. Node requires >=20; the foundation requirements describe Python >=3.12 and no external packages.

## Entry points and startup dependencies

| Mode | Entry and prerequisites | Behavior |
|---|---|---|
| HTTP preview | `npm start` → `node serve.js`; Node >=20, static assets | Binds 127.0.0.1:PORT (default 5173). Whitelisted assets only; no API proxy. It serves repository files, not dist. |
| Real local pilot | BAT or PowerShell → `.spike-venv/Scripts/python.exe -m backend.spike.server` | Requires preinstalled Python runtime, Oracle/TLS packages, interactive application passphrase, browser certificate handling, writable local data directory and approved Oracle access. Binds 127.0.0.1:8443. |
| Synthetic worker | `python -m backend.foundation.worker --registry <disposable-path>` | One-shot processing of a queued synthetic fixture in an existing/initialized synthetic-only registry; not attached to HTTPS API. |
| Synthetic smoke | `backend.foundation.smoke:main` | Would create temporary storage and launch subprocess; inspected only, not run. |

HTTPS startup generates an ephemeral one-day self-signed certificate, temporarily writes an encrypted private key outside the static root, loads it and removes temporary files. This is local pilot bootstrap, not managed production TLS. `server.py:tls_context/main` is the authoritative implementation.

The PowerShell launcher's error references `docs/source-spike-usage.md`, which is absent from the supplied tree. Some source headers are stale: `service.py` claims no target writes, and `oracle_read.py` claims not enabled in UI, despite `_run` and the UI implementing real local loads. Executable call paths take precedence over these comments.

## Tests and documentation

| Assets | What they cover by inspection | Limits |
|---|---|---|
| `test_spike.py` | session/limits/multi-profile behavior, fake Oracle service, disposable HTTPS guard tests | tests create files/services; not run in Phase 0 |
| `test_oracle_read.py`, `test_read_budget.py` | SQL generation, mock driver, caps, deadlines and gate behavior | no evidence of live Oracle grants/physical query cost |
| `test_catalog_store.py`, `test_local_target.py` | metadata persistence, DDL invalidation, PK upsert/preview | no production crash/precision/scale certification |
| `test_foundation.py` | synthetic authorization, revisions, lease fencing, retry/cancel and subprocess | does not validate Oracle job durability |
| Four Node suites loaded by `scripts/test.cjs` | deterministic matching, demo sync, catalog/source UI assertions | browser tests are not included by npm test |
| `*.browser.cjs`, `spike_browser_fixture.py` | intended browser flows; one fixture starts its own server | hardcoded external Playwright/Chrome paths; no npm-managed browser dependency |
| README, blueprint, API/incremental contracts | product intent and acceptance criteria | proposed endpoints/interfaces do not prove implementation |

Tests/builds were not run; no services were inspected live. No package installation or dependency availability check was attempted.
