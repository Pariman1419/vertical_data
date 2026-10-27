"""Phase 1 API tests against the live spiec_verti schema (TESTED LIVE; HTTP layer is in-process).

All DB work runs on ONE connection that is rolled back at the end: nothing is persisted.
"""
import logging
import pathlib
import sys
import uuid

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
psycopg2 = pytest.importorskip("psycopg2")
import psycopg2.extras  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.v2 import config, security  # noqa: E402
from backend.v2.app import app  # noqa: E402
from backend.v2.db import get_db  # noqa: E402

PW = "correct horse battery 1"
HASH = security.hash_password(PW)
ORIGIN = {"Origin": "https://testserver"}


class Shared:
    """One transaction for the whole test; commit/rollback inside requests are no-ops."""
    def __init__(self, conn): self.conn = conn
    def cursor(self): return self.conn.cursor()
    def commit(self): pass
    def rollback(self): pass


@pytest.fixture()
def env():
    try:
        conn = psycopg2.connect(host=config.get("UETL_PG_HOST"), port=config.get("UETL_PG_PORT"), dbname=config.get("UETL_PG_DB"),
                                user="uetl_app", password=config.get("UETL_APP_PASSWORD"), connect_timeout=5,
                                options="-c search_path=uetl_meta", cursor_factory=psycopg2.extras.RealDictCursor)
    except Exception as ex:
        pytest.skip(f"database unavailable: {ex}")
    shared = Shared(conn)
    app.dependency_overrides[get_db] = lambda: shared
    cur = conn.cursor()

    def mk_user(name, platform="none"):
        cur.execute("insert into app_user(username,password_hash,platform_role) values (%s,%s,%s) returning id", (name, HASH, platform))
        return cur.fetchone()["id"]

    def mk_ws(slug):
        cur.execute("insert into workspace(slug,name) values (%s,%s) returning id", (slug, slug))
        return cur.fetchone()["id"]

    def member(ws, uid, role):
        cur.execute("insert into membership(workspace_id,user_id,role) values (%s,%s,%s)", (ws, uid, role))

    e = type("E", (), {})()
    e.cur, e.mk_user = cur, mk_user
    e.ws1, e.ws2 = mk_ws("t-one"), mk_ws("t-two")
    e.root = mk_user("t_root", "superadmin")
    e.admin1, e.viewer1, e.author1, e.admin2 = mk_user("t_admin1"), mk_user("t_viewer1"), mk_user("t_author1"), mk_user("t_admin2")
    member(e.ws1, e.admin1, "admin"); member(e.ws1, e.viewer1, "viewer"); member(e.ws1, e.author1, "author")
    member(e.ws2, e.admin2, "admin")

    def client(name=None):
        c = TestClient(app, base_url="https://testserver")
        if name:
            r = c.post("/api/v2/auth/login", json={"username": name, "password": PW})
            assert r.status_code == 200, r.text
            c.headers.update({"X-CSRF-Token": r.json()["csrf"], **ORIGIN})
        return c
    e.client = client
    yield e
    app.dependency_overrides.clear()
    conn.rollback()
    conn.close()


def routes():
    spec = app.openapi()
    for path, ops in spec["paths"].items():
        for method in ops:
            yield path, method.upper()


def fill(path):
    out = path
    for name in ("workspace_id", "user_id"):
        out = out.replace("{" + name + "}", str(uuid.uuid4()))
    return out


PUBLIC = {"/api/v2/auth/login", "/healthz", "/readyz"}


def test_every_api_route_requires_authentication(env):
    c = env.client()
    seen = 0
    for path, method in routes():
        if path in PUBLIC:
            continue
        r = c.request(method, fill(path), json={})
        assert r.status_code == 401, (method, path, r.status_code)
        seen += 1
    assert seen >= 9


def test_cross_workspace_access_is_404_on_every_workspace_route(env):
    c = env.client("t_admin1")
    n = 0
    for path, method in routes():
        if "{workspace_id}" not in path:
            continue
        r = c.request(method, fill(path.replace("{workspace_id}", str(env.ws2))), json={"username": "x", "role": "viewer"})
        assert r.status_code == 404, (method, path, r.status_code)
        n += 1
    assert n >= 4


def test_workspace_routes_allow_own_workspace_admin(env):
    c = env.client("t_admin1")
    assert c.get(f"/api/v2/workspaces/{env.ws1}/members").status_code == 200
    assert c.get(f"/api/v2/workspaces/{env.ws1}/audit-events").status_code == 200


def test_viewer_and_author_cannot_manage_members_or_read_audit(env):
    for who in ("t_viewer1", "t_author1"):
        c = env.client(who)
        for method, path in (("GET", "members"), ("POST", "members"), ("GET", "audit-events")):
            r = c.request(method, f"/api/v2/workspaces/{env.ws1}/{path}", json={"username": "t_admin2", "role": "admin"})
            assert r.status_code == 403, (who, method, path)


def test_non_superadmin_cannot_create_users_or_workspaces(env):
    c = env.client("t_admin1")
    assert c.post("/api/v2/users", json={"username": "newbie", "password": PW}).status_code == 403
    assert c.post("/api/v2/workspaces", json={"slug": "zzz", "name": "z"}).status_code == 403
    assert c.get("/api/v2/users").status_code == 403


def test_superadmin_creates_user_and_workspace_and_hash_is_argon2id(env):
    c = env.client("t_root")
    r = c.post("/api/v2/users", json={"username": "t_new_user", "display_name": "N", "password": "a-long-enough-pass"})
    assert r.status_code == 201 and "password" not in r.text
    env.cur.execute("select password_hash from app_user where username='t_new_user'")
    assert env.cur.fetchone()["password_hash"].startswith("$argon2id$")
    assert c.post("/api/v2/users", json={"username": "T_NEW_USER", "password": "a-long-enough-pass"}).status_code == 409
    assert c.post("/api/v2/users", json={"username": "short", "password": "short"}).status_code == 422
    assert c.post("/api/v2/workspaces", json={"slug": "t-new-ws", "name": "New"}).status_code == 201


def test_csrf_and_origin_enforced_on_unsafe_methods(env):
    c = env.client("t_admin1")
    body = {"username": "t_viewer1", "role": "reviewer"}
    url = f"/api/v2/workspaces/{env.ws1}/members"
    assert c.post(url, json=body, headers={"X-CSRF-Token": "wrong"}).status_code == 403
    no_csrf = env.client()
    no_csrf.cookies.update(c.cookies)
    assert no_csrf.post(url, json=body).status_code == 403
    assert c.post(url, json=body, headers={"Origin": "https://evil.example"}).status_code == 403
    assert c.post(url, json=body).status_code == 201


def test_login_cookie_flags_and_generic_failure(env):
    c = env.client()
    ok = c.post("/api/v2/auth/login", json={"username": "t_admin1", "password": PW})
    cookie = ok.headers["set-cookie"].lower()
    assert "httponly" in cookie and "secure" in cookie and "samesite=strict" in cookie
    bad = c.post("/api/v2/auth/login", json={"username": "t_admin1", "password": "nope"})
    ghost = c.post("/api/v2/auth/login", json={"username": "t_nobody", "password": "nope"})
    assert bad.status_code == ghost.status_code == 401 and bad.json()["error"]["message"] == ghost.json()["error"]["message"]
    assert c.post("/api/v2/auth/login", json={"username": "t_admin1", "password": PW},
                  headers={"Origin": "https://evil.example"}).status_code == 403


def test_lockout_after_repeated_failures(env):
    c = env.client()
    for _ in range(5):
        assert c.post("/api/v2/auth/login", json={"username": "t_viewer1", "password": "bad"}).status_code == 401
    assert c.post("/api/v2/auth/login", json={"username": "t_viewer1", "password": PW}).status_code == 429


def test_logout_revokes_session(env):
    c = env.client("t_admin1")
    stale = c.cookies.get(config.COOKIE_NAME)
    assert c.post("/api/v2/auth/logout").status_code == 200
    again = env.client()
    again.cookies.set(config.COOKIE_NAME, stale)
    assert again.get("/api/v2/auth/me").status_code == 401


def test_cannot_remove_last_admin(env):
    c = env.client("t_admin1")
    r = c.delete(f"/api/v2/workspaces/{env.ws1}/members/{env.admin1}")
    assert r.status_code == 409


def test_denials_are_audited_and_visible_to_admin(env):
    env.client("t_viewer1").get(f"/api/v2/workspaces/{env.ws1}/members")
    env.client("t_admin1").get(f"/api/v2/workspaces/{env.ws2}/members")
    rows = env.client("t_admin1").get(f"/api/v2/workspaces/{env.ws1}/audit-events").json()
    assert any(r["action"] == "user.manage.denied" and r["outcome"] == "deny" and r["actor"] == "t_viewer1" for r in rows)
    env.cur.execute("select count(*) as n from audit_event where action='user.manage.denied' and workspace_id=%s and detail->>'reason'='not_member'", (env.ws2,))
    assert env.cur.fetchone()["n"] >= 1


def test_errors_carry_correlation_id_and_never_echo_input(env):
    c = env.client()
    cid = str(uuid.uuid4())
    r = c.post("/api/v2/auth/login", json={"username": "x" * 500, "password": "SECRET-CANARY-123"}, headers={"X-Correlation-ID": cid})
    assert r.status_code == 422 and r.headers["x-correlation-id"] == cid
    assert r.json()["error"]["correlation_id"] == cid
    assert "CANARY" not in r.text and "xxxx" not in r.text
    assert c.get("/api/v2/auth/me").headers["x-correlation-id"] != cid
    assert "default-src 'self'" in r.headers["content-security-policy"]


def test_logs_do_not_contain_secrets(env, caplog):
    caplog.set_level(logging.INFO, logger="uetl")
    env.client().post("/api/v2/auth/login", json={"username": "t_admin1", "password": "SECRET-CANARY-456"})
    c = env.client("t_admin1")
    c.get("/api/v2/auth/me")
    text = caplog.text
    assert "CANARY" not in text and PW not in text and c.headers["X-CSRF-Token"] not in text
    assert '"cid"' in text


def test_health_endpoints_are_public_and_minimal(env):
    c = env.client()
    assert c.get("/healthz").json() == {"status": "ok"}
    r = c.get("/readyz")
    assert r.status_code in (200, 503) and set(r.json()) == {"status"}


def test_static_allowlist(env):
    c = env.client()
    assert c.get("/").status_code == 200
    assert c.get("/backend/v2/app.py").status_code == 404
    assert c.get("/.env").status_code == 404


def test_change_password_flow(env):
    a, b = env.client("t_author1"), env.client("t_author1")  # two live sessions of the same user
    new = "a brand new passphrase 2"
    assert a.post("/api/v2/auth/change-password", json={"current_password": "wrong", "new_password": new}).status_code == 400
    assert a.post("/api/v2/auth/change-password", json={"current_password": PW, "new_password": "short"}).status_code == 422
    assert a.post("/api/v2/auth/change-password", json={"current_password": PW, "new_password": PW}).status_code == 400
    no_csrf = env.client(); no_csrf.cookies.update(a.cookies)
    assert no_csrf.post("/api/v2/auth/change-password", json={"current_password": PW, "new_password": new}).status_code == 403
    assert a.post("/api/v2/auth/change-password", json={"current_password": PW, "new_password": new}).status_code == 200
    assert a.get("/api/v2/auth/me").status_code == 200          # current session survives
    assert b.get("/api/v2/auth/me").status_code == 401          # other session revoked
    c = env.client()
    assert c.post("/api/v2/auth/login", json={"username": "t_author1", "password": PW}).status_code == 401
    assert c.post("/api/v2/auth/login", json={"username": "t_author1", "password": new}).status_code == 200
    env.cur.execute("select count(*) as n from audit_event where action='password.change' and outcome='allow'")
    assert env.cur.fetchone()["n"] == 1


def test_change_password_requires_authentication(env):
    assert env.client().post("/api/v2/auth/change-password", json={"current_password": "x", "new_password": "y" * 12}).status_code == 401


def test_wrong_current_password_counts_toward_lockout(env):
    c = env.client("t_viewer1")
    for _ in range(5):
        assert c.post("/api/v2/auth/change-password", json={"current_password": "bad", "new_password": "z" * 14}).status_code == 400
    assert env.client().post("/api/v2/auth/login", json={"username": "t_viewer1", "password": PW}).status_code == 429


def test_transaction_commits_before_response_is_sent():
    """Structural guard (not behavioural): default dependency scope would run commit AFTER the response is sent."""
    import inspect
    from backend.v2 import app as appmod
    src = inspect.getsource(appmod)
    assert 'DB = Depends(get_db, scope="function")' in src
    assert "Depends(get_db)" not in src.replace('Depends(get_db, scope="function")', "")
