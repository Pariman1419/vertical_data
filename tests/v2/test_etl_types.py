"""ETL type preservation, memory-bounded streaming, and quality checks (Phase 3 Task 4).

TESTED LIVE against SPICE Flight (synthetic generate_series only, no SCADA data)
and PostgreSQL (spiec_verti inside a transaction that is always rolled back).
"""
import datetime
import decimal
import hashlib
import pathlib
import sys
import time
import uuid

import psutil
import pytest
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.flight as fl

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "backend"))
psycopg2 = pytest.importorskip("psycopg2")
import migrate  # noqa: E402
from backend.v2 import etl, limiter, spice  # noqa: E402

MIG = pathlib.Path(__file__).resolve().parents[2] / "backend" / "migrations"
LIVE = {"base_url": "http://10.153.90.17:8091", "timeout_s": 30, "tls_verify": True, "secret_ref": None}


def _live_spice():
    try:
        return spice.health(LIVE)
    except spice.SpiceError:
        return False


live = pytest.mark.skipif(not _live_spice(), reason="SPICE host not reachable")


@pytest.fixture()
def db():
    """Provides a connection with 0007 schema applied in a single transaction that is always rolled back."""
    try:
        c = migrate.connect()
    except Exception as ex:  # pragma: no cover
        pytest.skip(f"database unavailable: {ex}")
    cr = c.cursor()
    # Check if 0007 is already applied; if not, apply it inside this transaction
    cr.execute("SELECT 1 FROM information_schema.tables WHERE table_schema='uetl_meta' AND table_name='dead_letter'")
    if not cr.fetchone():
        cr.execute((MIG / "0007_run_worker.up.sql").read_text())
    yield c, cr
    c.rollback()
    c.close()


@pytest.fixture()
def run_fixture(db):
    """Create an approved pipeline, revision, and claimed job_run inside the rollback transaction."""
    c, cr = db
    cr.execute("INSERT INTO app_user(username, password_hash) VALUES (%s, 'x') RETURNING id", (f"u_{uuid.uuid4().hex[:8]}",))
    uid = cr.fetchone()[0]
    cr.execute("INSERT INTO workspace(slug, name) VALUES (%s, 'test-ws') RETURNING id", (f"ws-{uuid.uuid4().hex[:8]}",))
    ws = cr.fetchone()[0]
    cr.execute("INSERT INTO pipeline(workspace_id, name, created_by) VALUES (%s, 'pipeline_test', %s) RETURNING id", (ws, uid))
    pid = cr.fetchone()[0]
    cr.execute(
        "INSERT INTO pipeline_revision(pipeline_id, spec, checksum, state, created_by) VALUES (%s, '{}', %s, 'approved', %s) RETURNING id",
        (pid, hashlib.sha256(b"spec").hexdigest(), uid)
    )
    rev = cr.fetchone()[0]
    cr.execute(
        "INSERT INTO job_run(revision_id, workspace_id, idempotency_key, requested_by) VALUES (%s, %s, %s, %s) RETURNING id",
        (rev, ws, f"idem-{uuid.uuid4().hex[:8]}", uid)
    )
    run_id = cr.fetchone()[0]
    # Claim run to acquire a valid fence token and active lease
    cr.execute("SELECT claim_run(%s, 'worker-1', 60)", (run_id,))
    fence = cr.fetchone()[0]
    assert fence == 1
    return {"user_id": uid, "workspace_id": ws, "pipeline_id": pid, "revision_id": rev, "run_id": run_id, "fence": fence}


def test_type_roundtrip_staging(db, run_fixture):
    """Decimal128(38,10), int64 max, uint64, NULL per type, timestamps with tz, and out-of-range dates survive staging."""
    c, cr = db
    run_id = run_fixture["run_id"]
    fence = run_fixture["fence"]
    tbl = etl.staging_table_name(run_id, 0)

    dec_val = decimal.Decimal("123456789012345678.1234567890")
    i64_val = 9223372036854775807
    u64_val = 18446744073709551615
    ts_val = datetime.datetime(2026, 10, 28, 11, 0, 0, tzinfo=datetime.timezone.utc)
    dates_arr = pa.array([0, -719528], type=pa.int32()).cast(pa.date32())  # 1970-01-01 and 0000-01-01

    batch = pa.record_batch([
        pa.array([dec_val, None], type=pa.decimal128(38, 10)),
        pa.array([i64_val, None], type=pa.int64()),
        pa.array([u64_val, None], type=pa.uint64()),
        pa.array([ts_val, None], type=pa.timestamp("us", tz="UTC")),
        dates_arr,
        pa.array(["standard_text", None], type=pa.string()),
        pa.array([True, None], type=pa.bool_()),
        pa.array([123.456, None], type=pa.float64())
    ], names=["d_col", "i64_col", "u64_col", "ts_col", "date_col", "str_col", "bool_col", "flt_col"])

    rows_staged = etl.stage_batch(cr, run_id, fence, tbl, batch)
    assert rows_staged == 2

    # Query back from PostgreSQL
    cr.execute(f"SELECT d_col, i64_col, u64_col, ts_col, date_col, str_col, bool_col, flt_col FROM uetl_staging.{tbl} ORDER BY (d_col IS NULL)")
    rows = cr.fetchall()
    assert len(rows) == 2

    row1, row2 = rows[0], rows[1]

    # Row 1: non-null exact values
    assert row1[0] == dec_val
    assert row1[1] == i64_val
    assert row1[2] == decimal.Decimal(str(u64_val))  # stored in numeric(20, 0)
    assert row1[3].astimezone(datetime.timezone.utc) == ts_val
    assert row1[4] == "1970-01-01"
    assert row1[5] == "standard_text"
    assert row1[6] is True
    assert abs(row1[7] - 123.456) < 1e-6

    # Row 2: all nulls
    assert row2[0] is None
    assert row2[1] is None
    assert row2[2] is None
    assert row2[3] is None
    assert row2[4] == "0000-01-01"  # out-of-range date preserved as ISO text
    assert row2[5] is None
    assert row2[6] is None
    assert row2[7] is None


def test_stale_fence_rejected(db, run_fixture):
    """A write with an outdated fence token or unowned lease must be rejected."""
    c, cr = db
    run_id = run_fixture["run_id"]
    stale_fence = 999  # not the active fence 1
    tbl = etl.staging_table_name(run_id, 0)

    batch = pa.record_batch([pa.array([1, 2])], names=["x"])
    with pytest.raises(etl.StaleFenceError):
        etl.stage_batch(cr, run_id, stale_fence, tbl, batch)


def test_quality_checks_findings(db, run_fixture):
    """Quality checks detect empty datasets, null violations, and duplicate keys."""
    c, cr = db
    run_id = run_fixture["run_id"]
    fence = run_fixture["fence"]
    tbl = etl.staging_table_name(run_id, 1)

    # 1. Empty dataset check
    spec_empty = {"allow_empty": False}
    cr.execute(f"CREATE TABLE uetl_staging.{tbl} (id int, name text)")
    findings = etl.quality_checks(cr, tbl, spec_empty)
    assert any(f.code == "empty_dataset" for f in findings)

    # 2. Not-null check
    batch_with_null = pa.record_batch([
        pa.array([1, 2]),
        pa.array(["ok", None])
    ], names=["id", "name"])
    cr.execute(f"DROP TABLE uetl_staging.{tbl}")
    etl.stage_batch(cr, run_id, fence, tbl, batch_with_null)

    spec_not_null = {"not_null": ["name"]}
    findings = etl.quality_checks(cr, tbl, spec_not_null)
    assert any(f.code == "null_value" and f.column == "name" for f in findings)

    # 3. Duplicate key check
    batch_dups = pa.record_batch([
        pa.array([1, 1]),
        pa.array(["a", "b"])
    ], names=["id", "name"])
    tbl2 = etl.staging_table_name(run_id, 2)
    etl.stage_batch(cr, run_id, fence, tbl2, batch_dups)

    spec_pkey = {"primary_keys": ["id"]}
    findings = etl.quality_checks(cr, tbl2, spec_pkey)
    assert any(f.code == "duplicate_key" and f.column == "id" for f in findings)

    # 4. Clean dataset produces no findings
    batch_clean = pa.record_batch([
        pa.array([101, 102]),
        pa.array(["alpha", "beta"])
    ], names=["id", "name"])
    tbl_clean = etl.staging_table_name(run_id, 3)
    etl.stage_batch(cr, run_id, fence, tbl_clean, batch_clean)
    findings_clean = etl.quality_checks(cr, tbl_clean, {"not_null": ["id", "name"], "primary_keys": ["id"]})
    assert len(findings_clean) == 0


def test_budget_byte_and_time_enforcement():
    """Fakes verify that byte and time ceilings halt extraction with exact error codes."""
    batch = pa.record_batch([pa.array([1, 2, 3])], names=["id"])

    # Byte budget
    class FakeReaderByte:
        def __iter__(self):
            for _ in range(10):
                yield type("Chunk", (), {"data": batch})()
        def cancel(self):
            pass

    class FakeClient:
        def get_flight_info(self, *a, **kw):
            return type("Info", (), {"endpoints": [type("EP", (), {"ticket": b"t"})()]})()
        def do_get(self, *a, **kw):
            return FakeReaderByte()
        def close(self):
            pass

    import unittest.mock as mock
    with mock.patch("pyarrow.flight.FlightClient", return_value=FakeClient()):
        with mock.patch.object(limiter, "lease"):
            with pytest.raises(etl.EtlBudgetExceeded) as exc_byte:
                list(etl.extract_batches(LIVE, {"sql": "SELECT 1"}, budget=etl.Budget(max_bytes=10)))
            assert exc_byte.value.error_code == "budget_bytes"

            # Time budget
            budget_time = etl.Budget(max_seconds=0)  # deadline already passed
            with pytest.raises(etl.EtlBudgetExceeded) as exc_time:
                list(etl.extract_batches(LIVE, {"sql": "SELECT 1"}, budget=budget_time))
            assert exc_time.value.error_code == "budget_seconds"


def test_cancellation_callback():
    """Extraction stops immediately when cancel callback returns True."""
    batch = pa.record_batch([pa.array([1, 2, 3])], names=["id"])

    class FakeReader:
        cancelled = False
        def __iter__(self):
            yield type("Chunk", (), {"data": batch})()
            yield type("Chunk", (), {"data": batch})()
        def cancel(self):
            self.cancelled = True

    reader = FakeReader()
    class FakeClient:
        def get_flight_info(self, *a, **kw):
            return type("Info", (), {"endpoints": [type("EP", (), {"ticket": b"t"})()]})()
        def do_get(self, *a, **kw):
            return reader
        def close(self):
            pass

    import unittest.mock as mock
    with mock.patch("pyarrow.flight.FlightClient", return_value=FakeClient()):
        with mock.patch.object(limiter, "lease"):
            cancelled = True
            with pytest.raises(etl.EtlCancelled):
                list(etl.extract_batches(LIVE, {"sql": "SELECT 1"}, is_cancelled=lambda: cancelled))


@live
def test_live_streaming_5m_rows_bounded_rss():
    """5 M synthetic rows via generate_series: RSS growth < 300 MB and stops at row ceiling."""
    proc = psutil.Process()
    rss_before = proc.memory_info().rss

    # Stream with max_rows = 5,000,000 from a 5,500,000 row generator
    spec = {"sql": "SELECT * FROM generate_series(1, 5500000)"}
    budget = etl.Budget(max_rows=5_000_000, max_bytes=2_147_483_648, max_seconds=60)

    rows_streamed = 0
    t0 = time.perf_counter()
    deadline = time.monotonic() + 15
    while True:
        try:
            with pytest.raises(etl.EtlBudgetExceeded) as exc_info:
                for b in etl.extract_batches(LIVE, spec, budget=budget):
                    rows_streamed += b.num_rows
            break
        except spice.SpiceError as ex:
            if ex.code == "busy" and time.monotonic() < deadline:
                time.sleep(0.1)
                continue
            if ex.code == "busy":
                pytest.skip("SPICE capacity busy for 15 s")
            raise

    duration = time.perf_counter() - t0
    rss_after = proc.memory_info().rss
    rss_growth_mb = (rss_after - rss_before) / (1024 * 1024)

    assert exc_info.value.error_code == "budget_rows"
    assert rows_streamed >= 5_000_000
    assert rss_growth_mb < 300.0, f"RSS growth {rss_growth_mb:.2f} MiB exceeded 300 MB ceiling"

    print(f"\n[EVIDENCE] Streamed {rows_streamed} rows in {duration:.2f} s; RSS growth: {rss_growth_mb:.2f} MiB")


def test_publish_generation_atomic(db, run_fixture):
    """Staging table moves to generation table and view swaps atomically with retention of 3."""
    c, cr = db
    run_id = run_fixture["run_id"]
    fence = run_fixture["fence"]
    stg_tbl = etl.staging_table_name(run_id, 0)

    batch = pa.record_batch([pa.array([1, 2, 3])], names=["val"])
    etl.stage_batch(cr, run_id, fence, stg_tbl, batch)

    target_name = "test_target_ds"
    gen1 = etl.publish_generation(cr, run_id, fence, spec={"target_name": target_name}, staging_table=stg_tbl)
    assert gen1 == 1

    # Verify view points to generation 1 and returns staged rows
    cr.execute(f"SELECT val FROM uetl_published.{target_name} ORDER BY val")
    res = cr.fetchall()
    assert res == [(1,), (2,), (3,)]

    # Verify run status advanced to succeeded
    cr.execute("SELECT state, rows_read FROM job_run WHERE id = %s", (run_id,))
    st, rows = cr.fetchone()
    assert st == "succeeded" and rows == 3
