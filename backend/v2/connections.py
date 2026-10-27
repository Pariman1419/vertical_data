"""Phase 2 routes: secret references and source connections (no SPICE wire calls yet).

Imported by app.py. Security rules:
  - a connection URL must pass netpolicy (allowlist + forbidden-address checks);
  - secret VALUES never enter the API or the database (only env-var style names);
  - every route is workspace-scoped through workspace_access(); a connection id from another
    workspace is indistinguishable from a missing one (404);
  - access to individual source objects is an explicit per-connection allowlist (decision D13).
"""
import re
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from . import netpolicy

NAME_RE = r"^[A-Z][A-Z0-9_]{2,60}$"
OBJECT_RE = re.compile(r"^[A-Za-z0-9_]+(\.[A-Za-z0-9_]+){0,2}$")
CONN_COLS = ("c.id, c.name, c.kind, c.base_url, c.tls_verify, c.auth_mode, s.name as secret_ref, c.scope, c.timeout_s,"
             " c.capabilities, c.last_test_at, c.status")


class SecretRefIn(BaseModel):
    name: str = Field(pattern=NAME_RE)  # env-var style name; the value is resolved server-side only


class ConnectionIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    kind: Literal["rest", "flight"] = "rest"
    base_url: str = Field(min_length=8, max_length=300)
    tls_verify: bool = True
    secret_ref: str | None = Field(default=None, pattern=NAME_RE)
    scope: str | None = Field(default=None, max_length=200)
    timeout_s: int = Field(default=10, ge=1, le=120)


class ConnectionPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    base_url: str | None = Field(default=None, min_length=8, max_length=300)
    tls_verify: bool | None = None
    secret_ref: str | None = Field(default=None, pattern=NAME_RE)
    scope: str | None = Field(default=None, max_length=200)
    timeout_s: int | None = Field(default=None, ge=1, le=120)


class AllowedObjectsIn(BaseModel):
    objects: list[str] = Field(max_length=500)


def build(workspace_access, DB, audit):
    """Router factory so this module does not import app.py (avoids a cycle)."""
    r = APIRouter()
    base = "/api/v2/workspaces/{workspace_id}"

    def check_url(url):
        try:
            netpolicy.resolve_pinned(url)
        except netpolicy.PolicyError as e:
            raise HTTPException(400, f"Connection URL rejected: {e}") from None

    def secret_id(cur, ws, name):
        if name is None:
            return None
        cur.execute("select id from secret_ref where workspace_id=%s and name=%s", (ws, name))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Secret reference not found")
        return row["id"]

    def connection(cur, ws, cid):
        cur.execute(f"select {CONN_COLS} from connection c left join secret_ref s on s.id=c.secret_ref_id"
                    " where c.workspace_id=%s and c.id=%s", (ws, cid))
        row = cur.fetchone()
        if not row:
            raise HTTPException(404, "Not found")
        return row

    @r.get(base + "/secret-refs")
    def list_secret_refs(ctx=Depends(workspace_access("connection.manage")), db=DB):
        with db.cursor() as cur:
            cur.execute("select id,name,provider,rotated_at,created_at from secret_ref where workspace_id=%s order by name",
                        (ctx["workspace_id"],))
            return cur.fetchall()

    @r.post(base + "/secret-refs", status_code=201)
    def create_secret_ref(body: SecretRefIn, request: Request, ctx=Depends(workspace_access("connection.manage")), db=DB):
        ws = ctx["workspace_id"]
        with db.cursor() as cur:
            cur.execute("select 1 from secret_ref where workspace_id=%s and name=%s", (ws, body.name))
            if cur.fetchone():
                raise HTTPException(409, "Secret reference already exists")
            cur.execute("insert into secret_ref(workspace_id,name,provider) values (%s,%s,'env') returning id,name,provider",
                        (ws, body.name))
            row = cur.fetchone()
        audit(db, request, "secret_ref.create", "allow", ws=ws, otype="secret_ref", oid=row["id"], detail={"name": body.name})
        return row

    @r.get(base + "/connections")
    def list_connections(ctx=Depends(workspace_access("connection.read")), db=DB):
        with db.cursor() as cur:
            cur.execute(f"select {CONN_COLS} from connection c left join secret_ref s on s.id=c.secret_ref_id"
                        " where c.workspace_id=%s order by c.name", (ctx["workspace_id"],))
            return cur.fetchall()

    @r.post(base + "/connections", status_code=201)
    def create_connection(body: ConnectionIn, request: Request, ctx=Depends(workspace_access("connection.manage")), db=DB):
        ws = ctx["workspace_id"]
        check_url(body.base_url)
        with db.cursor() as cur:
            cur.execute("select 1 from connection where workspace_id=%s and name=%s", (ws, body.name))
            if cur.fetchone():
                raise HTTPException(409, "Connection name already exists")
            sid = secret_id(cur, ws, body.secret_ref)
            cur.execute("insert into connection(workspace_id,name,kind,base_url,tls_verify,auth_mode,secret_ref_id,scope,timeout_s)"
                        " values (%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id",
                        (ws, body.name, body.kind, body.base_url.rstrip("/"), body.tls_verify,
                         "secret_ref" if sid else "none", sid, body.scope, body.timeout_s))
            cid = cur.fetchone()["id"]
            row = connection(cur, ws, cid)
        audit(db, request, "connection.create", "allow", ws=ws, otype="connection", oid=cid,
              detail={"name": body.name, "kind": body.kind})
        return row

    @r.patch(base + "/connections/{connection_id}")
    def update_connection(connection_id: uuid.UUID, body: ConnectionPatch, request: Request,
                          ctx=Depends(workspace_access("connection.manage")), db=DB):
        ws = ctx["workspace_id"]
        changes = body.model_dump(exclude_unset=True)
        if changes.get("base_url"):
            check_url(changes["base_url"])
            changes["base_url"] = changes["base_url"].rstrip("/")
        with db.cursor() as cur:
            connection(cur, ws, connection_id)
            if "secret_ref" in changes:
                sid = secret_id(cur, ws, changes.pop("secret_ref"))
                changes["secret_ref_id"], changes["auth_mode"] = sid, ("secret_ref" if sid else "none")
            if "base_url" in changes:  # a new endpoint invalidates what we learned about the old one
                changes.update(status="untested", capabilities=None, last_test_at=None)
            if changes:
                cur.execute("update connection set " + ",".join(f"{k}=%s" for k in changes) + " where id=%s",
                            list(changes.values()) + [connection_id])
            row = connection(cur, ws, connection_id)
        audit(db, request, "connection.update", "allow", ws=ws, otype="connection", oid=connection_id,
              detail={"fields": sorted(body.model_dump(exclude_unset=True))})
        return row

    @r.delete(base + "/connections/{connection_id}")
    def delete_connection(connection_id: uuid.UUID, request: Request, ctx=Depends(workspace_access("connection.manage")), db=DB):
        ws = ctx["workspace_id"]
        with db.cursor() as cur:
            connection(cur, ws, connection_id)
            cur.execute("delete from connection where id=%s and workspace_id=%s", (connection_id, ws))
        audit(db, request, "connection.delete", "allow", ws=ws, otype="connection", oid=connection_id)
        return {"status": "deleted"}

    @r.get(base + "/connections/{connection_id}/allowed-objects")
    def get_allowed_objects(connection_id: uuid.UUID, ctx=Depends(workspace_access("connection.read")), db=DB):
        with db.cursor() as cur:
            connection(cur, ctx["workspace_id"], connection_id)
            cur.execute("select object_name from connection_allowed_object where connection_id=%s order by object_name",
                        (connection_id,))
            return [x["object_name"] for x in cur.fetchall()]

    @r.put(base + "/connections/{connection_id}/allowed-objects")
    def set_allowed_objects(connection_id: uuid.UUID, body: AllowedObjectsIn, request: Request,
                            ctx=Depends(workspace_access("connection.manage")), db=DB):
        ws = ctx["workspace_id"]
        names = sorted({o.strip() for o in body.objects})
        if any(not OBJECT_RE.match(n) or len(n) > 200 for n in names):
            raise HTTPException(422, "Invalid object name")
        with db.cursor() as cur:
            connection(cur, ws, connection_id)
            cur.execute("delete from connection_allowed_object where connection_id=%s", (connection_id,))
            for n in names:
                cur.execute("insert into connection_allowed_object(connection_id,object_name,added_by) values (%s,%s,%s)",
                            (connection_id, n, ctx["user"]["id"]))
        audit(db, request, "connection.allowlist.set", "allow", ws=ws, otype="connection", oid=connection_id,
              detail={"count": len(names)})
        return names

    return r
