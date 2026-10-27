# Implementation log

## 2026-10-27 — Phase 1 start
- `git tag baseline-pilot`; branch `feature/v2-phase1-foundation`.
- Env: Python 3.12.10, Node 24, fastapi/sqlalchemy/psycopg2/pytest present; no docker/psql/pg_dump. WSL Ubuntu-24.04 present.
- Redis 7.0.15 installed in WSL (apt), config `/etc/redis/redis-uetl.conf`, loopback + requirepass, `PING` ok, unauth from Windows => NOAUTH. [TESTED LIVE]
- Read-only probe of `spiec_verti`: empty, `public` only. [TESTED LIVE]
- `scripts/db/bootstrap_roles.py` run once as `postgres`: created `uetl_migrator`, `uetl_app`, schemas `uetl_meta/uetl_staging/uetl_published`. Verified: app role cannot CREATE (InsufficientPrivilege); neither role is superuser/createrole/createdb. [TESTED LIVE]
- Mistake caught: `.env.example` was overwritten by mistake and restored from git before any commit.
