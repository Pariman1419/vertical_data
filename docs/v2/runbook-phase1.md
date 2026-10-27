# Phase 1 runbook (local development)

## Prerequisites
Python 3.12, `pip install -r backend/requirements-v2-dev.txt`, a git-ignored `.env` with `UETL_PG_*`, `UETL_APP_PASSWORD`, `UETL_MIGRATOR_PASSWORD`, optional `UETL_REDIS_URL`. See `.env.example`.

## One-time database bootstrap (needs the admin account, run once)
`python -I scripts/db/bootstrap_roles.py` creates roles `uetl_migrator` / `uetl_app` and schemas `uetl_meta`, `uetl_staging`, `uetl_published` in `spiec_verti` only.

## Migrate
`python -I backend/migrate.py status | up` ; revert latest: `python -I backend/migrate.py down --yes` (drops that migration's tables; take a backup first on non-empty data).

## First user
`python -m backend.v2.cli create-superadmin <name>` (prompts for the password in a real terminal, or set `UETL_NEW_PASSWORD`). Then sign in and use **Account** to change it.

## Run
`Start U-ETL v2.bat` or `python -m uvicorn backend.v2.app:app --host 127.0.0.1 --port 8443` → http://127.0.0.1:8443/. Cookies are `Secure`; browsers accept that on 127.0.0.1/localhost. Behind plain HTTP elsewhere set `UETL_COOKIE_SECURE=false` (dev only).

## Test
`python -I -m pytest tests/v2 -q` — runs against the live `spiec_verti`; every test is rolled back. Skips itself when the DB is unreachable.

## Rollback to the pilot
`git checkout baseline-pilot` and use `Start U-ETL Test.bat`; v2 tables are untouched by the pilot and can stay or be dropped with `migrate.py down`.

## Known limits
Backup: `pg_dump` is at `C:\Program Files\PostgreSQLin` (not on PATH); restore round-trip not yet tested. Redis in WSL does not auto-start. Legacy Oracle routes are not served by the v2 server.

## Docker
`docker compose up -d --build` (needs `UETL_REDIS_PASSWORD` in `.env`; API on 127.0.0.1:8443, Redis internal only). `docker compose down` to stop. Docker CLI: `C:\Program Files\Docker\Dockeresourcesin` if not on PATH.
