"""Phase 2 routes: test connection, capabilities, catalog snapshots, bounded preview.

Rules: no route accepts SQL text; preview builds its statement from an allowlisted object, catalog-known
columns and typed filter values; SPICE error text never reaches the client (spice.SpiceError.safe only).
"""
import time
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from psycopg2.extras import Json

from . import limiter, spice

CONN_SQL = ("select c.id, c.name, c.base_url, c.tls_verify, c.timeout_s, s.name as secret_ref"
            " from connection c left join secret_ref s on s.id=c.secret_ref_id where c.workspace_id=%s and c.id=%s")
IDENT = r"^[A-Za-z0-9_]+$"


class Filter(BaseModel):
    column: str = Field(pattern=IDENT, max_length=100)
    op: Literal["=", "!=", "<", "<=", ">", ">="]
    value: str | int | float | bool


class PreviewIn(BaseModel):
    object: str = Field(max_length=200)
    columns: list[str] = Field(default_factory=list, max_length=100)
    filters: list[Filter] = Field(default_factory=list, max_length=5)
    limit: int = Field(default=100, ge=1, le=spice.MAX_ROWS)


def build(workspace_access, DB, audit):
    r = APIRouter()
    base = "/api/v2/workspaces/{workspace_id}/connections/{connection_id}"

    def conn(cur, ws, cid):
        cur.execute(CONN_SQL, (ws, cid))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Not found")
        return row

    def fail(e):
        raise HTTPException({"timeout": 504, "busy": 429}.get(e.code, 502), e.safe) from None

    def latest(cur, cid):
        cur.execute("select revision, fetched_at, payload from catalog_snapshot where connection_id=%s"
                    " order by revision desc limit 1", (cid,))
        return cur.fetchone()

    def allowed(cur, cid):
        cur.execute("select object_name from connection_allowed_object where connection_id=%s", (cid,))
        return {x["object_name"] for x in cur.fetchall()}

    @r.post(base + "/test")
    def test_connection(connection_id: uuid.UUID, request: Request, ctx=Depends(workspace_access("connection.manage")), db=DB):
        ws = ctx["workspace_id"]
        with db.cursor() as cur:
            c = conn(cur, ws, connection_id)
        caps, status, err = {"auth": "token" if c["secret_ref"] else "none"}, "ok", None
        try:
            caps["rest"] = spice.health(c)
            caps["datasets"] = len(spice.list_datasets(c))
            db.commit()  # do not hold the session row lock while reading the source
            with limiter.lease("spice"):
                cols, rows, _ = spice.run_bounded(c, "SELECT 1", max_rows=1, max_seconds=min(c["timeout_s"], 10))
            caps["flight"] = bool(rows)
            caps["streaming"] = caps["flight"]
            caps["bind_parameters"] = False  # Flight path has none (docs/v2/09)
            if not (caps["rest"] and caps["flight"]):
                status, err = "failed", spice.SAFE["protocol"]
        except limiter.Busy as e:
            raise HTTPException(429, spice.SAFE["busy"], headers={"Retry-After": str(e.retry_after)}) from None
        except spice.SpiceError as e:
            status, err = "failed", e.safe
        with db.cursor() as cur:
            cur.execute("update connection set status=%s, capabilities=%s, last_test_at=now() where id=%s",
                        (status, Json(caps), connection_id))
        audit(db, request, "connection.test", "allow" if status == "ok" else "error", ws=ws, otype="connection",
              oid=connection_id, detail={"status": status})
        return {"status": status, "capabilities": caps, "error": err}

    @r.get(base + "/capabilities")
    def capabilities(connection_id: uuid.UUID, ctx=Depends(workspace_access("connection.read")), db=DB):
        with db.cursor() as cur:
            conn(cur, ctx["workspace_id"], connection_id)
            cur.execute("select status, capabilities, last_test_at from connection where id=%s", (connection_id,))
            return cur.fetchone()

    @r.post(base + "/catalog/refresh")
    def refresh_catalog(connection_id: uuid.UUID, request: Request, ctx=Depends(workspace_access("connection.manage")), db=DB):
        ws = ctx["workspace_id"]
        with db.cursor() as cur:
            c = conn(cur, ws, connection_id)
        try:
            objects = {d["name"]: {"columns": spice.describe(c, d["name"]), "kind": d["kind"]}
                       for d in spice.list_datasets(c)}
        except spice.SpiceError as e:
            fail(e)
        with db.cursor() as cur:
            # Serialize revisions and policy updates, after (not during) remote metadata reads.
            cur.execute("select id from connection where id=%s for update", (connection_id,))
            previous = latest(cur, connection_id)
            prior_objects = previous["payload"]["objects"] if previous else {}
            for name, obj in objects.items():
                old = prior_objects.get(name, {})
                obj["limit_pushdown"] = old.get("limit_pushdown") if old.get("kind") == obj["kind"] else None
            cur.execute("select coalesce(max(revision),0)+1 as n from catalog_snapshot where connection_id=%s", (connection_id,))
            rev = cur.fetchone()["n"]
            cur.execute("insert into catalog_snapshot(connection_id,revision,payload) values (%s,%s,%s)",
                        (connection_id, rev, Json({"objects": objects})))
            # a pending dataset request is fulfilled once its name shows up in the source catalog
            cur.execute("update dataset_request set status='applied', closed_at=now() where connection_id=%s"
                        " and status='pending' and dataset_name = any(%s) returning id", (connection_id, list(objects)))
            closed = len(cur.fetchall())
        audit(db, request, "catalog.refresh", "allow", ws=ws, otype="connection", oid=connection_id,
              detail={"revision": rev, "objects": len(objects), "requests_applied": closed})
        return {"revision": rev, "objects": len(objects), "requests_applied": closed}

    @r.get(base + "/catalog")
    def catalog(connection_id: uuid.UUID, ctx=Depends(workspace_access("catalog.read")), db=DB):
        """Only objects on the connection's allowlist are visible here."""
        with db.cursor() as cur:
            conn(cur, ctx["workspace_id"], connection_id)
            snap, ok = latest(cur, connection_id), None
            ok = allowed(cur, connection_id)
        if not snap:
            return {"revision": None, "objects": {}}
        objs = {k: v for k, v in snap["payload"]["objects"].items() if k in ok}
        return {"revision": snap["revision"], "fetched_at": snap["fetched_at"], "objects": objs}

    @r.get(base + "/catalog/all")
    def catalog_all(connection_id: uuid.UUID, ctx=Depends(workspace_access("connection.manage")), db=DB):
        """Admin view used to choose the allowlist: names only, with the allowed flag."""
        with db.cursor() as cur:
            conn(cur, ctx["workspace_id"], connection_id)
            snap, ok = latest(cur, connection_id), allowed(cur, connection_id)
        names = sorted(snap["payload"]["objects"]) if snap else []
        return {"revision": snap["revision"] if snap else None, "objects": [{"name": n, "allowed": n in ok} for n in names]}

    @r.post(base + "/preview")
    def preview(connection_id: uuid.UUID, body: PreviewIn, request: Request,
                ctx=Depends(workspace_access("preview.run")), db=DB):
        ws = ctx["workspace_id"]
        with db.cursor() as cur:
            c = conn(cur, ws, connection_id)
            snap, ok = latest(cur, connection_id), allowed(cur, connection_id)
        if body.object not in ok:
            audit(db, request, "preview.run", "deny", ws=ws, otype="connection", oid=connection_id,
                  detail={"reason": "not_allowlisted"})
            db.commit()
            raise HTTPException(403, "Object is not on this connection's allowlist")
        if not snap or body.object not in snap["payload"]["objects"]:
            raise HTTPException(409, "Catalog is missing for this object; refresh the catalog first")
        obj = snap["payload"]["objects"][body.object]
        types = {col["name"]: col["type"] for col in obj["columns"]}
        names = list(body.columns) + [f.column for f in body.filters]
        unknown = [n for n in names if n not in types]
        if unknown:
            raise HTTPException(422, "Unknown column")
        try:
            sql = spice.build_select(body.object, {"select": body.columns, "types": types},
                                     [f.model_dump() for f in body.filters], body.limit if obj.get("limit_pushdown") is not False else None)
        except ValueError:
            raise HTTPException(422, "Filter value does not fit the column type") from None
        db.commit()  # release auth/session locks before remote I/O; lease has its own transaction
        pool = "odbc" if obj.get("kind") == "odbc" else "spice"
        try:
            with limiter.lease(pool):
                with db.cursor() as cur:
                    current = latest(cur, connection_id)
                policy = current["payload"]["objects"].get(body.object, {}).get("limit_pushdown") if current else None
                limit_applied = policy is not False
                sql = spice.build_select(body.object, {"select": body.columns, "types": types},
                                         [f.model_dump() for f in body.filters], body.limit if limit_applied else None)
                deadline = time.monotonic() + min(c["timeout_s"], spice.MAX_SECONDS)
                try:
                    cols, rows, truncated = spice.run_bounded(c, sql, max_rows=body.limit, pool=pool,
                                                             max_seconds=max(0.001, deadline-time.monotonic()))
                except spice.SpiceError as e:
                    if e.code != "rejected" or not limit_applied:
                        raise
                    if time.monotonic() >= deadline:
                        raise spice.SpiceError("timeout") from None
                    sql = spice.build_select(body.object, {"select": body.columns, "types": types},
                                             [f.model_dump() for f in body.filters], None)
                    cols, rows, truncated = spice.run_bounded(c, sql, max_rows=body.limit, pool=pool,
                                                             max_seconds=deadline-time.monotonic())
                    limit_applied = False
                if policy is None or policy != limit_applied:
                    with db.cursor() as cur:
                        cur.execute("select id from connection where id=%s for update", (connection_id,))
                        cur.execute("update catalog_snapshot set payload=jsonb_set(payload,%s,%s)"
                                    " where connection_id=%s and revision=(select max(revision) from catalog_snapshot"
                                    " where connection_id=%s) and payload->'objects' ? %s",
                                    (["objects", body.object, "limit_pushdown"], Json(limit_applied),
                                     connection_id, connection_id, body.object))
                    db.commit()  # learning must be visible before the lease is released
        except limiter.Busy as e:
            audit(db, request, "preview.run", "deny", ws=ws, otype="connection", oid=connection_id,
                  detail={"object": body.object, "reason": "busy"})
            db.commit()
            raise HTTPException(429, spice.SAFE["busy"], headers={"Retry-After": str(e.retry_after)}) from None
        except spice.SpiceError as e:
            audit(db, request, "preview.run", "error", ws=ws, otype="connection", oid=connection_id,
                  detail={"object": body.object, "code": e.code})
            db.commit()  # keep the audit row although the request fails
            fail(e)
        audit(db, request, "preview.run", "allow", ws=ws, otype="connection", oid=connection_id,
              detail={"object": body.object, "rows": len(rows), "truncated": truncated, "filters": len(body.filters)})
        return {"columns": cols, "rows": rows, "truncated": truncated, "limit_applied": limit_applied}

    return r
