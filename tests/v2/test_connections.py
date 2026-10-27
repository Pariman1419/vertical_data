"""Phase 2 (part 1) tests: connections, secret refs, URL policy, object allowlist. TESTED LIVE (DB) / no SPICE contacted."""
import pytest

from test_api import env  # noqa: F401  (shared fixture)
from test_db_guards import denied

HOST_OK = "10.0.0.5:8091"
RESOLVE = {"10.0.0.5": "10.0.0.5", "localhost": "127.0.0.1", "169.254.169.254": "169.254.169.254"}


@pytest.fixture()
def spice_allowed(monkeypatch):
    from backend.v2 import netpolicy
    monkeypatch.setattr(netpolicy, "allowed_hosts", lambda: {HOST_OK, "169.254.169.254:80", "localhost:8091"})
    monkeypatch.setattr(netpolicy.socket, "getaddrinfo",
                        lambda host, port, type=0: [(2, 1, 6, "", (RESOLVE.get(host, "8.8.8.8"), port))])


def conn_body(**kw):
    return {"name": "spice-main", "kind": "rest", "base_url": f"http://{HOST_OK}", **kw}


def test_connection_crud_never_returns_secret_values(env, spice_allowed):
    c = env.client("t_admin1")
    base = f"/api/v2/workspaces/{env.ws1}"
    assert c.post(f"{base}/secret-refs", json={"name": "SPICE_TOKEN"}).status_code == 201
    assert c.post(f"{base}/secret-refs", json={"name": "lower-case"}).status_code == 422
    for bad in ("UETL_APP_PASSWORD", "UETL_MIGRATOR_PASSWORD", "PATH", "UETL_REDIS_PASSWORD"):   # must not be referencable
        assert c.post(f"{base}/secret-refs", json={"name": bad}).status_code == 422, bad
    r = c.post(f"{base}/connections", json=conn_body(secret_ref="SPICE_TOKEN"))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["secret_ref"] == "SPICE_TOKEN" and body["auth_mode"] == "secret_ref" and body["status"] == "untested"
    cid = body["id"]
    assert c.post(f"{base}/connections", json=conn_body()).status_code == 409
    assert c.post(f"{base}/connections", json=conn_body(name="x", secret_ref="NOPE_NOT_REAL")).status_code == 404
    assert [x["name"] for x in c.get(f"{base}/connections").json()] == ["spice-main"]
    p = c.patch(f"{base}/connections/{cid}", json={"timeout_s": 30, "secret_ref": None})
    assert p.status_code == 200 and p.json()["timeout_s"] == 30 and p.json()["auth_mode"] == "none"
    assert c.delete(f"{base}/connections/{cid}").status_code == 200
    assert c.get(f"{base}/connections").json() == []


def test_changing_endpoint_resets_learned_state(env, spice_allowed):
    c = env.client("t_admin1")
    base = f"/api/v2/workspaces/{env.ws1}/connections"
    cid = c.post(base, json=conn_body()).json()["id"]
    env.cur.execute("update connection set status='ok', capabilities='{\"rest\": true}', last_test_at=now() where id=%s", (cid,))
    r = c.patch(f"{base}/{cid}", json={"base_url": f"http://{HOST_OK}/v2"})
    assert r.status_code == 200 and r.json()["status"] == "untested" and r.json()["capabilities"] is None
    assert r.json()["last_test_at"] is None


def test_connection_url_policy_blocks_ssrf_targets(env, spice_allowed):
    c = env.client("t_admin1")
    base = f"/api/v2/workspaces/{env.ws1}/connections"
    for url in ("http://localhost:8091",               # loopback even though allow-listed
                "http://169.254.169.254",               # cloud metadata even though allow-listed
                "http://10.0.0.99:8091",                # private address, not on the allowlist
                "ftp://10.0.0.5:8091", "http://user:pw@10.0.0.5:8091", f"http://{HOST_OK}/?x=1", "file:///etc/passwd"):
        r = c.post(base, json=conn_body(name="bad", base_url=url))
        assert r.status_code == 400, (url, r.status_code)
        assert "Connection URL rejected" in r.json()["error"]["message"]
    env.cur.execute("select count(*) as n from connection where workspace_id=%s", (env.ws1,))
    assert env.cur.fetchone()["n"] == 0


def test_dns_rebinding_to_forbidden_address_is_refused(monkeypatch):
    from backend.v2 import netpolicy
    answers = iter(["10.0.0.5", "127.0.0.1"])           # first answer fine, second (at connect time) is loopback
    monkeypatch.setattr(netpolicy.socket, "getaddrinfo", lambda h, p, type=0: [(2, 1, 6, "", (next(answers), p))])
    assert netpolicy.resolve_pinned("http://svc.corp:8091", allow={"svc.corp:8091"}) == ("10.0.0.5", 8091)
    with pytest.raises(netpolicy.PolicyError):
        netpolicy.resolve_pinned("http://svc.corp:8091", allow={"svc.corp:8091"})


def test_empty_allowlist_means_nothing_is_allowed(monkeypatch):
    from backend.v2 import netpolicy
    monkeypatch.setattr(netpolicy, "allowed_hosts", lambda: set())
    with pytest.raises(netpolicy.PolicyError):
        netpolicy.resolve_pinned("http://10.0.0.5:8091")


def test_connection_permissions_and_isolation(env, spice_allowed):
    admin, viewer = env.client("t_admin1"), env.client("t_viewer1")
    base = f"/api/v2/workspaces/{env.ws1}"
    cid = admin.post(f"{base}/connections", json=conn_body()).json()["id"]
    assert viewer.get(f"{base}/connections").status_code == 200                 # connection.read
    assert viewer.post(f"{base}/connections", json=conn_body(name="v")).status_code == 403
    assert viewer.get(f"{base}/secret-refs").status_code == 403
    assert viewer.put(f"{base}/connections/{cid}/allowed-objects", json={"objects": []}).status_code == 403
    other = env.client("t_admin2")                                               # admin of ANOTHER workspace
    ws2 = f"/api/v2/workspaces/{env.ws2}"
    assert other.get(f"{ws2}/connections/{cid}/allowed-objects").status_code == 404
    assert other.patch(f"{ws2}/connections/{cid}", json={"timeout_s": 5}).status_code == 404
    assert other.delete(f"{ws2}/connections/{cid}").status_code == 404
    assert other.get(f"{ws2}/connections").json() == []


def test_object_allowlist_validation(env, spice_allowed):
    c = env.client("t_admin1")
    base = f"/api/v2/workspaces/{env.ws1}"
    cid = c.post(f"{base}/connections", json=conn_body()).json()["id"]
    url = f"{base}/connections/{cid}/allowed-objects"
    assert c.put(url, json={"objects": ["sixmonth.lot_summary", "equip_reg", "equip_reg"]}).json() == ["equip_reg", "sixmonth.lot_summary"]
    for bad in ("a; drop table x", "a b", "a.b.c.d", "", "x'--", "a" * 201):
        assert c.put(url, json={"objects": [bad]}).status_code == 422, bad
    assert c.get(url).json() == ["equip_reg", "sixmonth.lot_summary"]            # failed PUTs changed nothing


def test_db_rejects_secret_ref_from_other_workspace(env):
    env.cur.execute("insert into secret_ref(workspace_id,name,provider) values (%s,'OTHER_WS_SECRET','env') returning id", (env.ws2,))
    sid = env.cur.fetchone()["id"]
    err = denied(env.cur, "insert into connection(workspace_id,name,kind,base_url,secret_ref_id) values (%s,'x','rest','http://h',%s)",
                 (env.ws1, sid))
    assert "another workspace" in str(err)
