"""ETL core stages: extract_batches, stage_batch, quality_checks, publish_generation.

Pure pipeline functions with no queue/worker dependency; unit-testable in isolation.
All worker writes verify the PG fence token in-transaction before modifying data.
"""
import decimal
import io
import logging
import re
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator, List, Optional, Union

import psycopg2
from psycopg2 import sql
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pacsv
import pyarrow.flight as fl

from . import config, limiter, spice

log = logging.getLogger("uetl.etl")

TARGET_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{2,60}$")
SAFE_IDENT_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
GEN_SERIES_RE = re.compile(r"^SELECT \* FROM generate_series\([1-9][0-9]*,\s*[1-9][0-9]*(?:,\s*[1-9][0-9]*)?\)$")


class EtlError(Exception):
    """Base exception for ETL processing failures."""
    pass


class EtlCancelled(EtlError):
    """Raised when an ETL run is cancelled by operator or callback."""
    pass


class EtlBudgetExceeded(EtlError):
    """Raised when a resource ceiling (rows, bytes, or seconds) is reached."""
    def __init__(self, error_code: str, message: str = ""):
        self.error_code = error_code
        super().__init__(message or f"ETL budget exceeded: {error_code}")


class StaleFenceError(EtlError):
    """Raised when a worker's lease token is stale or expired."""
    pass


@dataclass
class Budget:
    max_rows: int = 5_000_000
    max_bytes: int = 2_147_483_648  # 2 GB
    max_seconds: int = 1800  # 30 minutes


@dataclass
class Finding:
    code: str
    column: Optional[str] = None
    message: str = ""

    def to_dict(self) -> dict:
        return {"code": self.code, "column": self.column, "message": self.message}


def staging_table_name(run_id: Union[str, Any], n: int = 0) -> str:
    """Generate a valid, collision-safe staging table name for a run."""
    clean = str(run_id).replace("-", "").lower()
    return f"r_{clean[:26]}_{n}"


def is_out_of_range_date(array: pa.Array) -> bool:
    """Check if a date array contains values outside PostgreSQL date range (year 1..9999)."""
    if len(array) == 0:
        return False
    if pa.types.is_date32(array.type):
        int_arr = array.cast(pa.int32())
        min_v = pc.min(int_arr).as_py()
        max_v = pc.max(int_arr).as_py()
        # Day -719162 corresponds to 0001-01-01 AD, 2932896 corresponds to 9999-12-31
        return min_v is not None and (min_v < -719162 or max_v > 2932896)
    if pa.types.is_date64(array.type):
        int_arr = array.cast(pa.int64())
        min_v = pc.min(int_arr).as_py()
        max_v = pc.max(int_arr).as_py()
        # In milliseconds:
        # -719162 * 86,400,000 = -62135596800000
        # 2932896 * 86,400,000 = 253402214400000
        return min_v is not None and (min_v < -62135596800000 or max_v > 253402214400000)
    return False


def arrow_type_to_pg(field: pa.Field, array: Optional[pa.Array] = None) -> str:
    """Map an Apache Arrow field type to the exact PostgreSQL column type."""
    t = field.type
    if pa.types.is_boolean(t):
        return "boolean"
    if pa.types.is_int8(t) or pa.types.is_int16(t):
        return "smallint"
    if pa.types.is_int32(t):
        return "integer"
    if pa.types.is_int64(t):
        return "bigint"
    if pa.types.is_uint8(t):
        return "smallint"
    if pa.types.is_uint16(t):
        return "integer"
    if pa.types.is_uint32(t):
        return "bigint"
    if pa.types.is_uint64(t):
        # Unsigned 64-bit integer can exceed int64 max (9223372036854775807); numeric(20, 0) is lossless.
        return "numeric(20, 0)"
    if pa.types.is_float16(t) or pa.types.is_float32(t):
        return "real"
    if pa.types.is_float64(t):
        return "double precision"
    if pa.types.is_decimal128(t) or pa.types.is_decimal256(t):
        return f"numeric({t.precision}, {t.scale})"
    if pa.types.is_timestamp(t):
        return "timestamptz" if t.tz else "timestamp without time zone"
    if pa.types.is_date(t):
        if array is not None and is_out_of_range_date(array):
            return "text"
        return "date"
    if pa.types.is_binary(t) or pa.types.is_large_binary(t):
        return "bytea"
    # Strings and complex/nested types fall back to text
    return "text"


def ensure_staging_table(cur, run_id: Any, fence: int, table: str, schema: pa.Schema,
                         batch: Optional[pa.RecordBatch] = None) -> None:
    """Create the staging table in uetl_staging if it does not already exist."""
    # Fence check
    cur.execute("SELECT run_fence_check(%s, %s)", (run_id, fence))

    schema_name = "uetl_staging"
    table_name = table
    if "." in table:
        schema_name, table_name = table.split(".", 1)

    # Check if table already exists
    cur.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_schema = %s AND table_name = %s",
        (schema_name, table_name)
    )
    if cur.fetchone():
        return

    # Check if security-definer helper worker_create_staging_table exists (Migration 0008)
    cur.execute("SELECT to_regproc('uetl_meta.worker_create_staging_table') IS NOT NULL")
    has_helper = cur.fetchone()[0]

    if has_helper:
        col_parts = []
        for field in schema:
            arr = batch[field.name] if batch is not None else None
            pg_type = arrow_type_to_pg(field, arr)
            col_parts.append(f'"{field.name}" {pg_type}')
        col_defs_str = ", ".join(col_parts)
        cur.execute("SELECT uetl_meta.worker_create_staging_table(%s, %s, %s, %s)",
                    (run_id, fence, table_name, col_defs_str))
    else:
        col_defs = []
        for field in schema:
            arr = batch[field.name] if batch is not None else None
            pg_type = arrow_type_to_pg(field, arr)
            col_defs.append(sql.SQL("{} {}").format(sql.Identifier(field.name), sql.SQL(pg_type)))

        qualified = sql.Identifier(schema_name, table_name)
        cur.execute(sql.SQL("CREATE TABLE IF NOT EXISTS {} ({})").format(qualified, sql.SQL(", ").join(col_defs)))
        cur.execute(sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON {} TO uetl_app").format(qualified))


def extract_batches(conn: dict, spec: dict, *, budget: Optional[Union[Budget, dict]] = None,
                    is_cancelled: Optional[Callable[[], bool]] = None,
                    allow_synthetic: bool = False,
                    heartbeat_s: float = 10.0) -> Iterator[pa.RecordBatch]:
    """Stream batches from SPICE over Flight, bounded by row, byte, and time budgets."""
    if budget is None:
        b = Budget()
    elif isinstance(budget, dict):
        b = Budget(**budget)
    else:
        b = budget

    if is_cancelled and is_cancelled():
        raise EtlCancelled("ETL run was cancelled before extract started")

    # Validate dataset and fail-closed server connection allowlist
    dataset = spec.get("dataset")
    sql_text = spec.get("sql")

    is_synth = bool(sql_text and GEN_SERIES_RE.fullmatch(sql_text))
    if is_synth:
        if not allow_synthetic:
            raise EtlError("Synthetic generator queries are forbidden in production")
    else:
        # Server-side connection allowlist (fail-closed)
        allowed_objects = conn.get("allowed_objects") or conn.get("allowed_datasets")
        if not allowed_objects:
            raise EtlError("Connection has no allowed datasets on record (fail-closed)")
        if not dataset or dataset not in allowed_objects:
            raise EtlError(f"Dataset '{dataset}' is not on the server connection allowlist")

    # Build or extract query
    if sql_text:
        # Never pass raw SQL straight to Flight; route through assert_select_shape (or synthetic generator)
        if not is_synth:
            if not dataset:
                raise ValueError("spec['sql'] requires 'dataset' to validate SELECT shape")
            allowed_cols = set(spec.get("allowed_columns") or (spec.get("columns", {}).get("types", {}) if isinstance(spec.get("columns"), dict) else []))
            spice.assert_select_shape(sql_text, dataset, allowed_cols)
    else:
        if not dataset:
            raise ValueError("spec must provide 'dataset'")
        columns = spec.get("columns")
        filters = spec.get("filters", [])
        limit = spec.get("limit")

        if isinstance(columns, dict) and "select" in columns:
            cols_spec = columns
        elif isinstance(columns, list):
            # Validate every column identifier strictly
            for c in columns:
                c_name = c["name"] if isinstance(c, dict) else c
                if not spice.IDENT_RE.match(str(c_name)):
                    raise ValueError(f"Invalid column identifier: {c_name}")
            types_dict = spec.get("column_types") or {
                (c["name"] if isinstance(c, dict) else c): (c.get("type", "Utf8") if isinstance(c, dict) else "Utf8")
                for c in columns
            }
            cols_spec = {"select": [(c["name"] if isinstance(c, dict) else c) for c in columns], "types": types_dict}
        else:
            types_dict = spec.get("column_types", {})
            cols_spec = {"select": [], "types": types_dict}

        # spice.build_select checks identifiers, escapes filter values, and calls assert_select_shape
        sql_text = spice.build_select(dataset, cols_spec, filters, limit)

    # Lease acquisition via limiter with periodic heartbeat renewal (maintains lease up to 30 min)
    lease_lost = threading.Event()
    active_reader = None

    def on_lease_lost():
        lease_lost.set()
        log.error("Source capacity lease renewal failed (lease expired or lost)")
        if active_reader is not None:
            try:
                active_reader.cancel()
            except Exception:
                pass

    try:
        with limiter.lease("spice", ttl_s=30, heartbeat_s=heartbeat_s, on_renew_failed=on_lease_lost):
            ip, port = spice.flight_endpoint(conn)
            deadline = time.monotonic() + b.max_seconds
            headers = [(b"authorization", ("Bearer " + t).encode())] if (t := spice._token(conn)) else []
            timeout = min(float(b.max_seconds), float(conn.get("timeout_s", 30)))
            opts = fl.FlightCallOptions(timeout=timeout, headers=headers)

            client = fl.FlightClient(f"grpc://{ip}:{port}")
            total_rows = 0
            total_bytes = 0
            try:
                info = client.get_flight_info(fl.FlightDescriptor.for_command(sql_text.encode()), opts)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise EtlBudgetExceeded("budget_seconds")

                reader = client.do_get(info.endpoints[0].ticket, fl.FlightCallOptions(timeout=remaining, headers=headers))
                active_reader = reader
                for chunk in reader:
                    if lease_lost.is_set():
                        reader.cancel()
                        raise EtlError("Source capacity lease renewal failed: lease was lost or expired")
                    if is_cancelled and is_cancelled():
                        reader.cancel()
                        raise EtlCancelled("ETL run cancelled during extract")
                    if time.monotonic() >= deadline:
                        reader.cancel()
                        raise EtlBudgetExceeded("budget_seconds")

                    batch = chunk.data
                    b_rows = batch.num_rows
                    b_bytes = batch.nbytes

                    if total_rows + b_rows > b.max_rows:
                        allowed = b.max_rows - total_rows
                        if allowed > 0:
                            yield batch.slice(0, allowed)
                            total_rows += allowed
                        reader.cancel()
                        raise EtlBudgetExceeded("budget_rows")
                    if total_bytes + b_bytes > b.max_bytes:
                        reader.cancel()
                        raise EtlBudgetExceeded("budget_bytes")

                    total_rows += b_rows
                    total_bytes += b_bytes
                    yield batch
            except EtlError:
                raise
            except Exception as e:
                if lease_lost.is_set():
                    raise EtlError("Source capacity lease renewal failed: lease was lost or expired") from e
                if isinstance(e, (fl.FlightTimedOutError, socket.timeout, TimeoutError)):
                    raise spice.SpiceError("timeout") from None
                if isinstance(e, fl.FlightUnavailableError):
                    raise spice.SpiceError("unreachable", e) from None
                if isinstance(e, (fl.FlightError, pa.ArrowException, OSError)):
                    raise spice.SpiceError("rejected", e) from None
                raise
            finally:
                client.close()
    except limiter.Busy:
        raise spice.SpiceError("busy") from None


def stage_batch(cur, run_id: Any, fence: int, table: str, batch: pa.RecordBatch) -> int:
    """Stage a single Arrow RecordBatch into the run-scoped staging table via COPY."""
    # 1. Fence check in the current transaction
    try:
        cur.execute("SELECT run_fence_check(%s, %s)", (run_id, fence))
    except psycopg2.Error as ex:
        if ex.pgcode == "42501":
            raise StaleFenceError("Stale run fence token") from ex
        raise

    schema_name = "uetl_staging"
    table_name = table
    if "." in table:
        schema_name, table_name = table.split(".", 1)

    # 2. Ensure staging table exists with matching schema
    ensure_staging_table(cur, run_id, fence, f"{schema_name}.{table_name}", batch.schema, batch=batch)

    # 3. Stream data via COPY CSV
    buf = io.BytesIO()
    pacsv.write_csv(batch, buf, write_options=pacsv.WriteOptions(include_header=True))
    buf.seek(0)

    qualified = sql.Identifier(schema_name, table_name)
    col_idents = sql.SQL(", ").join(sql.Identifier(name) for name in batch.schema.names)
    copy_sql = sql.SQL("COPY {} ({}) FROM STDIN WITH (FORMAT csv, HEADER true, NULL '')").format(
        qualified, col_idents
    ).as_string(cur)

    cur.copy_expert(copy_sql, buf)
    return batch.num_rows


def quality_checks(cur, table: str, spec: dict) -> List[Finding]:
    """Execute quality checks against the staged data according to the revision specification."""
    schema_name = "uetl_staging"
    table_name = table
    if "." in table:
        schema_name, table_name = table.split(".", 1)

    qualified = sql.Identifier(schema_name, table_name)
    findings: List[Finding] = []

    # 1. Row count check (dataset must not be empty unless explicitly permitted)
    cur.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(qualified))
    row_count = cur.fetchone()[0]
    if row_count == 0 and not spec.get("allow_empty", False):
        findings.append(Finding(code="empty_dataset", message="Dataset is empty"))

    # 2. Not-null checks
    not_null_cols = list(spec.get("not_null", []))
    for col in spec.get("columns", []):
        if isinstance(col, dict) and col.get("nullable") is False and col.get("name"):
            if col["name"] not in not_null_cols:
                not_null_cols.append(col["name"])

    for col in not_null_cols:
        cur.execute(sql.SQL("SELECT COUNT(*) FROM {} WHERE {} IS NULL").format(
            qualified, sql.Identifier(col)
        ))
        null_count = cur.fetchone()[0]
        if null_count > 0:
            findings.append(Finding(
                code="null_value",
                column=col,
                message=f"Column '{col}' contains {null_count} null value(s)"
            ))

    # 3. Duplicate key / uniqueness check
    pkeys = spec.get("primary_keys") or spec.get("unique_keys") or []
    if pkeys:
        key_cols = sql.SQL(", ").join(sql.Identifier(k) for k in pkeys)
        cur.execute(sql.SQL("SELECT {}, COUNT(*) FROM {} GROUP BY {} HAVING COUNT(*) > 1 LIMIT 1").format(
            key_cols, qualified, key_cols
        ))
        dup = cur.fetchone()
        if dup:
            findings.append(Finding(
                code="duplicate_key",
                column=",".join(pkeys),
                message=f"Duplicate primary key found: {dup[0]}"
            ))

    return findings


def publish_generation(cur, run_id: Any, fence: int, *, spec: Optional[dict] = None,
                       staging_table: Optional[str] = None) -> int:
    """Atomically publish a staging table as a new generation and swap the view pointer.

    Retains the 3 newest generations and cleans up older tables in the same transaction.
    Returns the newly published generation number.
    """
    # Fence check
    try:
        cur.execute("SELECT run_fence_check(%s, %s)", (run_id, fence))
    except psycopg2.Error as ex:
        if ex.pgcode == "42501":
            raise StaleFenceError("Stale run fence token") from ex
        raise

    # Fetch run details
    cur.execute("SELECT workspace_id, revision_id FROM job_run WHERE id = %s", (run_id,))
    run_row = cur.fetchone()
    if not run_row:
        raise ValueError(f"Run {run_id} not found")
    workspace_id, revision_id = run_row[0], run_row[1]

    # Fetch revision details
    cur.execute("SELECT pipeline_id, spec FROM pipeline_revision WHERE id = %s", (revision_id,))
    rev_row = cur.fetchone()
    if not rev_row:
        raise ValueError(f"Revision {revision_id} not found")
    pipeline_id, rev_spec = rev_row[0], rev_row[1]

    effective_spec = spec or rev_spec or {}
    target_name = effective_spec.get("target_name") or effective_spec.get("target_table")
    if not target_name:
        cur.execute("SELECT name FROM pipeline WHERE id = %s", (pipeline_id,))
        prow = cur.fetchone()
        target_name = prow[0] if prow else "dataset"

    target_name = target_name.lower().strip()
    if not TARGET_NAME_RE.match(target_name):
        raise ValueError(f"Invalid target name '{target_name}': must match ^[a-z][a-z0-9_]{{2,60}}$")

    # Find or insert dataset entry
    cur.execute(
        "SELECT id, current_generation FROM dataset WHERE workspace_id = %s AND target_table = %s FOR UPDATE",
        (workspace_id, target_name)
    )
    ds_row = cur.fetchone()
    if ds_row:
        dataset_id, cur_gen = ds_row[0], ds_row[1]
    else:
        cur.execute(
            """INSERT INTO dataset (workspace_id, target_schema, target_table, current_generation)
               VALUES (%s, 'uetl_published', %s, 0) RETURNING id, current_generation""",
            (workspace_id, target_name)
        )
        ds_row = cur.fetchone()
        dataset_id, cur_gen = ds_row[0], ds_row[1]

    next_gen = cur_gen + 1
    gen_table = f"{target_name}_g{next_gen}"

    # Staging table identification
    stg_schema = "uetl_staging"
    stg_name = staging_table or staging_table_name(run_id)
    if "." in stg_name:
        stg_schema, stg_name = stg_name.split(".", 1)

    view_ident = sql.Identifier("uetl_published", target_name)
    gen_ident = sql.Identifier("uetl_published", gen_table)

    # Move table to uetl_published and swap view atomically
    cur.execute("SELECT to_regproc('uetl_meta.worker_publish_generation') IS NOT NULL")
    has_publish_helper = cur.fetchone()[0]

    if has_publish_helper:
        cur.execute("SELECT uetl_meta.worker_publish_generation(%s, %s, %s, %s, %s)",
                    (run_id, fence, target_name, stg_name, gen_table))
    else:
        # Move table to uetl_published and rename to target generation
        cur.execute(sql.SQL("ALTER TABLE {} SET SCHEMA uetl_published").format(
            sql.Identifier(stg_schema, stg_name)
        ))
        cur.execute(sql.SQL("ALTER TABLE {} RENAME TO {}").format(
            sql.Identifier("uetl_published", stg_name),
            sql.Identifier(gen_table)
        ))

        # Atomic view swap: DROP VIEW IF EXISTS followed by CREATE VIEW in the same transaction
        # (PostgreSQL forbids CREATE OR REPLACE VIEW if columns are reordered, renamed, or retyped).
        cur.execute(sql.SQL("DROP VIEW IF EXISTS {}").format(view_ident))
        cur.execute(sql.SQL("CREATE VIEW {} AS SELECT * FROM {}").format(
            view_ident, gen_ident
        ))

        # Grant select to uetl_app
        cur.execute(sql.SQL("GRANT SELECT ON {} TO uetl_app").format(gen_ident))
        cur.execute(sql.SQL("GRANT SELECT ON {} TO uetl_app").format(view_ident))

    # Record row count
    cur.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(gen_ident))
    row_count = cur.fetchone()[0]

    # Record dataset generation
    cur.execute(
        """INSERT INTO dataset_generation (dataset_id, generation, revision_id, run_id, row_count, table_name)
           VALUES (%s, %s, %s, %s, %s, %s)""",
        (dataset_id, next_gen, revision_id, run_id, row_count, gen_table)
    )

    # Advance current generation
    cur.execute(
        "UPDATE dataset SET current_generation = %s WHERE id = %s",
        (next_gen, dataset_id)
    )

    # Retention: keep current + 2 previous generations (total 3), prune older
    cur.execute("SELECT to_regproc('uetl_meta.worker_drop_published_table') IS NOT NULL")
    has_drop_helper = cur.fetchone()[0]

    cur.execute(
        """SELECT generation, table_name FROM dataset_generation
           WHERE dataset_id = %s AND dropped_at IS NULL
           ORDER BY generation DESC OFFSET 3""",
        (dataset_id,)
    )
    old_gens = cur.fetchall()
    for old_gen, old_tbl in old_gens:
        if old_tbl and SAFE_IDENT_RE.match(old_tbl):
            if has_drop_helper:
                cur.execute("SELECT uetl_meta.worker_drop_published_table(%s, %s, %s)", (run_id, fence, old_tbl))
            else:
                cur.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(
                    sql.Identifier("uetl_published", old_tbl)
                ))
        cur.execute(
            "UPDATE dataset_generation SET dropped_at = clock_timestamp() WHERE dataset_id = %s AND generation = %s",
            (dataset_id, old_gen)
        )

    # Update run state to succeeded
    cur.execute(
        "UPDATE job_run SET state = 'succeeded', rows_read = %s WHERE id = %s AND fence = %s",
        (row_count, run_id, fence)
    )

    return next_gen
