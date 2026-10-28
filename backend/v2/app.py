"""U-ETL v2 control-plane API (Phase 1): auth, workspaces, members, audit, health.

Every non-public route resolves (a) an authenticated session, (b) CSRF + same-origin for
unsafe methods, (c) workspace membership, (d) a permission. Errors never echo input.
"""
import ipaddress
import json
import logging
import re
import socket
import time
import uuid
from typing import Literal
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import config, connections, dataset_requests, rbac, security, sources
from .db import get_db, ping

log = logging.getLogger("uetl")
if not log.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(_h)
    log.setLevel(logging.INFO)

# function scope: the transaction commits (or rolls back) BEFORE the response is sent, so a client that
# receives 200 can rely on the data being durable and visible to its next request.
DB = Depends(get_db, scope="function")

app = FastAPI(title="U-ETL v2", docs_url=None, redoc_url=None, openapi_url="/api/v2/openapi.json")

UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
CODES = {400: "bad_request", 401: "unauthenticated", 403: "forbidden", 404: "not_found", 409: "conflict",
         422: "validation_error", 429: "too_many_attempts", 503: "unavailable"}
CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "connect-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'")  # unsafe-inline: legacy shell (audit R06)


# ---------- plumbing: correlation id, logs, headers, sanitized errors ----------
@app.middleware("http")
async def envelope(request: Request, call_next):
    cid = request.headers.get("x-correlation-id", "")
    try:
        cid = str(uuid.UUID(cid))
    except ValueError:
        cid = str(uuid.uuid4())
    request.state.cid, request.state.user_id = cid, None
    start = time.perf_counter()
    try:
        resp = await call_next(request)
    except Exception as exc:  # unexpected: log class only (no message/args), return sanitized body
        log.error(json.dumps({"cid": cid, "path": request.url.path, "error": "unhandled", "type": type(exc).__name__}))
        resp = JSONResponse(_err("internal_error", "Unexpected error", cid), status_code=500)
    resp.headers.update({"X-Correlation-ID": cid, "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                         "Referrer-Policy": "no-referrer", "Content-Security-Policy": CSP})
    log.info(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "cid": cid, "method": request.method,
                         "path": request.url.path, "status": resp.status_code, "user": str(request.state.user_id) if request.state.user_id else None,
                         "ms": round((time.perf_counter() - start) * 1000, 1)}))
    return resp


def _err(code, message, cid):
    return {"error": {"code": code, "message": message, "correlation_id": cid}}


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    msg = exc.detail if isinstance(exc.detail, str) else "Request failed"
    return JSONResponse(_err(CODES.get(exc.status_code, "error"), msg, request.state.cid),
                        status_code=exc.status_code, headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    return JSONResponse(_err("validation_error", "Invalid request", request.state.cid), status_code=422)


# ---------- auth helpers ----------
def audit(db, request, action, outcome, *, ws=None, otype=None, oid=None, detail=None, actor=None):
    with db.cursor() as cur:
        cur.execute("insert into audit_event(correlation_id,actor_user_id,workspace_id,action,object_type,object_id,outcome,detail)"
                    " values (%s,%s,%s,%s,%s,%s,%s,%s)",
                    (request.state.cid, actor or request.state.user_id, ws, action, otype,
                     str(oid) if oid else None, outcome, json.dumps(detail or {})))


def same_origin(request):
    origin = request.headers.get("origin")
    return origin is None or urlparse(origin).netloc == request.headers.get("host")


def deny(db, request, status, message, action, **kw):
    audit(db, request, action, "deny", **kw)
    db.commit()  # keep the audit row although the request fails
    raise HTTPException(status, message)


def current_user(request: Request, db=DB):
    token = request.cookies.get(config.COOKIE_NAME)
    row = None
    if token:
        with db.cursor() as cur:
            cur.execute(
                "update app_session s set expires_at = least(now() + make_interval(mins => %s), s.created_at + make_interval(hours => %s))"
                " from app_user u where s.id_hash=%s and s.user_id=u.id and s.revoked_at is null and s.expires_at>now() and u.is_active"
                " returning u.id, u.username, u.display_name, u.platform_role, s.csrf_token",
                (config.SESSION_IDLE_MINUTES, config.SESSION_ABSOLUTE_HOURS, security.token_hash(token)))
            row = cur.fetchone()
    if not row:
        raise HTTPException(401, "Authentication required")
    request.state.user_id = row["id"]
    if request.method in UNSAFE:
        if not same_origin(request):
            deny(db, request, 403, "Cross-origin request rejected", "csrf.origin")
        if not security.same(request.headers.get("x-csrf-token", ""), row["csrf_token"]):
            deny(db, request, 403, "CSRF token missing or invalid", "csrf.token")
    return row


def superadmin(request: Request, user=Depends(current_user), db=DB):
    if user["platform_role"] != "superadmin":
        deny(db, request, 403, "Insufficient permission", "platform.denied")
    return user


def workspace_access(permission):
    """Dependency factory: membership (404 if none, so existence is not leaked) then permission (403)."""
    def dep(workspace_id: uuid.UUID, request: Request, user=Depends(current_user), db=DB):
        if user["platform_role"] == "superadmin":
            role = "admin"
        else:
            with db.cursor() as cur:
                cur.execute("select role from membership where workspace_id=%s and user_id=%s", (workspace_id, user["id"]))
                m = cur.fetchone()
            if not m:
                deny(db, request, 404, "Not found", f"{permission}.denied", ws=workspace_id, detail={"reason": "not_member"})
            role = m["role"]
        if not rbac.allowed(role, permission):
            deny(db, request, 403, "Insufficient permission", f"{permission}.denied", ws=workspace_id, detail={"role": role})
        return {"user": user, "role": role, "workspace_id": workspace_id}
    return dep


# ---------- models ----------
class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=256)


class UserIn(BaseModel):
    username: str = Field(pattern=r"^[A-Za-z0-9._-]{3,64}$")
    display_name: str = Field(default="", max_length=100)
    password: str = Field(min_length=12, max_length=256)


class PasswordChangeIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


class WorkspaceIn(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,40}$")
    name: str = Field(min_length=1, max_length=100)


class MemberIn(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    role: Literal["viewer", "author", "reviewer", "operator", "admin"]


# ---------- public ----------
@app.get("/healthz")
def healthz():
    return {"status": "ok"}


def _redis_ok():
    url = config.get("UETL_REDIS_URL")
    if not url:
        return True
    u = urlparse(url)
    try:
        with socket.create_connection((u.hostname, u.port or 6379), timeout=2) as s:
            if u.password:
                s.sendall(f"AUTH {u.password}\r\n".encode())
                if not s.recv(64).startswith(b"+OK"):
                    return False
            s.sendall(b"PING\r\n")
            return s.recv(64).startswith(b"+PONG")
    except OSError:
        return False


@app.get("/readyz")
def readyz():
    try:
        ping()
        pg = True
    except Exception:
        pg = False
    ok = pg and _redis_ok()
    return JSONResponse({"status": "ready" if ok else "unavailable"}, status_code=200 if ok else 503)


# ---------- auth ----------
@app.post("/api/v2/auth/login")
def login(body: LoginIn, request: Request, response: Response, db=DB):
    if not same_origin(request):
        deny(db, request, 403, "Cross-origin request rejected", "login.origin")
    with db.cursor() as cur:
        cur.execute("select * from app_user where lower(username)=lower(%s)", (body.username,))
        u = cur.fetchone()
    locked = bool(u and u["locked_until"]) and u["locked_until"].timestamp() > time.time()
    ok = security.verify_password(u["password_hash"] if u else None, body.password)
    if locked:
        deny(db, request, 429, "Too many failed attempts. Try again later.", "login.locked", actor=u["id"])
    if not (u and u["is_active"] and ok):
        if u:
            with db.cursor() as cur:
                cur.execute("update app_user set failed_logins=failed_logins+1,"
                            " locked_until=case when failed_logins+1>=%s then now()+make_interval(mins=>%s) else locked_until end"
                            " where id=%s", (config.MAX_FAILED_LOGINS, config.LOCKOUT_MINUTES, u["id"]))
        deny(db, request, 401, "Invalid username or password", "login.failed", actor=u["id"] if u else None)
    token, csrf = security.new_token(), security.new_token()
    with db.cursor() as cur:
        cur.execute("delete from app_session where expires_at < now() - interval '1 day'")
        cur.execute("update app_user set failed_logins=0, locked_until=null where id=%s", (u["id"],))
        cur.execute("insert into app_session(id_hash,user_id,csrf_token,expires_at,ip)"
                    " values (%s,%s,%s,now()+make_interval(mins=>%s),%s)",
                    (security.token_hash(token), u["id"], csrf, config.SESSION_IDLE_MINUTES,
                     _client_ip(request)))
    request.state.user_id = u["id"]
    audit(db, request, "login.success", "allow")
    response.set_cookie(config.COOKIE_NAME, token, httponly=True, samesite="strict", secure=config.COOKIE_SECURE,
                        max_age=config.SESSION_IDLE_MINUTES * 60, path="/")
    return {"csrf": csrf, "user": _public_user(u)}


def _client_ip(request):
    try:
        return str(ipaddress.ip_address(request.client.host))
    except (ValueError, AttributeError):
        return None


def _public_user(u):
    return {"id": u["id"], "username": u["username"], "display_name": u["display_name"], "platform_role": u["platform_role"]}


@app.post("/api/v2/auth/logout")
def logout(request: Request, response: Response, user=Depends(current_user), db=DB):
    with db.cursor() as cur:
        cur.execute("update app_session set revoked_at=now() where id_hash=%s", (security.token_hash(request.cookies[config.COOKIE_NAME]),))
    audit(db, request, "logout", "allow")
    response.delete_cookie(config.COOKIE_NAME, path="/")
    return {"status": "signed_out"}


@app.post("/api/v2/auth/change-password")
def change_password(body: PasswordChangeIn, request: Request, user=Depends(current_user), db=DB):
    with db.cursor() as cur:
        cur.execute("select password_hash from app_user where id=%s", (user["id"],))
        current_hash = cur.fetchone()["password_hash"]
    if not security.verify_password(current_hash, body.current_password):
        with db.cursor() as cur:  # a wrong "current password" counts toward the same lockout as a wrong login
            cur.execute("update app_user set failed_logins=failed_logins+1,"
                        " locked_until=case when failed_logins+1>=%s then now()+make_interval(mins=>%s) else locked_until end"
                        " where id=%s", (config.MAX_FAILED_LOGINS, config.LOCKOUT_MINUTES, user["id"]))
        deny(db, request, 400, "Current password is incorrect", "password.change.failed")
    if security.verify_password(current_hash, body.new_password):
        raise HTTPException(400, "New password must differ from the current one")
    with db.cursor() as cur:
        cur.execute("update app_user set password_hash=%s, failed_logins=0 where id=%s",
                    (security.hash_password(body.new_password), user["id"]))
        # every other session of this user is revoked; the current one stays signed in
        cur.execute("update app_session set revoked_at=now() where user_id=%s and revoked_at is null and id_hash<>%s",
                    (user["id"], security.token_hash(request.cookies[config.COOKIE_NAME])))
    audit(db, request, "password.change", "allow", otype="user", oid=user["id"])
    return {"status": "changed"}


@app.get("/api/v2/auth/me")
def me(user=Depends(current_user), db=DB):
    with db.cursor() as cur:
        if user["platform_role"] == "superadmin":
            cur.execute("select id,slug,name,'admin' as role from workspace order by name")
        else:
            cur.execute("select w.id,w.slug,w.name,m.role from membership m join workspace w on w.id=m.workspace_id"
                        " where m.user_id=%s order by w.name", (user["id"],))
        ws = cur.fetchall()
    return {"user": _public_user(user), "csrf": user["csrf_token"], "workspaces": ws}


# ---------- platform users / workspaces ----------
@app.get("/api/v2/users")
def list_users(user=Depends(superadmin), db=DB):
    with db.cursor() as cur:
        cur.execute("select id,username,display_name,platform_role,is_active,created_at from app_user order by username")
        return cur.fetchall()


@app.post("/api/v2/users", status_code=201)
def create_user(body: UserIn, request: Request, user=Depends(superadmin), db=DB):
    with db.cursor() as cur:
        cur.execute("select 1 from app_user where lower(username)=lower(%s)", (body.username,))
        if cur.fetchone():
            raise HTTPException(409, "Username already exists")
        cur.execute("insert into app_user(username,display_name,password_hash) values (%s,%s,%s) returning id,username,display_name",
                    (body.username, body.display_name, security.hash_password(body.password)))
        row = cur.fetchone()
    audit(db, request, "user.create", "allow", otype="user", oid=row["id"])
    return row


@app.get("/api/v2/workspaces")
def list_workspaces(user=Depends(current_user), db=DB):
    return me(user, db)["workspaces"]


@app.post("/api/v2/workspaces", status_code=201)
def create_workspace(body: WorkspaceIn, request: Request, user=Depends(superadmin), db=DB):
    with db.cursor() as cur:
        cur.execute("select 1 from workspace where slug=%s", (body.slug,))
        if cur.fetchone():
            raise HTTPException(409, "Workspace slug already exists")
        cur.execute("insert into workspace(slug,name,created_by) values (%s,%s,%s) returning id,slug,name",
                    (body.slug, body.name, user["id"]))
        row = cur.fetchone()
        cur.execute("insert into membership(workspace_id,user_id,role) values (%s,%s,'admin')", (row["id"], user["id"]))
    audit(db, request, "workspace.create", "allow", ws=row["id"], otype="workspace", oid=row["id"])
    return row


# ---------- members ----------
@app.get("/api/v2/workspaces/{workspace_id}/members")
def list_members(ctx=Depends(workspace_access("user.manage")), db=DB):
    with db.cursor() as cur:
        cur.execute("select u.id,u.username,u.display_name,m.role from membership m join app_user u on u.id=m.user_id"
                    " where m.workspace_id=%s order by u.username", (ctx["workspace_id"],))
        return cur.fetchall()


@app.post("/api/v2/workspaces/{workspace_id}/members", status_code=201)
def add_member(body: MemberIn, request: Request, ctx=Depends(workspace_access("user.manage")), db=DB):
    ws = ctx["workspace_id"]
    with db.cursor() as cur:
        cur.execute("select id from app_user where lower(username)=lower(%s) and is_active", (body.username,))
        u = cur.fetchone()
        if not u:
            raise HTTPException(404, "User not found")
        cur.execute("insert into membership(workspace_id,user_id,role) values (%s,%s,%s)"
                    " on conflict (workspace_id,user_id) do update set role=excluded.role", (ws, u["id"], body.role))
    audit(db, request, "member.set", "allow", ws=ws, otype="user", oid=u["id"], detail={"role": body.role})
    return {"user_id": u["id"], "role": body.role}


@app.delete("/api/v2/workspaces/{workspace_id}/members/{user_id}")
def remove_member(user_id: uuid.UUID, request: Request, ctx=Depends(workspace_access("user.manage")), db=DB):
    ws = ctx["workspace_id"]
    with db.cursor() as cur:
        cur.execute("select role from membership where workspace_id=%s and user_id=%s", (ws, user_id))
        m = cur.fetchone()
        if not m:
            raise HTTPException(404, "Not found")
        if m["role"] == "admin":
            cur.execute("select count(*) as n from membership where workspace_id=%s and role='admin'", (ws,))
            if cur.fetchone()["n"] <= 1:
                raise HTTPException(409, "Cannot remove the last admin")
        cur.execute("delete from membership where workspace_id=%s and user_id=%s", (ws, user_id))
    audit(db, request, "member.remove", "allow", ws=ws, otype="user", oid=user_id)
    return {"status": "removed"}


# ---------- audit ----------
@app.get("/api/v2/workspaces/{workspace_id}/audit-events")
def audit_events(limit: int = 100, ctx=Depends(workspace_access("settings.manage")), db=DB):
    with db.cursor() as cur:
        cur.execute("select a.id,a.at,a.correlation_id,u.username as actor,a.action,a.object_type,a.object_id,a.outcome"
                    " from audit_event a left join app_user u on u.id=a.actor_user_id"
                    " where a.workspace_id=%s order by a.id desc limit %s", (ctx["workspace_id"], max(1, min(limit, 200))))
        return cur.fetchall()


# ---------- Phase 2: secret refs + source connections ----------
app.include_router(connections.build(workspace_access, DB, audit))
app.include_router(sources.build(workspace_access, DB, audit))
app.include_router(dataset_requests.build(workspace_access, DB, audit))


# ---------- static UI (existing pilot UI, unchanged files + v2-ui.js) ----------
STATIC = {"/": "index.html", "/index.html": "index.html", "/styles.css": "styles.css",
          "/ui-reference-theme.css": "ui-reference-theme.css", "/assets/utac-logo-source.png": "assets/utac-logo-source.png",
          "/app.js": "app.js", "/demo-sync.js": "demo-sync.js", "/sync-ui.js": "sync-ui.js",
          "/dataset-workflow.js": "dataset-workflow.js", "/prototype.js": "prototype.js",
          "/real-source-ui.js": "real-source-ui.js", "/v2-ui.js": "v2-ui.js", "/v2-ui.css": "v2-ui.css"}
STATIC["/v2-main.js"] = "v2-main.js"
STATIC["/v2-store.js"] = "v2-store.js"
STATIC["/v2-table.js"] = "v2-table.js"
STATIC["/v2-forms.js"] = "v2-forms.js"
# Manifest entries, rather than a directory mount, define the vendor allowlist.
for _vendor_file in json.loads((config.ROOT / "vendor/tanstack/MANIFEST.json").read_text()):
    STATIC["/vendor/tanstack/" + _vendor_file] = "vendor/tanstack/" + _vendor_file


@app.get("/{path:path}", include_in_schema=False)
def static(path: str):
    rel = STATIC.get("/" + path)
    if not rel or re.search(r"\.\.", path):
        raise HTTPException(404, "Not found")
    return FileResponse(config.ROOT / rel, media_type="text/javascript" if rel.endswith((".js", ".mjs")) else None)
