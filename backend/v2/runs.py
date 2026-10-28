"""Runs API router for U-ETL v2 (Phase 3 Task 7).

Endpoints for submitting, listing, fetching details, cancelling, retrying runs,
and querying dead-lettered runs.
"""
import json
import logging
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from . import worker

log = logging.getLogger("uetl.runs")


class RunSubmitIn(BaseModel):
    revision_id: uuid.UUID
    idempotency_key: Optional[str] = Field(default=None, max_length=128)


def _format_run(row: dict) -> dict:
    """Format job_run DB row for JSON response."""
    return {
        "id": str(row["id"]),
        "revision_id": str(row["revision_id"]),
        "workspace_id": str(row["workspace_id"]),
        "pipeline_name": row.get("pipeline_name"),
        "idempotency_key": row.get("idempotency_key"),
        "state": row["state"],
        "fence": row.get("fence", 0),
        "attempt": row.get("attempt", 0),
        "max_attempts": row.get("max_attempts", 3),
        "cancel_requested": row.get("cancel_requested", False),
        "rows_read": row.get("rows_read", 0),
        "bytes_staged": row.get("bytes_staged", 0),
        "error_code": row.get("error_code"),
        "started_at": row["started_at"].isoformat() if row.get("started_at") else None,
        "finished_at": row["finished_at"].isoformat() if row.get("finished_at") else None,
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
    }


def build(workspace_access, DB, audit):
    r = APIRouter()
    base = "/api/v2/workspaces/{workspace_id}/runs"

    @r.post(base, status_code=201)
    def submit_run(workspace_id: uuid.UUID, body: RunSubmitIn, request: Request,
                   ctx=Depends(workspace_access("run.submit")), db=DB):
        """Submit a new pipeline run. Only approved revisions can run."""
        ws = ctx["workspace_id"]
        user = ctx["user"]
        idem_key = body.idempotency_key or f"run-{uuid.uuid4().hex}"

        with db.cursor() as cur:
            # 1. Validate revision
            cur.execute(
                """SELECT r.id, r.state, p.workspace_id, p.name as pipeline_name
                   FROM pipeline_revision r
                   JOIN pipeline p ON p.id = r.pipeline_id
                   WHERE r.id = %s""",
                (body.revision_id,)
            )
            rev = cur.fetchone()
            if not rev:
                audit(db, request, "run.submit", "deny", ws=ws, otype="job_run", detail={"reason": "revision_not_found"})
                raise HTTPException(404, "Revision not found")
            if rev["workspace_id"] != ws:
                audit(db, request, "run.submit", "deny", ws=ws, otype="job_run", detail={"reason": "workspace_mismatch"})
                raise HTTPException(400, "Revision belongs to another workspace")
            if rev["state"] != "approved":
                audit(db, request, "run.submit", "deny", ws=ws, otype="job_run", detail={"reason": "revision_not_approved"})
                raise HTTPException(400, "Only an approved revision can run")

            # 2. Idempotency check
            cur.execute(
                """SELECT r.*, p.name as pipeline_name
                   FROM job_run r
                   JOIN pipeline_revision pr ON pr.id = r.revision_id
                   JOIN pipeline p ON p.id = pr.pipeline_id
                   WHERE r.workspace_id = %s AND r.idempotency_key = %s""",
                (ws, idem_key)
            )
            existing = cur.fetchone()
            if existing:
                audit(db, request, "run.submit", "allow", ws=ws, otype="job_run", oid=existing["id"], detail={"idempotent": True})
                return _format_run(existing)

            # 3. Insert job_run
            cur.execute(
                """INSERT INTO job_run (revision_id, workspace_id, idempotency_key, requested_by, state, fence, attempt)
                   VALUES (%s, %s, %s, %s, 'queued', 0, 0)
                   RETURNING *""",
                (body.revision_id, ws, idem_key, user["id"])
            )
            new_run = cur.fetchone()
            run_id = new_run["id"]

            # 4. Insert initial event
            cur.execute(
                """INSERT INTO job_event (run_id, kind, detail)
                   VALUES (%s, 'run.queued', %s)""",
                (run_id, json.dumps({"requested_by": str(user["id"]), "revision_id": str(body.revision_id)}))
            )

        # 5. Enqueue to Dramatiq / Redis (non-blocking for DB transaction)
        enqueued = worker.enqueue_run(str(run_id))
        audit(db, request, "run.submit", "allow", ws=ws, otype="job_run", oid=run_id, detail={"enqueued": enqueued})

        res = _format_run(new_run)
        res["pipeline_name"] = rev["pipeline_name"]
        res["enqueued"] = enqueued
        return res

    @r.get(base)
    def list_runs(workspace_id: uuid.UUID,
                  state: Optional[str] = Query(default=None, pattern=r"^(queued|running|publishing|succeeded|failed|cancelled|dead)$"),
                  limit: int = Query(default=50, ge=1, le=100),
                  offset: int = Query(default=0, ge=0),
                  ctx=Depends(workspace_access("run.read")), db=DB):
        """List runs in workspace with optional status filter."""
        ws = ctx["workspace_id"]
        with db.cursor() as cur:
            query = """SELECT r.*, p.name as pipeline_name
                       FROM job_run r
                       JOIN pipeline_revision pr ON pr.id = r.revision_id
                       JOIN pipeline p ON p.id = pr.pipeline_id
                       WHERE r.workspace_id = %s"""
            params = [ws]
            if state:
                query += " AND r.state = %s"
                params.append(state)
            query += " ORDER BY r.created_at DESC LIMIT %s OFFSET %s"
            params.extend([limit, offset])

            cur.execute(query, params)
            rows = cur.fetchall()
            return [_format_run(row) for row in rows]

    @r.get(f"{base}/{{run_id}}")
    def get_run(workspace_id: uuid.UUID, run_id: uuid.UUID,
                ctx=Depends(workspace_access("run.read")), db=DB):
        """Get run details and event log."""
        ws = ctx["workspace_id"]
        with db.cursor() as cur:
            cur.execute(
                """SELECT r.*, p.name as pipeline_name
                   FROM job_run r
                   JOIN pipeline_revision pr ON pr.id = r.revision_id
                   JOIN pipeline p ON p.id = pr.pipeline_id
                   WHERE r.workspace_id = %s AND r.id = %s""",
                (ws, run_id)
            )
            run_row = cur.fetchone()
            if not run_row:
                raise HTTPException(404, "Run not found")

            cur.execute(
                """SELECT id, at, kind, detail
                   FROM job_event
                   WHERE run_id = %s
                   ORDER BY id ASC""",
                (run_id,)
            )
            events = [
                {
                    "id": ev["id"],
                    "at": ev["at"].isoformat() if ev.get("at") else None,
                    "kind": ev["kind"],
                    "detail": ev["detail"]
                }
                for ev in cur.fetchall()
            ]

            res = _format_run(run_row)
            res["events"] = events
            return res

    @r.post(f"{base}/{{run_id}}/cancel")
    def cancel_run(workspace_id: uuid.UUID, run_id: uuid.UUID, request: Request,
                   ctx=Depends(workspace_access("run.cancel")), db=DB):
        """Request cooperative cancellation for an active run, or cancel a queued run immediately."""
        ws = ctx["workspace_id"]
        with db.cursor() as cur:
            cur.execute("SELECT * FROM job_run WHERE workspace_id = %s AND id = %s FOR UPDATE", (ws, run_id))
            run_row = cur.fetchone()
            if not run_row:
                audit(db, request, "run.cancel", "deny", ws=ws, otype="job_run", oid=run_id, detail={"reason": "not_found"})
                raise HTTPException(404, "Run not found")

            if run_row["state"] in ("succeeded", "cancelled"):
                audit(db, request, "run.cancel", "deny", ws=ws, otype="job_run", oid=run_id, detail={"reason": "already_terminal"})
                raise HTTPException(400, f"Cannot cancel run in terminal state '{run_row['state']}'")

            if run_row["state"] == "queued":
                cur.execute(
                    """UPDATE job_run
                       SET state = 'cancelled', cancel_requested = true, finished_at = clock_timestamp()
                       WHERE id = %s RETURNING *""",
                    (run_id,)
                )
                updated = cur.fetchone()
                cur.execute("INSERT INTO job_event (run_id, kind, detail) VALUES (%s, 'run.cancelled', '{}')", (run_id,))
            else:
                cur.execute(
                    """UPDATE job_run
                       SET cancel_requested = true
                       WHERE id = %s RETURNING *""",
                    (run_id,)
                )
                updated = cur.fetchone()
                cur.execute("INSERT INTO job_event (run_id, kind, detail) VALUES (%s, 'run.cancel_requested', '{}')", (run_id,))

        audit(db, request, "run.cancel", "allow", ws=ws, otype="job_run", oid=run_id)
        return _format_run(updated)

    @r.post(f"{base}/{{run_id}}/retry")
    def retry_run(workspace_id: uuid.UUID, run_id: uuid.UUID, request: Request,
                  ctx=Depends(workspace_access("run.retry")), db=DB):
        """Retry a failed or dead run with a reset attempt budget."""
        ws = ctx["workspace_id"]
        with db.cursor() as cur:
            cur.execute("SELECT * FROM job_run WHERE workspace_id = %s AND id = %s FOR UPDATE", (ws, run_id))
            run_row = cur.fetchone()
            if not run_row:
                audit(db, request, "run.retry", "deny", ws=ws, otype="job_run", oid=run_id, detail={"reason": "not_found"})
                raise HTTPException(404, "Run not found")

            if run_row["state"] not in ("failed", "dead"):
                audit(db, request, "run.retry", "deny", ws=ws, otype="job_run", oid=run_id, detail={"reason": "invalid_state"})
                raise HTTPException(400, f"Cannot retry run in state '{run_row['state']}'; only failed or dead runs can be retried")

            cur.execute(
                """UPDATE job_run
                   SET state = 'queued',
                       next_attempt_at = null,
                       lease_owner = null,
                       lease_expires_at = null
                   WHERE id = %s RETURNING *""",
                (run_id,)
            )
            updated = cur.fetchone()
            cur.execute("INSERT INTO job_event (run_id, kind, detail) VALUES (%s, 'run.retried', '{}')", (run_id,))

        enqueued = worker.enqueue_run(str(run_id))
        audit(db, request, "run.retry", "allow", ws=ws, otype="job_run", oid=run_id, detail={"enqueued": enqueued})

        res = _format_run(updated)
        res["enqueued"] = enqueued
        return res

    @r.get("/api/v2/workspaces/{workspace_id}/dead-letters")
    def list_dead_letters(workspace_id: uuid.UUID,
                          limit: int = Query(default=50, ge=1, le=100),
                          ctx=Depends(workspace_access("run.read")), db=DB):
        """List dead-letter runs for workspace."""
        ws = ctx["workspace_id"]
        with db.cursor() as cur:
            cur.execute(
                """SELECT d.run_id, d.workspace_id, d.reason, d.at,
                          r.attempt, r.max_attempts, r.error_code,
                          p.name as pipeline_name
                   FROM dead_letter d
                   JOIN job_run r ON r.id = d.run_id
                   JOIN pipeline_revision pr ON pr.id = r.revision_id
                   JOIN pipeline p ON p.id = pr.pipeline_id
                   WHERE d.workspace_id = %s
                   ORDER BY d.at DESC LIMIT %s""",
                (ws, limit)
            )
            rows = cur.fetchall()
            return [
                {
                    "run_id": str(r["run_id"]),
                    "workspace_id": str(r["workspace_id"]),
                    "pipeline_name": r["pipeline_name"],
                    "reason": r["reason"],
                    "attempt": r["attempt"],
                    "max_attempts": r["max_attempts"],
                    "error_code": r["error_code"],
                    "at": r["at"].isoformat() if r.get("at") else None,
                }
                for r in rows
            ]

    return r
