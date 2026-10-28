"""Reaper process for cleaning up expired leases, retrying queued runs, and pruning retention events."""
import logging
from typing import Any

from . import worker

log = logging.getLogger("uetl.reaper")


def prune_source_events(db):
    """Call database function to prune old source activity events."""
    with db.cursor() as cur:
        cur.execute("SELECT prune_source_events() AS removed")
        row = cur.fetchone()
        return row["removed"] if isinstance(row, dict) else row[0]


def reap_stuck_runs(db) -> int:
    """Find queued runs eligible for execution and re-enqueue them to Redis."""
    with db.cursor() as cur:
        cur.execute(
            """SELECT id FROM job_run
               WHERE state = 'queued'
                 AND cancel_requested = false
                 AND (next_attempt_at IS NULL OR next_attempt_at <= clock_timestamp())
               ORDER BY created_at ASC LIMIT 100"""
        )
        rows = cur.fetchall()
        reaped = 0
        for r in rows:
            run_id = r["id"] if isinstance(r, dict) else r[0]
            if worker.enqueue_run(str(run_id)):
                reaped += 1
        return reaped


def expire_dead_leases(db) -> int:
    """Detect runs whose worker lease expired without a heartbeat, resetting or dead-lettering them."""
    with db.cursor() as cur:
        cur.execute(
            """SELECT id, workspace_id, attempt, max_attempts FROM job_run
               WHERE state IN ('running', 'publishing')
                 AND lease_expires_at IS NOT NULL
                 AND lease_expires_at <= clock_timestamp()
               FOR UPDATE SKIP LOCKED"""
        )
        expired_runs = cur.fetchall()
        count = 0
        for row in expired_runs:
            run_id = row["id"] if isinstance(row, dict) else row[0]
            ws_id = row["workspace_id"] if isinstance(row, dict) else row[1]
            attempt = row["attempt"] if isinstance(row, dict) else row[2]
            max_attempts = row["max_attempts"] if isinstance(row, dict) else row[3]

            if attempt < max_attempts:
                # Reset to queued for another worker to pick up
                cur.execute(
                    """UPDATE job_run
                       SET state = 'queued',
                           lease_owner = null,
                           lease_expires_at = null,
                           next_attempt_at = clock_timestamp()
                       WHERE id = %s""",
                    (run_id,)
                )
                cur.execute(
                    """INSERT INTO job_event (run_id, kind, detail)
                       VALUES (%s, 'run.lease_expired', '{"action": "requeued"}')""",
                    (run_id,)
                )
                worker.enqueue_run(str(run_id))
            else:
                # Exhausted attempts
                cur.execute(
                    """UPDATE job_run
                       SET state = 'dead',
                           finished_at = clock_timestamp(),
                           error_code = 'lease_expired',
                           lease_owner = null,
                           lease_expires_at = null
                       WHERE id = %s""",
                    (run_id,)
                )
                cur.execute(
                    """INSERT INTO dead_letter (run_id, workspace_id, reason)
                       VALUES (%s, %s, 'lease_expired')
                       ON CONFLICT (run_id) DO NOTHING""",
                    (run_id, ws_id)
                )
                cur.execute(
                    """INSERT INTO job_event (run_id, kind, detail)
                       VALUES (%s, 'run.dead_lettered', '{"reason": "lease_expired"}')""",
                    (run_id,)
                )
            count += 1
        return count
