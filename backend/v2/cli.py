"""Bootstrap CLI. Usage: python -m backend.v2.cli create-superadmin <username> [--display-name NAME]

The password is read from UETL_NEW_PASSWORD or prompted (never taken from argv, never printed).
"""
import argparse
import getpass
import os
import sys

import psycopg2

from . import config, security


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["create-superadmin"])
    ap.add_argument("username")
    ap.add_argument("--display-name", default="")
    a = ap.parse_args(argv)
    pw = os.environ.get("UETL_NEW_PASSWORD") or getpass.getpass("Password (min 12 chars): ")
    if len(pw) < 12:
        sys.exit("password must be at least 12 characters")
    conn = psycopg2.connect(host=config.get("UETL_PG_HOST"), port=config.get("UETL_PG_PORT", "5432"),
                            dbname=config.get("UETL_PG_DB"), user="uetl_app", password=config.get("UETL_APP_PASSWORD"),
                            options="-c search_path=uetl_meta")
    with conn, conn.cursor() as cur:
        cur.execute("select 1 from app_user where lower(username)=lower(%s)", (a.username,))
        if cur.fetchone():
            sys.exit("user already exists")
        cur.execute("insert into app_user(username,display_name,password_hash,platform_role) values (%s,%s,%s,'superadmin')",
                    (a.username, a.display_name, security.hash_password(pw)))
        cur.execute("insert into audit_event(action,outcome,object_type,detail) values ('user.bootstrap','allow','user',%s)",
                    ('{"username": "%s"}' % a.username.replace('"', ""),))
    print("superadmin created:", a.username)


if __name__ == "__main__":
    main()
