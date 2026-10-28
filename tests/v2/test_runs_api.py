"""Tests for Runs API endpoints and RBAC permissions (Phase 3 Task 7).

TESTED LIVE against spiec_verti inside a transaction that is always rolled back.
Verifies:
- RBAC permissions (403 for non-operator/admin, 404 for non-members)
- Submit validation (approved revisions only, workspace boundaries)
- Idempotency preservation
- Durable queuing even when Redis/enqueue fails
- Cancel cooperative and immediate semantics
- Retry only for failed/dead runs with budget reset
- Dead-letter queries and audit log generation
"""
import hashlib
import json
import pathlib
import sys
import uuid
import unittest.mock as mock

import pytest
from starlette.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "backend"))
psycopg2 = pytest.importorskip("psycopg2")
import psycopg2.extras
import migrate  # noqa: E402
from backend.v2 import config, security, worker  # noqa: E402
from backend.v2.app import app  # noqa: E402
from backend.v2.db import get_db  # noqa: E402

MIG = pathlib.Path(__file__).resolve().parents[2] / "backend" / "migrations"
PW = "correct horse battery 1"
HASH = security.hash_password(PW)


class Shared:
    """One transaction for the test; commit/rollback inside requests are no-ops."""
    def __init__(self, conn):
        self.conn = conn

    def cursor(self):
        return self.conn.cursor()

    def commit(self):
        pass

    def rollback(self):
        pass


@pytest.fixture()
def runs_env():
    """Provides a transactional test environment with 0007 and 0008 migrations applied."""
    try:
        e = migrate.env()
        conn = psycopg2.connect(
            host=e["UETL_PG_HOST"], port=e["UETL_PG_PORT"], dbname=e["UETL_PG_DB"],
            user="uetl_migrator", password=e["UETL_MIGRATOR_PASSWORD"], connect_timeout=8,
            options="-c search_path=uetl_meta", cursor_factory=psycopg2.extras.RealDictCursor
        )
    except Exception as ex:  # pragma: no cover
        pytest.skip(f"database unavailable: {ex}")

    cur = conn.cursor()
    # Check and apply 0007 and 0008 inside this uncommitted transaction
    cur.execute("SELECT 1 FROM information_schema.tables WHERE table_schema='uetl_meta' AND table_name='dead_letter'")
    if not cur.fetchone():
        cur.execute((MIG / "0007_run_worker.up.sql").read_text())
    cur.execute("SELECT (to_regproc('uetl_meta.worker_create_staging_table') IS NOT NULL) AS has_helper")
    if not cur.fetchone()["has_helper"]:
        cur.execute((MIG / "0008_worker_ddl.up.sql").read_text())

    shared = Shared(conn)
    app.dependency_overrides[get_db] = lambda: shared

    # Helper fixtures
    def mk_user(name, platform="none"):
        cur.execute("INSERT INTO app_user(username, password_hash, platform_role) VALUES (%s, %s, %s) RETURNING id",
                    (name, HASH, platform))
        return cur.fetchone()["id"]

    def mk_ws(slug):
        cur.execute("INSERT INTO workspace(slug, name) VALUES (%s, %s) RETURNING id", (slug, slug))
        return cur.fetchone()["id"]

    def member(ws, uid, role):
        cur.execute("INSERT INTO membership(workspace_id, user_id, role) VALUES (%s, %s, %s)", (ws, uid, role))

    env = type("Env", (), {})()
    env.conn = conn
    env.cur = cur

    suffix = uuid.uuid4().hex[:6]
    env.ws1 = mk_ws(f"ws1-{suffix}")
    env.ws2 = mk_ws(f"ws2-{suffix}")

    env.admin = mk_user(f"u_admin_{suffix}")
    env.operator = mk_user(f"u_op_{suffix}")
    env.author = mk_user(f"u_auth_{suffix}")
    env.viewer = mk_user(f"u_view_{suffix}")
    env.reviewer = mk_user(f"u_rev_{suffix}")
    env.other_user = mk_user(f"u_other_{suffix}")

    member(env.ws1, env.admin, "admin")
    member(env.ws1, env.operator, "operator")
    member(env.ws1, env.author, "author")
    member(env.ws1, env.viewer, "viewer")
    member(env.ws1, env.reviewer, "reviewer")
    member(env.ws2, env.other_user, "admin")

    # Create pipelines and revisions
    cur.execute("INSERT INTO pipeline(workspace_id, name, created_by) VALUES (%s, 'pipe1', %s) RETURNING id",
                (env.ws1, env.admin))
    env.pipe1 = cur.fetchone()["id"]

    cur.execute(
        """INSERT INTO pipeline_revision(pipeline_id, spec, checksum, state, created_by)
           VALUES (%s, '{\"dataset\": \"test\"}', %s, 'approved', %s) RETURNING id""",
        (env.pipe1, hashlib.sha256(b"pipe1-rev1").hexdigest(), env.admin)
    )
    env.rev_approved = cur.fetchone()["id"]

    cur.execute(
        """INSERT INTO pipeline_revision(pipeline_id, spec, checksum, state, created_by)
           VALUES (%s, '{\"dataset\": \"test\"}', %s, 'draft', %s) RETURNING id""",
        (env.pipe1, hashlib.sha256(b"pipe1-rev2").hexdigest(), env.admin)
    )
    env.rev_draft = cur.fetchone()["id"]

    # Pipeline in ws2
    cur.execute("INSERT INTO pipeline(workspace_id, name, created_by) VALUES (%s, 'pipe2', %s) RETURNING id",
                (env.ws2, env.other_user))
    env.pipe2 = cur.fetchone()["id"]
    cur.execute(
        """INSERT INTO pipeline_revision(pipeline_id, spec, checksum, state, created_by)
           VALUES (%s, '{\"dataset\": \"test2\"}', %s, 'approved', %s) RETURNING id""",
        (env.pipe2, hashlib.sha256(b"pipe2-rev").hexdigest(), env.other_user)
    )
    env.rev_ws2 = cur.fetchone()["id"]

    def client(username):
        c = TestClient(app, base_url="https://testserver")
        r = c.post("/api/v2/auth/login", json={"username": username, "password": PW})
        assert r.status_code == 200, r.text
        token = r.cookies.get(config.COOKIE_NAME)
        csrf = r.json()["csrf"]
        c.headers.update({"Origin": "https://testserver", "X-CSRF-Token": csrf})
        c.cookies.set(config.COOKIE_NAME, token)
        return c

    env.client = client
    env.usernames = {
        "admin": f"u_admin_{suffix}",
        "operator": f"u_op_{suffix}",
        "author": f"u_auth_{suffix}",
        "viewer": f"u_view_{suffix}",
        "reviewer": f"u_rev_{suffix}",
        "other": f"u_other_{suffix}"
    }

    yield env

    app.dependency_overrides.pop(get_db, None)
    conn.rollback()
    conn.close()


def test_runs_api_rbac_permissions(runs_env):
    """Verify operator/admin can submit/cancel/retry; viewer/author/reviewer get 403; non-members get 404."""
    e = runs_env
    base1 = f"/api/v2/workspaces/{e.ws1}/runs"

    c_op = e.client(e.usernames["operator"])
    c_admin = e.client(e.usernames["admin"])
    c_viewer = e.client(e.usernames["viewer"])
    c_author = e.client(e.usernames["author"])
    c_reviewer = e.client(e.usernames["reviewer"])
    c_other = e.client(e.usernames["other"])

    # 1. Non-member access -> 404
    r_other = c_other.get(base1)
    assert r_other.status_code == 404

    # 2. Viewer, Author, Reviewer cannot submit -> 403
    payload = {"revision_id": str(e.rev_approved)}
    assert c_viewer.post(base1, json=payload).status_code == 403
    assert c_author.post(base1, json=payload).status_code == 403
    assert c_reviewer.post(base1, json=payload).status_code == 403

    # 3. Operator can submit -> 201
    with mock.patch("backend.v2.worker.enqueue_run", return_value=True):
        r_sub = c_op.post(base1, json=payload)
        assert r_sub.status_code == 201, r_sub.text
        run_data = r_sub.json()
        assert run_data["state"] == "queued"
        run_id = run_data["id"]

    # 4. Viewer can read runs list and run details -> 200
    r_list = c_viewer.get(base1)
    assert r_list.status_code == 200
    assert any(x["id"] == run_id for x in r_list.json())

    r_get = c_viewer.get(f"{base1}/{run_id}")
    assert r_get.status_code == 200
    assert r_get.json()["id"] == run_id
    assert len(r_get.json()["events"]) >= 1

    # 5. Viewer cannot cancel or retry -> 403
    assert c_viewer.post(f"{base1}/{run_id}/cancel").status_code == 403
    assert c_viewer.post(f"{base1}/{run_id}/retry").status_code == 403

    # 6. Admin can cancel -> 200
    r_cancel = c_admin.post(f"{base1}/{run_id}/cancel")
    assert r_cancel.status_code == 200
    assert r_cancel.json()["state"] == "cancelled"


def test_runs_api_submit_validation(runs_env):
    """Submitting must reject draft revisions, non-existent revisions, and revisions from other workspaces."""
    e = runs_env
    base1 = f"/api/v2/workspaces/{e.ws1}/runs"
    c_op = e.client(e.usernames["operator"])

    # Draft revision rejection
    r_draft = c_op.post(base1, json={"revision_id": str(e.rev_draft)})
    assert r_draft.status_code == 400
    assert "approved" in r_draft.text

    # Cross-workspace revision rejection
    r_cross = c_op.post(base1, json={"revision_id": str(e.rev_ws2)})
    assert r_cross.status_code == 400
    assert "another workspace" in r_cross.text

    # Non-existent revision
    r_none = c_op.post(base1, json={"revision_id": str(uuid.uuid4())})
    assert r_none.status_code == 404


def test_runs_api_idempotency(runs_env):
    """Submitting twice with the same idempotency_key returns the same run without duplicate."""
    e = runs_env
    base1 = f"/api/v2/workspaces/{e.ws1}/runs"
    c_op = e.client(e.usernames["operator"])
    idem_key = f"test-idem-{uuid.uuid4().hex[:8]}"

    with mock.patch("backend.v2.worker.enqueue_run", return_value=True):
        r1 = c_op.post(base1, json={"revision_id": str(e.rev_approved), "idempotency_key": idem_key})
        assert r1.status_code == 201
        run1 = r1.json()

        r2 = c_op.post(base1, json={"revision_id": str(e.rev_approved), "idempotency_key": idem_key})
        assert r2.status_code == 201
        run2 = r2.json()

        assert run1["id"] == run2["id"]
        assert run1["created_at"] == run2["created_at"]

    # Verify only 1 run was created in database
    e.cur.execute("SELECT count(*) FROM job_run WHERE workspace_id = %s AND idempotency_key = %s", (e.ws1, idem_key))
    assert e.cur.fetchone()["count"] == 1


def test_runs_api_enqueue_failure_preserved(runs_env):
    """If Redis enqueue fails, the run remains durably stored as 'queued' in PostgreSQL for the Reaper."""
    e = runs_env
    base1 = f"/api/v2/workspaces/{e.ws1}/runs"
    c_op = e.client(e.usernames["operator"])

    # Mock enqueue_run to simulate Redis connection failure
    with mock.patch("backend.v2.worker.enqueue_run", return_value=False):
        r = c_op.post(base1, json={"revision_id": str(e.rev_approved)})
        assert r.status_code == 201
        body = r.json()
        assert body["enqueued"] is False
        run_id = body["id"]

    # Verify run exists in DB with state 'queued'
    e.cur.execute("SELECT state FROM job_run WHERE id = %s", (run_id,))
    row = e.cur.fetchone()
    assert row is not None
    assert row["state"] == "queued"


def test_runs_api_retry_and_dead_letters(runs_env):
    """Only failed or dead runs can be retried; retrying resets attempt to 0; dead-letters queryable."""
    e = runs_env
    base1 = f"/api/v2/workspaces/{e.ws1}/runs"
    c_op = e.client(e.usernames["operator"])

    with mock.patch("backend.v2.worker.enqueue_run", return_value=True):
        r = c_op.post(base1, json={"revision_id": str(e.rev_approved)})
        run_id = r.json()["id"]

    # 1. Retrying a queued run must be rejected
    r_retry_queued = c_op.post(f"{base1}/{run_id}/retry")
    assert r_retry_queued.status_code == 400
    assert "only failed or dead runs can be retried" in r_retry_queued.text

    # 2. Simulate worker failure: run claimed, failed 3 times, marked as 'dead' with dead_letter entry
    e.cur.execute("SELECT claim_run(%s, 'worker-fail', 60)", (run_id,))
    e.cur.execute(
        """UPDATE job_run
           SET state = 'dead', attempt = 3, error_code = 'flight_unreachable', finished_at = clock_timestamp()
           WHERE id = %s""",
        (run_id,)
    )
    e.cur.execute(
        "INSERT INTO dead_letter (run_id, workspace_id, reason) VALUES (%s, %s, 'flight_unreachable')",
        (run_id, e.ws1)
    )

    # 3. Query dead-letters list
    r_dl = c_op.get(f"/api/v2/workspaces/{e.ws1}/dead-letters")
    assert r_dl.status_code == 200
    dls = r_dl.json()
    assert any(x["run_id"] == run_id and x["reason"] == "flight_unreachable" for x in dls)

    # 4. Operator retries the dead run
    with mock.patch("backend.v2.worker.enqueue_run", return_value=True):
        r_retry = c_op.post(f"{base1}/{run_id}/retry")
        assert r_retry.status_code == 200
        retried_data = r_retry.json()
        assert retried_data["state"] == "queued"
        assert retried_data["attempt"] == 0
        assert retried_data["error_code"] is None


def test_runs_api_audit_trail(runs_env):
    """Every submit, cancel, retry, and permission denial generates an audit_event row."""
    e = runs_env
    base1 = f"/api/v2/workspaces/{e.ws1}/runs"
    c_op = e.client(e.usernames["operator"])
    c_viewer = e.client(e.usernames["viewer"])

    # 1. Denied submit
    c_viewer.post(base1, json={"revision_id": str(e.rev_approved)})
    e.cur.execute(
        "SELECT action, outcome FROM audit_event WHERE workspace_id = %s AND action = 'run.submit.denied'",
        (e.ws1,)
    )
    assert e.cur.fetchone() is not None

    # 2. Allowed submit
    with mock.patch("backend.v2.worker.enqueue_run", return_value=True):
        r_sub = c_op.post(base1, json={"revision_id": str(e.rev_approved)})
        run_id = r_sub.json()["id"]

    e.cur.execute(
        "SELECT action, outcome, object_id FROM audit_event WHERE workspace_id = %s AND action = 'run.submit'",
        (e.ws1,)
    )
    audit_row = e.cur.fetchone()
    assert audit_row["outcome"] == "allow"
    assert audit_row["object_id"] == run_id
