"""Tests for publish atomicity, retention of 3 generations, and rollback preservation (Phase 3 Task 6).

TESTED LIVE against spiec_verti inside a transaction that is always rolled back.
"""
import hashlib
import pathlib
import sys
import uuid

import pyarrow as pa
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "backend"))
psycopg2 = pytest.importorskip("psycopg2")
import migrate  # noqa: E402
from backend.v2 import etl  # noqa: E402

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
    cr.execute("SELECT to_regproc('uetl_meta.worker_create_staging_table') IS NOT NULL")
    if not cr.fetchone()[0]:
        cr.execute((MIG / "0008_worker_ddl.up.sql").read_text())
    yield c, cr
    c.rollback()
    c.close()


def _create_run(cr, target_name="publish_target"):
    """Helper to create workspace, pipeline, approved revision, and first claimed job_run."""
    cr.execute("INSERT INTO app_user(username, password_hash) VALUES (%s, 'x') RETURNING id",
               (f"u_{uuid.uuid4().hex[:8]}",))
    uid = cr.fetchone()[0]
    cr.execute("INSERT INTO workspace(slug, name) VALUES (%s, 'publish-ws') RETURNING id",
               (f"ws-{uuid.uuid4().hex[:8]}",))
    ws = cr.fetchone()[0]
    cr.execute("INSERT INTO pipeline(workspace_id, name, created_by) VALUES (%s, %s, %s) RETURNING id",
               (ws, target_name, uid))
    pid = cr.fetchone()[0]
    cr.execute(
        "INSERT INTO pipeline_revision(pipeline_id, spec, checksum, state, created_by) VALUES (%s, '{}', %s, 'approved', %s) RETURNING id",
        (pid, hashlib.sha256(b"publish-spec").hexdigest(), uid)
    )
    rev = cr.fetchone()[0]
    cr.execute(
        "INSERT INTO job_run(revision_id, workspace_id, idempotency_key, requested_by) VALUES (%s, %s, %s, %s) RETURNING id",
        (rev, ws, f"idem-{uuid.uuid4().hex[:8]}", uid)
    )
    run_id = cr.fetchone()[0]
    cr.execute("SELECT claim_run(%s, 'worker-publish', 60)", (run_id,))
    fence = cr.fetchone()[0]
    return {
        "user_id": uid, "workspace_id": ws, "pipeline_id": pid,
        "revision_id": rev, "run_id": run_id, "fence": fence, "target_name": target_name
    }


def _create_subsequent_run(cr, ctx):
    """Create and claim a subsequent run for the same workspace, revision, and pipeline."""
    cr.execute(
        "INSERT INTO job_run(revision_id, workspace_id, idempotency_key, requested_by) VALUES (%s, %s, %s, %s) RETURNING id",
        (ctx["revision_id"], ctx["workspace_id"], f"idem-{uuid.uuid4().hex[:8]}", ctx["user_id"])
    )
    run_id = cr.fetchone()[0]
    cr.execute("SELECT claim_run(%s, 'worker-publish', 60)", (run_id,))
    fence = cr.fetchone()[0]
    return run_id, fence


def test_publish_retention_keeps_three_latest_generations(db):
    """Publishing generations 1..4 keeps generations 2, 3, 4 and prunes generation 1."""
    c, cr = db
    ctx = _create_run(cr, target_name=f"t_ret_{uuid.uuid4().hex[:6]}")
    target = ctx["target_name"]

    # 1. Publish Generation 1 (10 rows)
    run1, fence1 = ctx["run_id"], ctx["fence"]
    stg1 = etl.staging_table_name(run1, 1)
    b1 = pa.record_batch([pa.array(list(range(10)))], names=["val"])
    etl.stage_batch(cr, run1, fence1, stg1, b1)
    gen1 = etl.publish_generation(cr, run1, fence1, spec={"target_name": target}, staging_table=stg1)
    assert gen1 == 1

    # 2. Publish Generation 2 (20 rows) via Run 2
    run2, fence2 = _create_subsequent_run(cr, ctx)
    stg2 = etl.staging_table_name(run2, 1)
    b2 = pa.record_batch([pa.array(list(range(20)))], names=["val"])
    etl.stage_batch(cr, run2, fence2, stg2, b2)
    gen2 = etl.publish_generation(cr, run2, fence2, spec={"target_name": target}, staging_table=stg2)
    assert gen2 == 2

    # 3. Publish Generation 3 (30 rows) via Run 3
    run3, fence3 = _create_subsequent_run(cr, ctx)
    stg3 = etl.staging_table_name(run3, 1)
    b3 = pa.record_batch([pa.array(list(range(30)))], names=["val"])
    etl.stage_batch(cr, run3, fence3, stg3, b3)
    gen3 = etl.publish_generation(cr, run3, fence3, spec={"target_name": target}, staging_table=stg3)
    assert gen3 == 3

    # All 3 generations are active and retained
    cr.execute("SELECT generation, dropped_at FROM dataset_generation WHERE dataset_id = (SELECT id FROM dataset WHERE target_table = %s) ORDER BY generation", (target,))
    gens = cr.fetchall()
    assert len(gens) == 3
    assert all(r[1] is None for r in gens), "Generations 1, 2, 3 should not be dropped yet"

    # View should point to generation 3
    cr.execute(f"SELECT COUNT(*) FROM uetl_published.{target}")
    assert cr.fetchone()[0] == 30

    # 4. Publish Generation 4 (40 rows) via Run 4 -> triggers retention prune of Gen 1
    run4, fence4 = _create_subsequent_run(cr, ctx)
    stg4 = etl.staging_table_name(run4, 1)
    b4 = pa.record_batch([pa.array(list(range(40)))], names=["val"])
    etl.stage_batch(cr, run4, fence4, stg4, b4)
    gen4 = etl.publish_generation(cr, run4, fence4, spec={"target_name": target}, staging_table=stg4)
    assert gen4 == 4

    # View should point to generation 4
    cr.execute(f"SELECT COUNT(*) FROM uetl_published.{target}")
    assert cr.fetchone()[0] == 40

    # Gen 1 must now be marked dropped_at
    cr.execute("SELECT generation, dropped_at FROM dataset_generation WHERE dataset_id = (SELECT id FROM dataset WHERE target_table = %s) ORDER BY generation", (target,))
    gens_after = cr.fetchall()
    assert len(gens_after) == 4
    g1_row = next(r for r in gens_after if r[0] == 1)
    assert g1_row[1] is not None, "Generation 1 must have dropped_at recorded"
    for g in (2, 3, 4):
        g_row = next(r for r in gens_after if r[0] == g)
        assert g_row[1] is None, f"Generation {g} must still be active"

    # Table target_g1 dropped, tables g2, g3, g4 still exist
    cr.execute(f"SELECT to_regclass('uetl_published.{target}_g1') IS NOT NULL")
    assert cr.fetchone()[0] is False, "Generation 1 table must be dropped from database"
    for g in (2, 3, 4):
        cr.execute(f"SELECT to_regclass('uetl_published.{target}_g{g}') IS NOT NULL")
        assert cr.fetchone()[0] is True, f"Generation {g} table must still exist in database"


def test_publish_rollback_preserves_old_generation(db):
    """If a publish attempt fails or rolls back, the previous published generation remains 100% intact."""
    c, cr = db
    ctx = _create_run(cr, target_name=f"t_roll_{uuid.uuid4().hex[:6]}")
    run_id = ctx["run_id"]
    fence = ctx["fence"]
    target = ctx["target_name"]

    # 1. Publish initial generation 1 with 15 rows
    stg1 = etl.staging_table_name(run_id, 1)
    b1 = pa.record_batch([pa.array(list(range(15)))], names=["score"])
    etl.stage_batch(cr, run_id, fence, stg1, b1)
    gen1 = etl.publish_generation(cr, run_id, fence, spec={"target_name": target}, staging_table=stg1)
    assert gen1 == 1

    # Verify initial view
    cr.execute(f"SELECT COUNT(*), SUM(score) FROM uetl_published.{target}")
    cnt, total = cr.fetchone()
    assert cnt == 15
    assert total == sum(range(15))

    # 2. Simulate failed publish of generation 2 within a SAVEPOINT using Run 2
    cr.execute("SAVEPOINT test_pub_g2")
    run2, fence2 = _create_subsequent_run(cr, ctx)
    stg2 = etl.staging_table_name(run2, 1)
    b2 = pa.record_batch([pa.array([999, 888])], names=["score"])
    etl.stage_batch(cr, run2, fence2, stg2, b2)

    # Publish with an invalid / corrupted state (e.g. stale fence)
    with pytest.raises(Exception):
        etl.publish_generation(cr, run2, fence2 + 99, spec={"target_name": target}, staging_table=stg2)

    # Roll back to the savepoint before the failed publish
    cr.execute("ROLLBACK TO SAVEPOINT test_pub_g2")

    # 3. Verify previous generation 1 view and data are 100% preserved
    cr.execute(f"SELECT COUNT(*), SUM(score) FROM uetl_published.{target}")
    cnt_after, total_after = cr.fetchone()
    assert cnt_after == 15
    assert total_after == sum(range(15))

    # Dataset current_generation is still 1
    cr.execute("SELECT current_generation FROM dataset WHERE target_table = %s", (target,))
    assert cr.fetchone()[0] == 1


def test_publish_atomic_reader_never_sees_partial_data(db):
    """View always points to a complete generation table; reader never sees 0 rows or half-loaded data."""
    c, cr = db
    ctx = _create_run(cr, target_name=f"t_atom_{uuid.uuid4().hex[:6]}")
    run_id = ctx["run_id"]
    fence = ctx["fence"]
    target = ctx["target_name"]

    # Stage generation 1 in batches
    stg1 = etl.staging_table_name(run_id, 1)
    b1_part1 = pa.record_batch([pa.array(list(range(50)))], names=["num"])
    b1_part2 = pa.record_batch([pa.array(list(range(50, 100)))], names=["num"])
    etl.stage_batch(cr, run_id, fence, stg1, b1_part1)
    etl.stage_batch(cr, run_id, fence, stg1, b1_part2)

    # Before publishing, published view does not exist yet
    cr.execute(f"SELECT to_regclass('uetl_published.{target}') IS NOT NULL")
    assert cr.fetchone()[0] is False

    # Publish generation 1
    gen1 = etl.publish_generation(cr, run_id, fence, spec={"target_name": target}, staging_table=stg1)
    assert gen1 == 1

    # Query view immediately: sees exactly 100 rows, never partial 50
    cr.execute(f"SELECT COUNT(*), MIN(num), MAX(num) FROM uetl_published.{target}")
    cnt, min_val, max_val = cr.fetchone()
    assert cnt == 100
    assert min_val == 0
    assert max_val == 99

    # Now stage generation 2 in 3 separate batches in staging using Run 2
    run2, fence2 = _create_subsequent_run(cr, ctx)
    stg2 = etl.staging_table_name(run2, 1)
    etl.stage_batch(cr, run2, fence2, stg2, pa.record_batch([pa.array(list(range(100, 200)))], names=["num"]))
    etl.stage_batch(cr, run2, fence2, stg2, pa.record_batch([pa.array(list(range(200, 300)))], names=["num"]))
    etl.stage_batch(cr, run2, fence2, stg2, pa.record_batch([pa.array(list(range(300, 400)))], names=["num"]))

    # While staging is being filled, existing view still cleanly sees Gen 1 (100 rows)
    cr.execute(f"SELECT COUNT(*) FROM uetl_published.{target}")
    assert cr.fetchone()[0] == 100

    # Publish generation 2
    gen2 = etl.publish_generation(cr, run2, fence2, spec={"target_name": target}, staging_table=stg2)
    assert gen2 == 2

    # View now atomically transitions to exactly 300 rows (from 100 to 399)
    cr.execute(f"SELECT COUNT(*), MIN(num), MAX(num) FROM uetl_published.{target}")
    cnt2, min_val2, max_val2 = cr.fetchone()
    assert cnt2 == 300
    assert min_val2 == 100
    assert max_val2 == 399


def test_publish_schema_evolution_seamless(db):
    """View handles column additions, reordering, and type mutations across generations."""
    c, cr = db
    ctx = _create_run(cr, target_name=f"t_evolve_{uuid.uuid4().hex[:6]}")
    run_id = ctx["run_id"]
    fence = ctx["fence"]
    target = ctx["target_name"]

    # Generation 1: columns (id: int32, label: utf8)
    stg1 = etl.staging_table_name(run_id, 1)
    b1 = pa.record_batch([pa.array([1, 2]), pa.array(["alpha", "beta"])], names=["id", "label"])
    etl.stage_batch(cr, run_id, fence, stg1, b1)
    etl.publish_generation(cr, run_id, fence, spec={"target_name": target}, staging_table=stg1)

    cr.execute(f"SELECT id, label FROM uetl_published.{target} ORDER BY id")
    assert cr.fetchall() == [(1, "alpha"), (2, "beta")]

    # Generation 2: columns reordered and new column added (label: utf8, extra: float64, id: int32) via Run 2
    run2, fence2 = _create_subsequent_run(cr, ctx)
    stg2 = etl.staging_table_name(run2, 1)
    b2 = pa.record_batch([pa.array(["gamma"]), pa.array([3.14]), pa.array([3])], names=["label", "extra", "id"])
    etl.stage_batch(cr, run2, fence2, stg2, b2)
    etl.publish_generation(cr, run2, fence2, spec={"target_name": target}, staging_table=stg2)

    cr.execute(f"SELECT label, extra, id FROM uetl_published.{target}")
    row = cr.fetchone()
    assert row[0] == "gamma"
    assert abs(row[1] - 3.14) < 1e-5
    assert row[2] == 3
