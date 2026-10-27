"""Minimal migration runner: `python backend/migrate.py up|down|status`.

Connects as uetl_migrator (never the admin). Each migration is one transaction;
applied files are recorded with a SHA-256 so edited history is refused.
`down` reverts only the latest migration and requires --yes.
"""
import hashlib
import pathlib
import sys

import psycopg2

ROOT = pathlib.Path(__file__).resolve().parents[1]
MIG = pathlib.Path(__file__).resolve().parent / "migrations"


def env():
    lines = (ROOT / ".env").read_text().splitlines()
    return dict(l.split("=", 1) for l in lines if "=" in l)


def connect(e=None, schema="uetl_meta"):
    e = e or env()
    return psycopg2.connect(host=e["UETL_PG_HOST"], port=e["UETL_PG_PORT"], dbname=e["UETL_PG_DB"],
                            user="uetl_migrator", password=e["UETL_MIGRATOR_PASSWORD"], connect_timeout=8,
                            options=f"-c search_path={schema}")


def files(kind):
    return sorted(MIG.glob(f"*.{kind}.sql"))


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def applied(cur):
    cur.execute("create table if not exists schema_migration (name text primary key, "
                "sha256 text not null, applied_at timestamptz not null default now())")
    cur.execute("select name, sha256 from schema_migration order by name")
    return dict(cur.fetchall())


def up(c):
    cur = c.cursor()
    done = applied(cur)
    c.commit()
    for f in files("up"):
        name = f.name.removesuffix(".up.sql")
        if name in done:
            if done[name] != sha(f):
                raise SystemExit(f"refusing: {name} was edited after being applied")
            continue
        cur.execute(f.read_text())
        cur.execute("insert into schema_migration(name, sha256) values (%s, %s)", (name, sha(f)))
        c.commit()
        print("applied", name)


def down(c):
    cur = c.cursor()
    done = applied(cur)
    if not done:
        return print("nothing to revert")
    name = sorted(done)[-1]
    cur.execute((MIG / f"{name}.down.sql").read_text())
    cur.execute("delete from schema_migration where name=%s", (name,))
    c.commit()
    print("reverted", name)


def status(c):
    done = applied(c.cursor())
    c.commit()
    for f in files("up"):
        n = f.name.removesuffix(".up.sql")
        print(("applied " if n in done else "pending ") + n)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "down" and "--yes" not in sys.argv:
        raise SystemExit("down requires --yes")
    conn = connect()
    try:
        {"up": up, "down": down, "status": status}[cmd](conn)
    finally:
        conn.close()
