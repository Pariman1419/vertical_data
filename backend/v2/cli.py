"""Bootstrap CLI. Usage:
    python -m backend.v2.cli create-superadmin <username> [--display-name NAME]
    python -m backend.v2.cli reset-password <username>

The password is read from UETL_NEW_PASSWORD or prompted (never taken from argv, never printed).
"""
import argparse
import getpass
import json
import os
import sys

import psycopg2

from . import config, security


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["create-superadmin", "reset-password"])
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
        cur.execute("select id from app_user where lower(username)=lower(%s)", (a.username,))
        row = cur.fetchone()
        if a.command == "create-superadmin":
            if row:
                sys.exit("user already exists")
            cur.execute("insert into app_user(username,display_name,password_hash,platform_role) values (%s,%s,%s,'superadmin')",
                        (a.username, a.display_name, security.hash_password(pw)))
            cur.execute("insert into audit_event(action,outcome,object_type,detail) values ('user.bootstrap','allow','user',%s)",
                        (json.dumps({"username": a.username}),))
            print("superadmin created:", a.username)
        elif a.command == "reset-password":
            if not row:
                sys.exit("user not found")
            user_id = row[0]
            cur.execute("update app_user set password_hash=%s, failed_logins=0, locked_until=null where id=%s",
                        (security.hash_password(pw), user_id))
            cur.execute("update app_session set revoked_at=now() where user_id=%s and revoked_at is null", (user_id,))
            cur.execute("insert into audit_event(action,outcome,object_type,object_id,detail) values ('user.password_reset','allow','user',%s,%s)",
                        (str(user_id), json.dumps({"username": a.username, "source": "cli"})))
            print("password reset successful for:", a.username)


if __name__ == "__main__":
    main()
