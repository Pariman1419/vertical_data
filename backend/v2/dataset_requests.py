"""Requests to add a dataset to the SPICE pod (docs/v2/runbook-dataset-onboarding.md).

U-ETL never edits SPICE. It records the request and renders the spicepod entry that the SPICE
operator pastes in. The entry only references an EXISTING source profile (a YAML anchor whose
credentials live in the SPICE host's .env), so no database credential ever passes through U-ETL.
"""
import re
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

IDENT = r"[A-Za-z_][A-Za-z0-9_]{0,62}"
# profile -> (anchor, remote_object pattern, `from:` renderer). Patterns are whitelists: nothing else reaches the YAML.
PROFILES = {
    "pg": ("*pg", re.compile(rf"^{IDENT}\.{IDENT}$"),
           lambda o: "postgres:" + ".".join('"' + p + '"' for p in o.split("."))),
    "scada": ("*scada", re.compile(rf"^{IDENT}\.{IDENT}\.{IDENT}$"), lambda o: "odbc:" + o),
}
EXAMPLE = {"pg": "schema.table", "scada": "Database.schema.table"}
COLS = "id, profile, dataset_name, remote_object, status, note, created_at, closed_at, requested_by"


class RequestIn(BaseModel):
    profile: Literal["pg", "scada"]
    dataset_name: str = Field(pattern=r"^[a-z][a-z0-9_]{2,60}$")
    remote_object: str = Field(min_length=3, max_length=200)
    note: str | None = Field(default=None, max_length=500)


def snippet(profile, name, remote_object):
    anchor, _, render = PROFILES[profile]
    return f"- from: {render(remote_object)}\n  name: {name}\n  params: {anchor}\n"


def build(workspace_access, DB, audit):
    r = APIRouter()
    base = "/api/v2/workspaces/{workspace_id}/connections/{connection_id}/dataset-requests"

    def conn_exists(cur, ws, cid):
        cur.execute("select 1 from connection where workspace_id=%s and id=%s", (ws, cid))
        if not cur.fetchone():
            raise HTTPException(404, "Not found")

    def shape(row):
        return {**row, "snippet": snippet(row["profile"], row["dataset_name"], row["remote_object"])}

    @r.get(base)
    def list_requests(connection_id: uuid.UUID, ctx=Depends(workspace_access("connection.read")), db=DB):
        with db.cursor() as cur:
            conn_exists(cur, ctx["workspace_id"], connection_id)
            cur.execute(f"select {COLS} from dataset_request where connection_id=%s order by created_at desc limit 100",
                        (connection_id,))
            return [shape(x) for x in cur.fetchall()]

    @r.post(base, status_code=201)
    def create_request(connection_id: uuid.UUID, body: RequestIn, request: Request,
                       ctx=Depends(workspace_access("connection.manage")), db=DB):
        ws = ctx["workspace_id"]
        if not PROFILES[body.profile][1].match(body.remote_object):
            raise HTTPException(422, f"remote_object must look like {EXAMPLE[body.profile]} (letters, digits, underscore)")
        with db.cursor() as cur:
            conn_exists(cur, ws, connection_id)
            cur.execute("select payload->'objects' ? %s as hit from catalog_snapshot where connection_id=%s"
                        " order by revision desc limit 1", (body.dataset_name, connection_id))
            snap = cur.fetchone()
            if snap and snap["hit"]:
                raise HTTPException(409, "A dataset with this name already exists in the catalog")
            cur.execute("select 1 from dataset_request where workspace_id=%s and dataset_name=%s and status='pending'",
                        (ws, body.dataset_name))
            if cur.fetchone():
                raise HTTPException(409, "A pending request with this name already exists")
            cur.execute("insert into dataset_request(workspace_id,connection_id,requested_by,profile,dataset_name,remote_object,note)"
                        f" values (%s,%s,%s,%s,%s,%s,%s) returning {COLS}",
                        (ws, connection_id, ctx["user"]["id"], body.profile, body.dataset_name, body.remote_object, body.note))
            row = cur.fetchone()
        audit(db, request, "dataset_request.create", "allow", ws=ws, otype="dataset_request", oid=row["id"],
              detail={"profile": body.profile, "name": body.dataset_name})
        return shape(row)

    @r.post(base + "/{request_id}/cancel")
    def cancel_request(connection_id: uuid.UUID, request_id: uuid.UUID, request: Request,
                       ctx=Depends(workspace_access("connection.manage")), db=DB):
        ws = ctx["workspace_id"]
        with db.cursor() as cur:
            conn_exists(cur, ws, connection_id)
            cur.execute("update dataset_request set status='cancelled', closed_at=now()"
                        " where id=%s and connection_id=%s and workspace_id=%s and status='pending' returning id",
                        (request_id, connection_id, ws))
            if not cur.fetchone():
                raise HTTPException(404, "No pending request with this id")
        audit(db, request, "dataset_request.cancel", "allow", ws=ws, otype="dataset_request", oid=request_id)
        return {"status": "cancelled"}

    return r
