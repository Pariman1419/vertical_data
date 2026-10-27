"""Phase 2 (part 2) tests. TESTED LIVE against the SPICE host at 10.153.90.17 (read-only SELECT/DESCRIBE only)."""
import decimal
import json
import time

import pytest

from test_api import env  # noqa: F401
from backend.v2 import spice

LIVE = {"base_url": "http://10.153.90.17:8091", "timeout_s": 10, "tls_verify": True, "secret_ref": None}


def _live():
    try:
        return spice.health(LIVE)
    except spice.SpiceError:
        return False


live = pytest.mark.skipif(not _live(), reason="SPICE host not reachable from this machine")


@pytest.fixture()
def conn(env):
    c = env.client("t_admin1")
    base = f"/api/v2/workspaces/{env.ws1}/connections"
    r = c.post(base, json={"name": "live", "kind": "rest", "base_url": LIVE["base_url"]})
    assert r.status_code == 201, r.text
    return c, f"{base}/{r.json()['id']}"


# ---------- pure unit tests (no network) ----------
def test_literals_are_typed_and_escaped():
    assert spice.literal("Utf8", "o'brien") == "'o''brien'"
    assert spice.literal("Int64", "42") == "42"
    assert spice.literal("Decimal128(38, 10)", "1.50") == "1.50"
    assert spice.literal("Date32", "2026-01-31") == "DATE '2026-01-31'"
    for t, v in (("Int64", "1; drop table x"), ("Int64", "1.5"), ("Decimal128(38, 10)", "NaN"), ("Date32", "x'--"),
                 ("Boolean", "yes"), ("Utf8", "a" * 201), ("Binary", "x")):
        with pytest.raises(ValueError):
            spice.literal(t, v)


def test_build_select_quotes_everything():
    cols = {"select": ["a", "b"], "types": {"a": "Utf8", "b": "Int64"}}
    sql = spice.build_select("sixmonth.t", cols, [{"column": "a", "op": "!=", "value": "x'y"}], 5)
    assert sql == "SELECT \"a\", \"b\" FROM \"sixmonth\".\"t\" WHERE \"a\" <> 'x''y' LIMIT 5"
    with pytest.raises(ValueError):
        spice.quote('a"; drop')


def test_jsonable_keeps_precision_as_strings():
    assert spice._jsonable(decimal.Decimal("123456789012345678.1234567890")) == "123456789012345678.1234567890"
    assert spice._jsonable(9007199254740993) == "9007199254740993"
    assert spice._jsonable(7) == 7


def test_unreachable_source_gives_safe_message(monkeypatch):
    from backend.v2 import netpolicy
    monkeypatch.setattr(netpolicy, "resolve_pinned", lambda url: ("127.0.0.1", 9))  # nothing listens on port 9
    with pytest.raises(spice.SpiceError) as e:
        spice.health({"base_url": "http://10.0.0.7:8091", "timeout_s": 1, "tls_verify": True, "secret_ref": None})
    assert e.value.code in ("unreachable", "timeout") and "10.0.0.7" not in str(e.value)


# ---------- live ----------
@live
def test_test_connection_catalog_and_preview(env, conn):
    c, url = conn
    t = c.post(url + "/test").json()
    assert t["status"] == "ok" and t["capabilities"]["streaming"] is True and t["capabilities"]["datasets"] >= 1
    assert t["capabilities"]["bind_parameters"] is False
    assert c.get(url + "/capabilities").json()["status"] == "ok"

    assert c.get(url + "/catalog").json()["objects"] == {}                       # nothing refreshed yet
    rf = c.post(url + "/catalog/refresh").json()
    assert rf["revision"] == 1 and rf["objects"] >= 1
    names = [o["name"] for o in c.get(url + "/catalog/all").json()["objects"]]
    assert "machine_map" in names
    assert c.get(url + "/catalog").json()["objects"] == {}                       # visible only once allow-listed

    body = {"object": "machine_map", "limit": 5}
    r = c.post(url + "/preview", json=body)
    assert r.status_code == 403                                                 # not allow-listed yet
    assert c.put(url + "/allowed-objects", json={"objects": ["machine_map"]}).status_code == 200
    cat = c.get(url + "/catalog").json()["objects"]["machine_map"]["columns"]
    col = cat[0]["name"]

    r = c.post(url + "/preview", json=body)
    assert r.status_code == 200, r.text
    d = r.json()
    assert 1 <= len(d["rows"]) <= 5 and len(d["columns"]) == len(cat)
    r = c.post(url + "/preview", json={**body, "columns": [col], "limit": 1})
    assert r.status_code == 200 and len(r.json()["columns"]) == 1 and len(r.json()["rows"]) == 1


@live
def test_preview_rejects_injection_and_bad_input(env, conn):
    c, url = conn
    c.post(url + "/catalog/refresh")
    c.put(url + "/allowed-objects", json={"objects": ["machine_map"]})
    col = c.get(url + "/catalog").json()["objects"]["machine_map"]["columns"][0]
    for bad in ({"object": "machine_map; drop table x"}, {"object": "other_table"}, {"object": "pg_catalog.pg_user"}):
        assert c.post(url + "/preview", json=bad).status_code in (403, 422), bad
    assert c.post(url + "/preview", json={"object": "machine_map", "columns": ['x" FROM y --']}).status_code == 422
    assert c.post(url + "/preview", json={"object": "machine_map", "columns": ["nope"]}).status_code == 422
    assert c.post(url + "/preview", json={"object": "machine_map", "limit": 100000}).status_code == 422
    f = {"column": col["name"], "op": "=", "value": "x'; DROP TABLE t; --"}
    r = c.post(url + "/preview", json={"object": "machine_map", "filters": [f]})
    assert r.status_code in (200, 422)                                          # escaped literal or type mismatch, never executed
    assert c.post(url + "/preview", json={"object": "machine_map", "filters": [{**f, "op": "LIKE"}]}).status_code == 422


@live
def test_preview_permissions_and_isolation(env, conn):
    c, url = conn
    assert env.client("t_viewer1").post(url + "/preview", json={"object": "machine_map"}).status_code == 403
    assert env.client("t_viewer1").post(url + "/test").status_code == 403
    other = url.replace(str(env.ws1), str(env.ws2))
    assert env.client("t_admin2").post(other + "/test").status_code == 404


@live
def test_flight_budgets_stop_early_without_reading_everything():
    t = time.perf_counter()
    cols, rows, truncated = spice.run_bounded(LIVE, "SELECT * FROM generate_series(1, 2000000)", max_rows=10)
    assert len(rows) == 10 and truncated and time.perf_counter() - t < 3
    cols, rows, truncated = spice.run_bounded(LIVE, "SELECT * FROM generate_series(1, 2000000)", max_rows=1000, max_bytes=50_000)
    assert truncated and len(rows) < 1000 + 8192


@live
def test_exact_numbers_survive():
    cols, rows, _ = spice.run_bounded(LIVE, "SELECT CAST('123456789012345678.1234567890' AS DECIMAL(38,10)) AS d,"
                                            " CAST(9007199254740993 AS BIGINT) AS i", max_rows=1)
    assert rows[0] == ["123456789012345678.1234567890", "9007199254740993"]


@live
def test_errors_never_leak_source_text(env, conn):
    c, url = conn
    c.post(url + "/catalog/refresh")
    c.put(url + "/allowed-objects", json={"objects": ["machine_map"]})
    snap_cols = c.get(url + "/catalog").json()["objects"]["machine_map"]["columns"]
    assert snap_cols
    with pytest.raises(spice.SpiceError) as e:
        spice.run_bounded(LIVE, "SELECT * FROM no_such_table_zz", max_rows=1)
    assert "spice.public" not in str(e.value) and "no_such_table_zz" not in str(e.value)
    assert json.dumps(c.post(url + "/test").json()).count("spice.public") == 0


@live
def test_preview_works_for_sources_that_reject_limit_pushdown(env, conn):
    c, url = conn                      # 'alarm' is backed by SQL Server, which rejects the pushed-down LIMIT
    c.post(url + "/catalog/refresh")
    c.put(url + "/allowed-objects", json={"objects": ["alarm"]})
    r = c.post(url + "/preview", json={"object": "alarm", "limit": 3})
    assert r.status_code == 200, r.text
    assert len(r.json()["rows"]) == 3 and r.json()["truncated"] is True
