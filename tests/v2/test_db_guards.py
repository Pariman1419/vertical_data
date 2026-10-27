"""DB-level guard tests against the live spiec_verti schema (TESTED LIVE).

Every test runs inside a transaction that is always rolled back, so no row is kept.
Skipped automatically when .env or the database is unavailable.
"""
import hashlib
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "backend"))
psycopg2 = pytest.importorskip("psycopg2")
import migrate  # noqa: E402


@pytest.fixture()
def cur():
    try:
        e = migrate.env()
        c = psycopg2.connect(host=e["UETL_PG_HOST"], port=e["UETL_PG_PORT"], dbname=e["UETL_PG_DB"],
                             user="uetl_app", password=e["UETL_APP_PASSWORD"], connect_timeout=5,
                             options="-c search_path=uetl_meta")
    except Exception as ex:  # pragma: no cover
        pytest.skip(f"database unavailable: {ex}")
    cr = c.cursor()
    yield cr
    c.rollback()
    c.close()


def user(cr, name):
    cr.execute("insert into app_user(username,password_hash) values (%s,'x') returning id", (name,))
    return cr.fetchone()[0]


def revision(cr, author):
    cr.execute("insert into workspace(slug,name) values ('t-ws','t') returning id")
    ws = cr.fetchone()[0]
    cr.execute("insert into pipeline(workspace_id,name,created_by) values (%s,'p',%s) returning id", (ws, author))
    pid = cr.fetchone()[0]
    ck = hashlib.sha256(b"spec").hexdigest()
    cr.execute("insert into pipeline_revision(pipeline_id,spec,checksum,created_by) values (%s,'{}',%s,%s) returning id",
               (pid, ck, author))
    return cr.fetchone()[0], ck


def denied(cr, sql, args=()):
    cr.execute("savepoint s")
    with pytest.raises(psycopg2.Error) as ei:
        cr.execute(sql, args)
    cr.execute("rollback to savepoint s")
    return ei.value


def test_audit_event_is_append_only(cur):
    cur.execute("insert into audit_event(action,outcome) values ('t','allow') returning id")
    i = cur.fetchone()[0]
    assert denied(cur, "update audit_event set action='x' where id=%s", (i,)).pgcode == "42501"
    assert denied(cur, "delete from audit_event where id=%s", (i,)).pgcode == "42501"
    assert denied(cur, "truncate audit_event").pgcode == "42501"


def test_app_role_cannot_ddl(cur):
    assert denied(cur, "create table uetl_meta.x(i int)").pgcode == "42501"


def test_author_cannot_decide_own_revision(cur):
    a = user(cur, "author1")
    rid, ck = revision(cur, a)
    cur.execute("update pipeline_revision set state='in_review' where id=%s", (rid,))
    err = denied(cur, "insert into approval_decision(revision_id,checksum,decided_by,decision) values (%s,%s,%s,'approve')",
                 (rid, ck, a))
    assert "author cannot decide" in str(err)


def test_checksum_mismatch_and_state_rejected(cur):
    a, r = user(cur, "author2"), user(cur, "reviewer2")
    rid, ck = revision(cur, a)
    ins = "insert into approval_decision(revision_id,checksum,decided_by,decision) values (%s,%s,%s,'approve')"
    assert "not in_review" in str(denied(cur, ins, (rid, ck, r)))
    cur.execute("update pipeline_revision set state='in_review' where id=%s", (rid,))
    assert "checksum mismatch" in str(denied(cur, ins, (rid, "0" * 64, r)))


def test_valid_approval_then_immutable(cur):
    a, r = user(cur, "author3"), user(cur, "reviewer3")
    rid, ck = revision(cur, a)
    cur.execute("update pipeline_revision set state='in_review' where id=%s", (rid,))
    cur.execute("insert into approval_decision(revision_id,checksum,decided_by,decision) values (%s,%s,%s,'approve') returning id",
                (rid, ck, r))
    did = cur.fetchone()[0]
    cur.execute("update pipeline_revision set state='approved' where id=%s", (rid,))
    assert "immutable" in str(denied(cur, "update pipeline_revision set spec='{\"x\":1}' where id=%s", (rid,)))
    assert denied(cur, "update pipeline_revision set state='draft' where id=%s", (rid,)).pgcode == "42501"
    assert denied(cur, "delete from pipeline_revision where id=%s", (rid,)).pgcode == "42501"
    assert denied(cur, "update approval_decision set decision='reject' where id=%s", (did,)).pgcode == "42501"
    assert denied(cur, "delete from approval_decision where id=%s", (did,)).pgcode == "42501"


def test_workspace_slug_and_role_constraints(cur):
    assert denied(cur, "insert into workspace(slug,name) values ('Bad Slug','x')").pgcode == "23514"
    u = user(cur, "u9")
    cur.execute("insert into workspace(slug,name) values ('ok-ws','x') returning id")
    ws = cur.fetchone()[0]
    assert denied(cur, "insert into membership(workspace_id,user_id,role) values (%s,%s,'god')", (ws, u)).pgcode == "23514"
