"""One-time, idempotent bootstrap of U-ETL roles and schemas in ONE database.

Run with the admin credentials from .env (UETL_PG_*). Touches only the target
database plus two cluster-level roles prefixed `uetl_`. Writes the generated
role passwords to .env (never printed). Re-running keeps existing passwords.
"""
import pathlib
import secrets

import psycopg2
from psycopg2 import sql

ENV = pathlib.Path(__file__).resolve().parents[2] / ".env"
SCHEMAS = ("uetl_meta", "uetl_staging", "uetl_published")


def load_env():
    return dict(l.rstrip("\n").split("=", 1) for l in ENV.read_text().splitlines() if "=" in l)


def main():
    env = load_env()
    db = env["UETL_PG_DB"]
    if db != "spiec_verti":
        raise SystemExit("refusing: bootstrap is pinned to spiec_verti")
    new = {}
    for key in ("UETL_MIGRATOR_PASSWORD", "UETL_APP_PASSWORD"):
        if key not in env:
            new[key] = secrets.token_urlsafe(24)
    pw = {**env, **new}
    c = psycopg2.connect(host=env["UETL_PG_HOST"], port=env["UETL_PG_PORT"], dbname=db,
                         user=env["UETL_PG_USER"], password=env["UETL_PG_PASSWORD"], connect_timeout=8)
    c.autocommit = True
    cur = c.cursor()
    for role, key in (("uetl_migrator", "UETL_MIGRATOR_PASSWORD"), ("uetl_app", "UETL_APP_PASSWORD")):
        cur.execute("select 1 from pg_roles where rolname=%s", (role,))
        verb = "alter" if cur.fetchone() else "create"
        cur.execute(sql.SQL(f"{verb} role {{}} login password %s nosuperuser nocreatedb nocreaterole noinherit connection limit 20").format(sql.Identifier(role)), (pw[key],))
    cur.execute(sql.SQL("revoke all on database {} from public").format(sql.Identifier(db)))
    for r in ("uetl_migrator", "uetl_app"):
        cur.execute(sql.SQL("grant connect on database {} to {}").format(sql.Identifier(db), sql.Identifier(r)))
    cur.execute("revoke create on schema public from public")
    for s in SCHEMAS:
        cur.execute(sql.SQL("create schema if not exists {} authorization uetl_migrator").format(sql.Identifier(s)))
        cur.execute(sql.SQL("grant usage on schema {} to uetl_app").format(sql.Identifier(s)))
        # objects later created by the migrator are usable by the app role
        cur.execute(sql.SQL("alter default privileges for role uetl_migrator in schema {} grant select,insert,update,delete on tables to uetl_app").format(sql.Identifier(s)))
        cur.execute(sql.SQL("alter default privileges for role uetl_migrator in schema {} grant usage,select on sequences to uetl_app").format(sql.Identifier(s)))
    cur.execute("alter role uetl_app in database " + db.replace('"', '') + " set search_path = uetl_meta")
    cur.execute("alter role uetl_migrator in database " + db.replace('"', '') + " set search_path = uetl_meta")
    if new:
        with ENV.open("a") as f:
            for k, v in new.items():
                f.write(f"{k}={v}\n")
    print("bootstrap ok; new secrets written:", sorted(new))


if __name__ == "__main__":
    main()
