"""Tests for Worker execution, heartbeat, cooperative cancellation, retry backoff,
dead-letter queuing, and Reaper recovery (Phase 3 Task 5).

TESTED LIVE against spiec_verti inside a transaction that is always rolled back.
"""
import hashlib
import pathlib
import sys
import uuid
import unittest.mock as mock

import pyarrow as pa
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "backend"))
psycopg2 = pytest.importorskip("psycopg2")
import psycopg2.extras
import migrate  # noqa: E402
from backend.v2 import etl, reaper, worker  # noqa: E402

MIG = pathlib.Path(__file__).resolve().parents[2] / "backend" / "migrations"


@pytest.fixture()
def db():
    """Provides a connection with 0007 and 0008 schemas applied in a single transaction that is always rolled back."""
    try:
        c = migrate.connect()
    except Exception as ex:  # pragma: no cover
        pytest.skip(f"database unavailable: {ex}")
    cr = c.cursor()
    cr.execute("SELECT 1 FROM information_schema.tables WHERE table_schema='uetl_meta' AND table_name='dead_letter'")
    if not cr.fetchone():
        cr.execute((MIG / "0007_run_worker.up.sql").read_text())
    cr.execute("SELECT (to_regproc('uetl_meta.worker_create_staging_table') IS NOT NULL) AS has_helper")
    if not cr.fetchone()[0]:
        cr.execute((MIG / "0008_worker_ddl.up.sql").read_text())
    yield c, cr
    c.rollback()
    c.close()


def _make_run(cr, target_name="worker_test_ds", max_attempts=3):
    """Helper to create test workspace, pipeline, approved revision, and queued job_run."""
    cr.execute("INSERT INTO app_user(username, password_hash) VALUES (%s, 'x') RETURNING id",
               (f"u_{uuid.uuid4().hex[:8]}",))
    uid = cr.fetchone()[0]
    cr.execute("INSERT INTO workspace(slug, name) VALUES (%s, 'worker-ws') RETURNING id",
               (f"ws-{uuid.uuid4().hex[:8]}",))
    ws = cr.fetchone()[0]
    cr.execute("INSERT INTO pipeline(workspace_id, name, created_by) VALUES (%s, %s, %s) RETURNING id",
               (ws, target_name, uid))
    pid = cr.fetchone()[0]
    spec = {"target_name": target_name, "dataset": "test_ds", "max_rows": 1000, "max_bytes": 1000000, "max_seconds": 60}
    cr.execute(
        """INSERT INTO pipeline_revision(pipeline_id, spec, checksum, state, created_by)
           VALUES (%s, %s, %s, 'approved', %s) RETURNING id""",
        (pid, psycopg2.extras.Json(spec), hashlib.sha256(b"worker-spec").hexdigest(), uid)
    )
    rev = cr.fetchone()[0]
    cr.execute(
        """INSERT INTO job_run(revision_id, workspace_id, idempotency_key, requested_by, max_attempts)
           VALUES (%s, %s, %s, %s, %s) RETURNING id""",
        (rev, ws, f"idem-{uuid.uuid4().hex[:8]}", uid, max_attempts)
    )
    run_id = cr.fetchone()[0]
    return {"user_id": uid, "workspace_id": ws, "pipeline_id": pid, "revision_id": rev, "run_id": run_id, "target_name": target_name}


def test_worker_claim_and_execute_success(db):
    """Worker claims queued run, stages batches, publishes generation, and marks state succeeded."""
    c, cr = db
    ctx = _make_run(cr, target_name=f"t_wk_{uuid.uuid4().hex[:6]}")
    run_id = ctx["run_id"]

    class ConnWrapper:
        def __init__(self, conn): self.conn = conn
        def cursor(self): return self.conn.cursor()
        def commit(self): pass
        def rollback(self): pass
        def close(self): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass

    wrapper = ConnWrapper(c)

    # Mock extract_batches to yield a small batch
    batch = pa.record_batch([pa.array([1, 2, 3])], names=["metric"])
    with mock.patch("backend.v2.etl.extract_batches", return_value=[batch]):
        # Run worker execution
        worker.execute_run(str(run_id), worker_id="test-worker-1", db_factory=lambda: wrapper)

    # Verify run succeeded
    cr.execute("SELECT state, attempt, rows_read, finished_at FROM job_run WHERE id = %s", (run_id,))
    state, attempt, rows_read, fin = cr.fetchone()
    assert state == "succeeded"
    assert attempt == 1
    assert rows_read == 3
    assert fin is not None

    # Verify published view exists and returns 3 rows
    cr.execute(f"SELECT COUNT(*) FROM uetl_published.{ctx['target_name']}")
    assert cr.fetchone()[0] == 3

    # Verify events
    cr.execute("SELECT kind FROM job_event WHERE run_id = %s ORDER BY id ASC", (run_id,))
    events = [r[0] for r in cr.fetchall()]
    assert "run.started" in events
    assert "run.publishing" in events
    assert "run.succeeded" in events


def test_worker_fenced_write_rejection_on_expired_lease(db):
    """If a worker's lease expires and another claims it, late writes are rejected by fence check."""
    c, cr = db
    ctx = _make_run(cr)
    run_id = ctx["run_id"]

    # Worker 1 claims with 1 second lease
    cr.execute("SELECT claim_run(%s, 'worker-1', 1)", (run_id,))
    fence1 = cr.fetchone()[0]
    assert fence1 == 1

    # Staging with active fence 1 succeeds
    stg_tbl = etl.staging_table_name(run_id, 0)
    batch = pa.record_batch([pa.array([42])], names=["val"])
    etl.stage_batch(cr, run_id, fence1, stg_tbl, batch)

    # Simulate lease expiry
    cr.execute("UPDATE job_run SET lease_expires_at = clock_timestamp() - interval '1 second' WHERE id = %s", (run_id,))

    # Worker 1's fence check now fails within a savepoint
    cr.execute("SAVEPOINT sp_fence_test")
    with pytest.raises(Exception) as exc:
        etl.stage_batch(cr, run_id, fence1, stg_tbl, batch)
    assert "stale" in str(exc.value).lower()
    cr.execute("ROLLBACK TO SAVEPOINT sp_fence_test")

    # Worker 2 can now claim the run and gets fence 2
    cr.execute("SELECT claim_run(%s, 'worker-2', 60)", (run_id,))
    fence2 = cr.fetchone()[0]
    assert fence2 == 2

    # Worker 2 stages batch successfully
    etl.stage_batch(cr, run_id, fence2, stg_tbl, batch)


def test_worker_cooperative_cancellation(db):
    """When cancel_requested is true during execution, worker aborts and marks state cancelled."""
    c, cr = db
    ctx = _make_run(cr)
    run_id = ctx["run_id"]

    class ConnWrapper:
        def __init__(self, conn): self.conn = conn
        def cursor(self): return self.conn.cursor()
        def commit(self): pass
        def rollback(self): pass
        def close(self): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass

    wrapper = ConnWrapper(c)

    def extract_with_cancel_signal(*a, **kw):
        # Yield first batch
        yield pa.record_batch([pa.array([1, 2])], names=["val"])
        # Simulate operator cancellation request while job is running
        cr.execute("UPDATE job_run SET cancel_requested = true WHERE id = %s", (run_id,))
        # Yield second batch
        yield pa.record_batch([pa.array([3, 4])], names=["val"])

    with mock.patch("backend.v2.etl.extract_batches", side_effect=extract_with_cancel_signal):
        worker.execute_run(str(run_id), worker_id="test-worker-cancel", db_factory=lambda: wrapper)

    # Verify run marked as cancelled
    cr.execute("SELECT state, cancel_requested, finished_at FROM job_run WHERE id = %s", (run_id,))
    state, cancel_req, fin = cr.fetchone()
    assert state == "cancelled"
    assert cancel_req is True
    assert fin is not None


def test_worker_retry_backoff_and_dead_letter(db):
    """Failures trigger retry with exponential backoff up to max_attempts, then transition to dead."""
    c, cr = db
    ctx = _make_run(cr, max_attempts=2)
    run_id = ctx["run_id"]

    class ConnWrapper:
        def __init__(self, conn): self.conn = conn
        def cursor(self): return self.conn.cursor()
        def commit(self): pass
        def rollback(self): pass
        def close(self): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass

    wrapper = ConnWrapper(c)

    # 1. Failure on Attempt 1 -> state queued with next_attempt_at in the future
    with mock.patch("backend.v2.worker._run_pipeline", side_effect=RuntimeError("connection dropped")):
        worker.execute_run(str(run_id), worker_id="test-worker", db_factory=lambda: wrapper)

    cr.execute("SELECT state, attempt, next_attempt_at, error_code FROM job_run WHERE id = %s", (run_id,))
    state1, att1, next_att1, err1 = cr.fetchone()
    assert state1 == "queued"
    assert att1 == 1
    assert next_att1 is not None
    assert "runtimeerror" in err1.lower()

    # Reset next_attempt_at to simulate backoff elapsing
    cr.execute("UPDATE job_run SET next_attempt_at = clock_timestamp() - interval '1 second' WHERE id = %s", (run_id,))

    # 2. Failure on Attempt 2 (exhausts max_attempts=2) -> transitions to 'dead'
    with mock.patch("backend.v2.worker._run_pipeline", side_effect=RuntimeError("connection dropped again")):
        worker.execute_run(str(run_id), worker_id="test-worker", db_factory=lambda: wrapper)

    cr.execute("SELECT state, attempt, error_code, finished_at FROM job_run WHERE id = %s", (run_id,))
    state2, att2, err2, fin2 = cr.fetchone()
    assert state2 == "dead"
    assert att2 == 2
    assert fin2 is not None

    # Verify recorded in dead_letter table
    cr.execute("SELECT reason, workspace_id FROM dead_letter WHERE run_id = %s", (run_id,))
    dl_row = cr.fetchone()
    assert dl_row is not None
    assert "runtimeerror" in dl_row[0].lower()
    assert dl_row[1] == ctx["workspace_id"]


def test_reaper_reap_stuck_runs_and_dead_leases(db):
    """Reaper discovers eligible queued runs to re-enqueue and recovers expired leases."""
    c, cr = db
    ctx = _make_run(cr, max_attempts=2)
    run_id = ctx["run_id"]

    class SharedDb:
        def __init__(self, conn): self.conn = conn
        def cursor(self): return self.conn.cursor()

    shared_db = SharedDb(c)

    # 1. Test reap_stuck_runs
    with mock.patch("backend.v2.worker.enqueue_run", return_value=True) as mock_enq:
        reaped = reaper.reap_stuck_runs(shared_db)
        assert reaped == 1
        mock_enq.assert_called_with(str(run_id))

    # 2. Test expire_dead_leases: worker claimed run, then crashed and lease expired
    cr.execute("SELECT claim_run(%s, 'crashed-worker', 1)", (run_id,))
    cr.execute("UPDATE job_run SET lease_expires_at = clock_timestamp() - interval '5 seconds' WHERE id = %s", (run_id,))

    with mock.patch("backend.v2.worker.enqueue_run", return_value=True):
        count = reaper.expire_dead_leases(shared_db)
        assert count == 1

    # Run was reset to queued for retry since attempt (1) < max_attempts (2)
    cr.execute("SELECT state, lease_owner FROM job_run WHERE id = %s", (run_id,))
    st, owner = cr.fetchone()
    assert st == "queued"
    assert owner is None
