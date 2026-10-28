"""Worker execution and Dramatiq actor for U-ETL v2 runs (Phase 3 Tasks 5 & 7).

Manages run claiming, lease heartbeating, fenced writes, cooperative cancellation,
retry with exponential backoff, and dead-letter queuing.
"""
import logging
import math
import os
import threading
import time
import uuid
from typing import Any, Optional

import dramatiq
from dramatiq.brokers.redis import RedisBroker
import psycopg2
from psycopg2 import sql

from . import config, etl
from .db import get_db

log = logging.getLogger("uetl.worker")

# Initialize Dramatiq broker
_redis_url = config.get("UETL_REDIS_URL", "redis://127.0.0.1:6379/0")
broker = RedisBroker(url=_redis_url)
dramatiq.set_broker(broker)


def _get_worker_conn():
    """Connect as uetl_app for worker execution."""
    return psycopg2.connect(
        host=config.get("UETL_PG_HOST", "127.0.0.1"),
        port=config.get("UETL_PG_PORT", "5432"),
        dbname=config.get("UETL_PG_DB", "spiec_verti"),
        user="uetl_app",
        password=config.get("UETL_APP_PASSWORD"),
        connect_timeout=8,
        options="-c search_path=uetl_meta"
    )


def enqueue_run(run_id: str) -> bool:
    """Enqueue run to Dramatiq worker. Returns True on success, False if Redis is unreachable."""
    try:
        execute_run.send(str(run_id))
        return True
    except Exception as ex:
        log.warning("Could not enqueue run %s to Redis: %s", run_id, ex)
        return False


class HeartbeatLoop:
    """Background thread that continuously renews the job run lease until stopped."""
    def __init__(self, run_id: Any, fence: int, lease_s: int = 30, interval_s: float = 5.0, db_factory=_get_worker_conn):
        self.run_id = run_id
        self.fence = fence
        self.lease_s = lease_s
        self.interval_s = interval_s
        self.db_factory = db_factory
        self.stopped = threading.Event()
        self.lost_lease = threading.Event()
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True, name=f"hb-{self.run_id}")
        self.thread.start()

    def stop(self):
        self.stopped.set()
        if self.thread:
            self.thread.join(timeout=3)

    def _run(self):
        while not self.stopped.wait(timeout=self.interval_s):
            try:
                with self.db_factory() as conn:
                    with conn.cursor() as cur:
                        cur.execute("SELECT heartbeat_run(%s, %s, %s)", (self.run_id, self.fence, self.lease_s))
                        ok = cur.fetchone()[0]
                        if not ok:
                            log.warning("Heartbeat failed for run %s fence %s: lease lost", self.run_id, self.fence)
                            self.lost_lease.set()
                            return
            except Exception as ex:
                log.warning("Heartbeat exception for run %s: %s", self.run_id, ex)


@dramatiq.actor(max_retries=0, queue_name="default")
def execute_run(run_id_str: str, worker_id: Optional[str] = None, db_factory=_get_worker_conn):
    """Claim and execute an approved pipeline run."""
    run_id = uuid.UUID(run_id_str)
    worker_id = worker_id or f"worker-{os.getpid()}-{uuid.uuid4().hex[:6]}"
    lease_s = 30

    conn = db_factory()
    try:
        # 1. Atomic claim
        with conn.cursor() as cur:
            cur.execute("SELECT claim_run(%s, %s, %s)", (run_id, worker_id, lease_s))
            fence = cur.fetchone()[0]
        conn.commit()

        if fence is None:
            log.info("Run %s could not be claimed by %s (not queued or cancelled)", run_id, worker_id)
            return

        # 2. Start heartbeat thread
        hb = HeartbeatLoop(run_id, fence, lease_s=lease_s, db_factory=db_factory)
        hb.start()

        try:
            _run_pipeline(conn, run_id, fence, hb)
        finally:
            hb.stop()

    except Exception as exc:
        _handle_run_failure(conn, run_id, exc)
    finally:
        conn.close()


def _run_pipeline(conn, run_id: uuid.UUID, fence: int, hb: HeartbeatLoop):
    """Execute the stages of a claimed run."""
    with conn.cursor() as cur:
        # Check cooperative cancellation
        cur.execute("SELECT cancel_requested, workspace_id, revision_id FROM job_run WHERE id = %s", (run_id,))
        row = cur.fetchone()
        if not row:
            return
        cancel_requested, ws_id, rev_id = row[0], row[1], row[2]
        if cancel_requested:
            cur.execute("UPDATE job_run SET state = 'cancelled', finished_at = clock_timestamp() WHERE id = %s AND fence = %s",
                        (run_id, fence))
            cur.execute("INSERT INTO job_event (run_id, kind, detail) VALUES (%s, 'run.cancelled', '{}')", (run_id,))
            conn.commit()
            return

        # Fetch revision spec
        cur.execute("SELECT pipeline_id, spec FROM pipeline_revision WHERE id = %s", (rev_id,))
        rev_row = cur.fetchone()
        pipeline_id, spec = rev_row[0], rev_row[1] or {}

        # Log started event
        cur.execute("INSERT INTO job_event (run_id, kind, detail) VALUES (%s, 'run.started', %s)",
                    (run_id, psycopg2.extras.Json({"fence": fence})))
        conn.commit()

    # Stage data
    stg_table = etl.staging_table_name(run_id, 0)
    total_rows = 0

    # Look up connection if dataset / connection_id provided
    conn_dict = spec.get("connection") or {}
    budget = etl.Budget(
        max_rows=spec.get("max_rows", 5000000),
        max_bytes=spec.get("max_bytes", 2147483648),
        max_seconds=spec.get("max_seconds", 1800)
    )

    with conn.cursor() as cur:
        # If dataset query specified, run extraction
        if "sql" in spec or "dataset" in spec:
            batches = etl.extract_batches(conn_dict, spec, budget=budget)
            for batch in batches:
                if hb.lost_lease.is_set():
                    raise etl.StaleFenceError("Lost lease during execution")
                # Check cancellation at batch boundary
                cur.execute("SELECT cancel_requested FROM job_run WHERE id = %s", (run_id,))
                if cur.fetchone()[0]:
                    cur.execute("UPDATE job_run SET state = 'cancelled', finished_at = clock_timestamp() WHERE id = %s AND fence = %s",
                                (run_id, fence))
                    cur.execute("INSERT INTO job_event (run_id, kind, detail) VALUES (%s, 'run.cancelled', '{}')", (run_id,))
                    conn.commit()
                    return

                etl.stage_batch(cur, run_id, fence, stg_table, batch)
                total_rows += batch.num_rows

        # State transition to 'publishing'
        cur.execute("UPDATE job_run SET state = 'publishing' WHERE id = %s AND fence = %s", (run_id, fence))
        cur.execute("INSERT INTO job_event (run_id, kind, detail) VALUES (%s, 'run.publishing', %s)",
                    (run_id, psycopg2.extras.Json({"staged_rows": total_rows})))
        conn.commit()

        # Publish generation and swap view atomically
        gen = etl.publish_generation(cur, run_id, fence, spec=spec, staging_table=stg_table)
        cur.execute("INSERT INTO job_event (run_id, kind, detail) VALUES (%s, 'run.succeeded', %s)",
                    (run_id, psycopg2.extras.Json({"generation": gen, "rows": total_rows})))
        conn.commit()


def _handle_run_failure(conn, run_id: uuid.UUID, exc: Exception):
    """Handle run failure with exponential backoff retry or dead-letter queueing."""
    log.error("Run %s failed: %s", run_id, exc)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT attempt, max_attempts, workspace_id FROM job_run WHERE id = %s", (run_id,))
            row = cur.fetchone()
            if not row:
                return
            attempt, max_attempts, ws_id = row[0], row[1], row[2]
            err_code = type(exc).__name__.lower()[:63]
            # Ensure error code matches regex ^[a-z][a-z0-9_]{0,63}$
            err_code = "".join(c if c.isalnum() or c == '_' else '_' for c in err_code).strip('_')
            if not err_code or not err_code[0].isalpha():
                err_code = "err_" + err_code

            if attempt < max_attempts:
                # Exponential backoff: 5s, 10s, 20s...
                delay_s = int(5 * math.pow(2, max(0, attempt - 1)))
                cur.execute(
                    """UPDATE job_run
                       SET state = 'queued',
                           next_attempt_at = clock_timestamp() + make_interval(secs => %s),
                           error_code = %s,
                           lease_owner = null,
                           lease_expires_at = null
                       WHERE id = %s""",
                    (delay_s, err_code, run_id)
                )
                cur.execute(
                    """INSERT INTO job_event (run_id, kind, detail)
                       VALUES (%s, 'run.retry_scheduled', %s)""",
                    (run_id, psycopg2.extras.Json({"attempt": attempt, "delay_s": delay_s, "error": str(exc)[:200]}))
                )
            else:
                # Retries exhausted -> mark as dead and record dead letter
                cur.execute(
                    """UPDATE job_run
                       SET state = 'dead',
                           finished_at = clock_timestamp(),
                           error_code = %s,
                           lease_owner = null,
                           lease_expires_at = null
                       WHERE id = %s""",
                    (err_code, run_id)
                )
                cur.execute(
                    """INSERT INTO dead_letter (run_id, workspace_id, reason)
                       VALUES (%s, %s, %s)
                       ON CONFLICT (run_id) DO NOTHING""",
                    (run_id, ws_id, err_code)
                )
                cur.execute(
                    """INSERT INTO job_event (run_id, kind, detail)
                       VALUES (%s, 'run.dead_lettered', %s)""",
                    (run_id, psycopg2.extras.Json({"attempts": attempt, "error": str(exc)[:200]}))
                )
            conn.commit()
    except Exception as db_exc:
        log.error("Failed to record failure for run %s: %s", run_id, db_exc)
        conn.rollback()
