"""Dataset-request tests. DB-level + API-level; the auto-close test fakes the catalog (no SPICE contacted)."""
import json

import pytest

from test_api import env  # noqa: F401
from test_db_guards import denied
from backend.v2 import dataset_requests as dr

HOST_OK = "10.0.0.5:8091"


@pytest.fixture()
def conn(env, monkeypatch):
    from backend.v2 import netpolicy
    monkeypatch.setattr(netpolicy, "allowed_hosts", lambda: {HOST_OK})
    monkeypatch.setattr(netpolicy.socket, "getaddrinfo", lambda h, p, type=0: [(2, 1, 6, "", ("10.0.0.5", p))])
    c = env.client("t_admin1")
    cid = c.post(f"/api/v2/workspaces/{env.ws1}/connections",
                 json={"name": "s", "kind": "rest", "base_url": f"http://{HOST_OK}"}).json()["id"]
    return c, f"/api/v2/workspaces/{env.ws1}/connections/{cid}/dataset-requests", cid


def body(**kw):
    return {"profile": "pg", "dataset_name": "my_new_set", "remote_object": "threemonth.some_table", **kw}


def test_snippet_matches_spicepod_format():
    assert dr.snippet("pg", "lot_x", "sixmonth.YD_LOT") == '- from: postgres:"sixmonth"."YD_LOT"\n  name: lot_x\n  params: *pg\n'
    assert dr.snippet("scada", "alarm2", "AssySCADADB1.dbo.OEEAlmEvents") == \
        "- from: odbc:AssySCADADB1.dbo.OEEAlmEvents\n  name: alarm2\n  params: *scada\n"


def test_create_list_cancel(env, conn):
    c, url, cid = conn
    r = c.post(url, json=body(note="for line 3"))
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["status"] == "pending" and "params: *pg" in d["snippet"]
    assert [x["dataset_name"] for x in c.get(url).json()] == ["my_new_set"]
    assert c.post(url, json=body()).status_code == 409                         # same pending name
    assert c.post(f"{url}/{d['id']}/cancel").json() == {"status": "cancelled"}
    assert c.post(f"{url}/{d['id']}/cancel").status_code == 404                # already closed
    assert c.post(url, json=body()).status_code == 201                          # name is free again


@pytest.mark.parametrize("profile,obj", [
    ("pg", 'a"; drop table x; --.t'), ("pg", "only_one_part"), ("pg", "a.b.c"), ("pg", "a b.c"), ("pg", "a.b\nparams: *evil"),
    ("pg", "a.b: x"), ("pg", "1abc.t"), ("scada", "a.b"), ("scada", "db.dbo.t;x"), ("scada", "db..t"), ("pg", "a." + "x" * 80)])
def test_remote_object_cannot_inject_yaml_or_sql(env, conn, profile, obj):
    c, url, _ = conn
    assert c.post(url, json=body(profile=profile, remote_object=obj)).status_code in (422,), obj


@pytest.mark.parametrize("name", ["Bad", "x", "has space", "a-b", "name\nparams: *x", "1abc", "a" * 70])
def test_dataset_name_is_whitelisted(env, conn, name):
    c, url, _ = conn
    assert c.post(url, json=body(dataset_name=name)).status_code == 422


def test_unknown_profile_rejected(env, conn):
    c, url, _ = conn
    assert c.post(url, json=body(profile="oracle")).status_code == 422


def test_name_already_in_catalog_is_refused(env, conn):
    c, url, cid = conn
    env.cur.execute("insert into catalog_snapshot(connection_id,revision,payload) values (%s,1,%s)",
                    (cid, json.dumps({"objects": {"existing_set": {"columns": []}}})))
    assert c.post(url, json=body(dataset_name="existing_set")).status_code == 409
    assert c.post(url, json=body(dataset_name="brand_new")).status_code == 201


def test_permissions_and_isolation(env, conn):
    c, url, cid = conn
    rid = c.post(url, json=body()).json()["id"]
    viewer = env.client("t_viewer1")
    assert viewer.get(url).status_code == 200                                    # can read, snippet holds no secret
    assert viewer.post(url, json=body(dataset_name="other_name")).status_code == 403
    assert viewer.post(f"{url}/{rid}/cancel").status_code == 403
    other = env.client("t_admin2")
    ws2url = url.replace(str(env.ws1), str(env.ws2))
    assert other.get(ws2url).status_code == 404
    assert other.post(ws2url, json=body(dataset_name="zz_other")).status_code == 404


def test_audit_trail_records_requests(env, conn):
    c, url, _ = conn
    rid = c.post(url, json=body()).json()["id"]
    c.post(f"{url}/{rid}/cancel")
    env.cur.execute("select action from audit_event where workspace_id=%s and action like 'dataset_request.%%' order by at", (env.ws1,))
    assert [x["action"] for x in env.cur.fetchall()] == ["dataset_request.create", "dataset_request.cancel"]


def test_db_guards_closed_request_is_final_and_fields_immutable(env, conn):
    c, url, cid = conn
    rid = c.post(url, json=body()).json()["id"]
    assert "immutable" in str(denied(env.cur, "update dataset_request set dataset_name='changed_name' where id=%s", (rid,)))
    env.cur.execute("update dataset_request set status='applied', closed_at=now() where id=%s", (rid,))
    assert "closed" in str(denied(env.cur, "update dataset_request set status='pending' where id=%s", (rid,)))


def test_refresh_closes_matching_pending_requests(env, conn, monkeypatch):
    from backend.v2 import spice
    c, url, cid = conn
    c.post(url, json=body(dataset_name="will_appear"))
    c.post(url, json=body(dataset_name="stays_pending"))
    monkeypatch.setattr(spice, "list_datasets", lambda conn: ["will_appear", "alarm"])
    monkeypatch.setattr(spice, "describe", lambda conn, n: [{"name": "a", "type": "Utf8", "nullable": True}])
    r = c.post(url.replace("dataset-requests", "catalog/refresh"))
    assert r.status_code == 200 and r.json()["requests_applied"] == 1
    status = {x["dataset_name"]: x["status"] for x in c.get(url).json()}
    assert status == {"will_appear": "applied", "stays_pending": "pending"}
