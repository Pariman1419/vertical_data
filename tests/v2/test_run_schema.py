"""Migration 0007 (run/worker schema) guards. TESTED LIVE against spiec_verti inside ONE transaction that is
always rolled back: the migration is applied and reverted in that transaction, nothing is persisted.
Skipped when .env or the database is unavailable."""
import hashlib
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "backend"))
psycopg2 = pytest.importorskip("psycopg2")
import migrate  # noqa: E402

MIG = pathlib.Path(__file__).resolve().parents[2] / "backend" / "migrations"


@pytest.fixture()
def cur():
    try:
        c = migrate.connect()
    except Exception as ex:  # pragma: no cover
        pytest.skip(f"database unavailable: {ex}")
    cr = c.cursor()
    cr.execute("select 1 from schema_migration where name='0007_run_worker'") if _has_table(cr) else None
    if _has_table(cr) and cr.fetchone():
        c.rollback(); c.close()
        pytest.skip("0007 already applied on this database; the test applies it itself")
    cr.execute((MIG / "0007_run_worker.up.sql").read_text())
    yield cr
    c.rollback()
    c.close()


def _has_table(cr):
    cr.execute("select to_regclass('schema_migration') is not null")
    return cr.fetchone()[0]


def err(cr, sql, args=()):
    cr.execute("savepoint s")
    with pytest.raises(psycopg2.Error) as ei:
        cr.execute(sql, args)
    cr.execute("rollback to savepoint s")
    return ei.value


def world(cr, approved=True):
    cr.execute("insert into app_user(username,password_hash) values ('t_rs_u','x') returning id")
    uid = cr.fetchone()[0]
    cr.execute("insert into workspace(slug,name) values ('t-rs','t') returning id")
    ws = cr.fetchone()[0]
    cr.execute("insert into pipeline(workspace_id,name,created_by) values (%s,'p',%s) returning id", (ws, uid))
    pid = cr.fetchone()[0]
    cr.execute("insert into pipeline_revision(pipeline_id,spec,checksum,created_by) values (%s,'{}',%s,%s) returning id",
               (pid, hashlib.sha256(b"s").hexdigest(), uid))
    rev = cr.fetchone()[0]
    if approved:
        cr.execute("update pipeline_revision set state='approved' where id=%s", (rev,))
    return uid, ws, rev


def new_run(cr, uid, ws, rev, key="k1", **cols):
    cr.execute("insert into job_run(revision_id,workspace_id,idempotency_key,requested_by) values (%s,%s,%s,%s) returning id",
               (rev, ws, key, uid))
    rid = cr.fetchone()[0]
    for k, v in cols.items():
        cr.execute(f"update job_run set {k}=%s where id=%s", (v, rid))
    return rid


def expire_lease(cr, rid):
    cr.execute("update job_run set lease_expires_at = clock_timestamp() - interval '1 second' where id=%s", (rid,))


def test_only_an_approved_revision_in_its_own_workspace_can_run(cur):
    uid, ws, rev = world(cur, approved=False)
    assert "approved" in str(err(cur, "insert into job_run(revision_id,workspace_id,idempotency_key,requested_by)"
                                 " values (%s,%s,'k',%s)", (rev, ws, uid)))
    cur.execute("update pipeline_revision set state='approved' where id=%s", (rev,))
    cur.execute("insert into workspace(slug,name) values ('t-rs2','t') returning id")
    other = cur.fetchone()[0]
    assert "another workspace" in str(err(cur, "insert into job_run(revision_id,workspace_id,idempotency_key,requested_by)"
                                          " values (%s,%s,'k',%s)", (rev, other, uid)))
    new_run(cur, uid, ws, rev)
    assert isinstance(err(cur, "insert into job_run(revision_id,workspace_id,idempotency_key,requested_by)"
                          " values (%s,%s,'k1',%s)", (rev, ws, uid)), psycopg2.errors.UniqueViolation)


def test_claim_is_exclusive_and_a_takeover_fences_the_old_holder(cur):
    uid, ws, rev = world(cur)
    rid = new_run(cur, uid, ws, rev)
    cur.execute("select claim_run(%s,'w1',30)", (rid,)); f1 = cur.fetchone()[0]
    assert f1 == 1
    cur.execute("select claim_run(%s,'w2',30)", (rid,))
    assert cur.fetchone()[0] is None                                   # live lease: second claimant gets nothing
    cur.execute("select run_fence_check(%s,%s)", (rid, f1))             # holder passes
    expire_lease(cur, rid)
    assert "stale" in str(err(cur, "select run_fence_check(%s,%s)", (rid, f1)))   # expired lease also fails
    cur.execute("select claim_run(%s,'w2',30)", (rid,)); f2 = cur.fetchone()[0]
    assert f2 == 2
    assert "stale" in str(err(cur, "select run_fence_check(%s,%s)", (rid, f1)))   # late write of the old worker
    cur.execute("select run_fence_check(%s,%s)", (rid, f2))
    cur.execute("select attempt from job_run where id=%s", (rid,))
    assert cur.fetchone()[0] == 2


def test_heartbeat_extends_only_for_the_current_holder(cur):
    uid, ws, rev = world(cur)
    rid = new_run(cur, uid, ws, rev)
    cur.execute("select claim_run(%s,'w1',30)", (rid,)); f = cur.fetchone()[0]
    cur.execute("select heartbeat_run(%s,%s,60)", (rid, f)); assert cur.fetchone()[0] is True
    cur.execute("select heartbeat_run(%s,%s,60)", (rid, f + 1)); assert cur.fetchone()[0] is False
    expire_lease(cur, rid)
    cur.execute("select heartbeat_run(%s,%s,60)", (rid, f)); assert cur.fetchone()[0] is False   # lost the run


def test_attempt_budget_and_cancel_block_claims(cur):
    uid, ws, rev = world(cur)
    rid = new_run(cur, uid, ws, rev, max_attempts=1)
    cur.execute("select claim_run(%s,'w1',30)", (rid,)); assert cur.fetchone()[0] == 1
    expire_lease(cur, rid)
    cur.execute("select claim_run(%s,'w2',30)", (rid,)); assert cur.fetchone()[0] is None       # budget used up
    rid2 = new_run(cur, uid, ws, rev, key="k2", cancel_requested=True)
    cur.execute("select claim_run(%s,'w1',30)", (rid2,)); assert cur.fetchone()[0] is None
    rid3 = new_run(cur, uid, ws, rev, key="k3", next_attempt_at="2999-01-01")
    cur.execute("select claim_run(%s,'w1',30)", (rid3,)); assert cur.fetchone()[0] is None       # backoff not elapsed


def test_state_machine_and_terminal_states(cur):
    uid, ws, rev = world(cur)
    rid = new_run(cur, uid, ws, rev)
    assert "illegal" in str(err(cur, "update job_run set state='succeeded' where id=%s", (rid,)))   # queued -> succeeded
    cur.execute("select claim_run(%s,'w',30)", (rid,))
    cur.execute("update job_run set state='failed', error_code='source_error' where id=%s", (rid,))
    cur.execute("select finished_at is not null from job_run where id=%s", (rid,)); assert cur.fetchone()[0]
    cur.execute("update job_run set state='queued' where id=%s", (rid,))                 # operator retry
    cur.execute("select attempt, error_code, finished_at from job_run where id=%s", (rid,))
    assert tuple(cur.fetchone()) == (0, None, None)
    cur.execute("select claim_run(%s,'w',30)", (rid,))
    cur.execute("update job_run set state='publishing' where id=%s", (rid,))
    assert "illegal" in str(err(cur, "update job_run set state='cancelled' where id=%s", (rid,)))   # no cancel mid-publish
    cur.execute("update job_run set state='succeeded' where id=%s", (rid,))
    assert "terminal" in str(err(cur, "update job_run set state='queued' where id=%s", (rid,)))
    assert "backwards" in str(err(cur, "update job_run set fence=0 where id=%s", (rid,)))
    assert "immutable" in str(err(cur, "update job_run set idempotency_key='zz' where id=%s", (rid,)))


def test_one_generation_per_run_and_append_only_logs(cur):
    uid, ws, rev = world(cur)
    rid = new_run(cur, uid, ws, rev)
    cur.execute("insert into dataset(workspace_id,target_table) values (%s,'t_out') returning id", (ws,))
    ds = cur.fetchone()[0]
    ins = "insert into dataset_generation(dataset_id,generation,revision_id,run_id,table_name) values (%s,%s,%s,%s,%s)"
    cur.execute(ins, (ds, 1, rev, rid, "t_out_g1"))
    assert "duplicate" in str(err(cur, ins, (ds, 2, rev, rid, "t_out_g2"))).lower()          # duplicate delivery cannot publish twice
    assert err(cur, ins, (ds, 3, rev, None, "Bad Name"))                                          # table-name whitelist
    cur.execute("insert into job_event(run_id,kind,detail) values (%s,'claimed','{}')", (rid,))
    assert err(cur, "update job_event set kind='other' where run_id=%s", (rid,))
    assert err(cur, "insert into job_event(run_id,kind,detail) values (%s,'Bad Kind','{}')", (rid,))
    cur.execute("insert into dead_letter(run_id,workspace_id,reason) values (%s,%s,'attempts_exhausted')", (rid, ws))
    assert err(cur, "delete from dead_letter where run_id=%s", (rid,))


def test_down_then_up_round_trips(cur):
    cur.execute((MIG / "0007_run_worker.down.sql").read_text())
    cur.execute("select count(*) from information_schema.columns where table_name='job_run' and column_name='fence'")
    assert cur.fetchone()[0] == 0
    cur.execute((MIG / "0007_run_worker.up.sql").read_text())
    cur.execute("select count(*) from information_schema.columns where table_name='job_run' and column_name='fence'")
    assert cur.fetchone()[0] == 1
