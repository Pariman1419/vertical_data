"""Phase 2 (part 2) tests. TESTED LIVE against the SPICE host at 10.153.90.17 (read-only SELECT/DESCRIBE only)."""
import decimal
import json
import time
from contextlib import contextmanager

import pytest

from test_api import env  # noqa: F401
from backend.v2 import limiter, spice

LIVE = {"base_url": "http://10.153.90.17:8091", "timeout_s": 10, "tls_verify": True, "secret_ref": None}
MOCK_OBJECT = 'cycletime_mock'


def _live():
    try:
        return spice.health(LIVE)
    except spice.SpiceError:
        return False


live = pytest.mark.skipif(not _live(), reason="SPICE host not reachable from this machine")


@pytest.fixture()
def conn(env, monkeypatch):
    list_datasets = spice.list_datasets
    # Phase 3 tests may inspect/read only synthetic or _mock datasets, never production/SCADA.
    monkeypatch.setattr(spice, 'list_datasets', lambda c: [d for d in list_datasets(c) if d['name'] == MOCK_OBJECT])
    c = env.client("t_admin1")
    base = f"/api/v2/workspaces/{env.ws1}/connections"
    r = c.post(base, json={"name": "live", "kind": "rest", "base_url": LIVE["base_url"]})
    assert r.status_code == 201, r.text
    return c, f"{base}/{r.json()['id']}"


@pytest.fixture()
def source_slot():
    """Shared PG capacity is external contention, not a precision/error-sanitizing failure.

    Retry only Busy for up to ten seconds; always release our exact lease in finally.
    This fixture never retries SQL/source errors and never holds a slot during REST/API calls.
    """
    @contextmanager
    def slot():
        deadline = time.monotonic() + 10
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                pytest.skip('SPICE lease pool remained busy for 10 s')
            try:
                lid = limiter.acquire('spice', wait_s=min(2, remaining))
                break
            except limiter.Busy:
                time.sleep(min(0.05, max(0, deadline - time.monotonic())))
        try:
            yield
        finally:
            limiter.release(lid)
    return slot


def test_live_slot_helper_retries_busy_and_releases_on_source_error(source_slot, monkeypatch):
    attempts, released = [], []
    def acquire(pool, ttl_s=30, wait_s=None):
        attempts.append(pool)
        if len(attempts) < 3: raise limiter.Busy()
        return 'test-lease'
    monkeypatch.setattr(limiter, 'acquire', acquire)
    monkeypatch.setattr(limiter, 'release', released.append)
    with pytest.raises(spice.SpiceError):
        with source_slot():
            raise spice.SpiceError('rejected')
    assert attempts == ['spice'] * 3 and released == ['test-lease']


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
    assert MOCK_OBJECT in names
    assert c.get(url + "/catalog").json()["objects"] == {}                       # visible only once allow-listed

    body = {"object": MOCK_OBJECT, "limit": 5}
    r = c.post(url + "/preview", json=body)
    assert r.status_code == 403                                                 # not allow-listed yet
    assert c.put(url + "/allowed-objects", json={"objects": [MOCK_OBJECT]}).status_code == 200
    cat = c.get(url + "/catalog").json()["objects"][MOCK_OBJECT]["columns"]
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
    c.put(url + "/allowed-objects", json={"objects": [MOCK_OBJECT]})
    col = c.get(url + "/catalog").json()["objects"][MOCK_OBJECT]["columns"][0]
    for bad in ({"object": MOCK_OBJECT + "; drop table x"}, {"object": "other_table"}, {"object": "pg_catalog.pg_user"}):
        assert c.post(url + "/preview", json=bad).status_code in (403, 422), bad
    assert c.post(url + "/preview", json={"object": MOCK_OBJECT, "columns": ['x" FROM y --']}).status_code == 422
    assert c.post(url + "/preview", json={"object": MOCK_OBJECT, "columns": ["nope"]}).status_code == 422
    assert c.post(url + "/preview", json={"object": MOCK_OBJECT, "limit": 100000}).status_code == 422
    f = {"column": col["name"], "op": "=", "value": "x'; DROP TABLE t; --"}
    r = c.post(url + "/preview", json={"object": MOCK_OBJECT, "filters": [f]})
    assert r.status_code in (200, 422)                                          # escaped literal or type mismatch, never executed
    assert c.post(url + "/preview", json={"object": MOCK_OBJECT, "filters": [{**f, "op": "LIKE"}]}).status_code == 422


@live
def test_preview_permissions_and_isolation(env, conn):
    c, url = conn
    assert env.client("t_viewer1").post(url + "/preview", json={"object": MOCK_OBJECT}).status_code == 403
    assert env.client("t_viewer1").post(url + "/test").status_code == 403
    other = url.replace(str(env.ws1), str(env.ws2))
    assert env.client("t_admin2").post(other + "/test").status_code == 404


@live
def test_flight_budgets_stop_early_without_reading_everything(source_slot):
    with source_slot():
        t = time.perf_counter()
        cols, rows, truncated = spice.run_bounded(LIVE, "SELECT * FROM generate_series(1, 2000000)", max_rows=10)
        assert len(rows) == 10 and truncated and time.perf_counter() - t < 3
        cols, rows, truncated = spice.run_bounded(LIVE, "SELECT * FROM generate_series(1, 2000000)", max_rows=1000, max_bytes=50_000)
    assert truncated and len(rows) < 1000 + 8192


@live
def test_exact_numbers_survive(source_slot):
    with source_slot():
        cols, rows, _ = spice.run_bounded(LIVE, "SELECT CAST('123456789012345678.1234567890' AS DECIMAL(38,10)) AS d,"
                                                " CAST(9007199254740993 AS BIGINT) AS i", max_rows=1)
    assert rows[0] == ["123456789012345678.1234567890", "9007199254740993"]


@live
def test_errors_never_leak_source_text(env, conn, source_slot):
    c, url = conn
    with source_slot():
        with pytest.raises(spice.SpiceError) as e:
            spice.run_bounded(LIVE, "SELECT * FROM no_such_table_zz", max_rows=1)
    assert e.value.code == 'rejected'  # Busy must not masquerade as the expected SQL-rejection path.
    assert "spice.public" not in str(e.value) and "no_such_table_zz" not in str(e.value)
    assert json.dumps(c.post(url + "/test").json()).count("spice.public") == 0


def test_preview_works_for_sources_that_reject_limit_pushdown(fake_catalog, monkeypatch):
    # MOCKED: retain the LIMIT-rejection regression without accessing a real SCADA table.
    c, url = fake_catalog
    def read(_, sql, **kw):
        if ' LIMIT ' in sql: raise spice.SpiceError('rejected')
        return [{'name': 'id', 'type': 'Int64'}], [[1], [2], [3]], True
    monkeypatch.setattr(spice, 'run_bounded', read)
    r = c.post(url + "/preview", json={"object": "alarm", "limit": 3})
    assert r.status_code == 200, r.text
    assert len(r.json()["rows"]) == 3 and r.json()["truncated"] is True


def test_secret_resolution_refuses_non_spice_settings(monkeypatch):
    monkeypatch.setenv("UETL_APP_PASSWORD", "canary-value")
    monkeypatch.setenv("SPICE_TEST_TOKEN", "ok-token")
    assert spice._token({"secret_ref": "UETL_APP_PASSWORD"}) is None
    assert spice._token({"secret_ref": "SPICE_TEST_TOKEN"}) == "ok-token"


def test_list_datasets_returns_kind_without_source_path(monkeypatch):
    monkeypatch.setattr(spice, "_rest", lambda *a: json.dumps([
        {"name": "pg_table", "from": 'postgres:"secret_schema"."secret_table"'},
        {"name": "alarm", "from": "odbc:private.db.path"},
        {"name": "file_table", "from": "file:/private/path"},
        {"name": "bad;name", "from": "odbc:private"},
    ]).encode())
    assert spice.list_datasets(LIVE) == [
        {"name": "alarm", "kind": "odbc"}, {"name": "file_table", "kind": "other"},
        {"name": "pg_table", "kind": "postgres"}]


def test_refresh_stores_kind_and_hides_from_string(env, conn, monkeypatch):
    c, url = conn
    monkeypatch.setattr(spice, "list_datasets", lambda _: [{"name": "alarm", "kind": "odbc"}])
    monkeypatch.setattr(spice, "describe", lambda *_: [{"name": "id", "type": "Int64", "nullable": False}])
    assert c.post(url + "/catalog/refresh").status_code == 200
    c.put(url + "/allowed-objects", json={"objects": ["alarm"]})
    obj = c.get(url + "/catalog").json()["objects"]["alarm"]
    assert obj["kind"] == "odbc" and obj["limit_pushdown"] is None
    cid = url.split("/")[-1]
    env.cur.execute("update catalog_snapshot set payload=jsonb_set(payload,'{objects,alarm,limit_pushdown}','false')"
                    " where connection_id=%s", (cid,))
    assert c.post(url + "/catalog/refresh").status_code == 200
    assert c.get(url + "/catalog").json()["objects"]["alarm"]["limit_pushdown"] is False
    for path in ("/catalog", "/catalog/all"):
        assert '"from"' not in c.get(url + path).text


@pytest.fixture()
def fake_catalog(conn, monkeypatch):
    c, url = conn
    monkeypatch.setattr(spice, "list_datasets", lambda _: [{"name": "alarm", "kind": "odbc"}])
    monkeypatch.setattr(spice, "describe", lambda *_: [{"name": "id", "type": "Int64", "nullable": False}])
    assert c.post(url + "/catalog/refresh").status_code == 200
    assert c.put(url + "/allowed-objects", json={"objects": ["alarm"]}).status_code == 200
    return c, url


def test_odbc_dataset_preview_takes_the_odbc_pool(fake_catalog, monkeypatch):
    c, url = fake_catalog
    pools = []
    acquire = limiter.acquire
    def take(pool, ttl_s=30):
        pools.append(pool)
        return acquire(pool, ttl_s)
    monkeypatch.setattr(limiter, "acquire", take)
    monkeypatch.setattr(spice, "run_bounded", lambda *a, **kw: ([{"name": "id", "type": "Int64"}], [[1]], False))
    r = c.post(url + "/preview", json={"object": "alarm"})
    assert r.status_code == 200 and r.json()["limit_applied"] is True
    assert pools == ["odbc"]


def test_busy_returns_429_with_retry_after(env, fake_catalog, monkeypatch):
    c, url = fake_catalog
    def busy(*a, **kw):
        raise limiter.Busy(3)
    monkeypatch.setattr(limiter, "acquire", busy)
    r = c.post(url + "/preview", json={"object": "alarm"})
    assert r.status_code == 429 and r.headers["Retry-After"] == "3"
    env.cur.execute("select outcome,detail from audit_event where workspace_id=%s and action='preview.run' order by id desc limit 1", (env.ws1,))
    row = env.cur.fetchone()
    assert row["outcome"] == "deny" and row["detail"]["reason"] == "busy"


def test_limit_less_retry_happens_once_per_dataset(fake_catalog, monkeypatch):
    c, url = fake_catalog
    statements = []
    def read(_, sql, **kw):
        statements.append(sql)
        if " LIMIT " in sql:
            raise spice.SpiceError("rejected")
        return [{"name": "id", "type": "Int64"}], [[1]], True
    monkeypatch.setattr(spice, "run_bounded", read)
    assert c.post(url + "/preview", json={"object": "alarm"}).json()["limit_applied"] is False
    assert c.get(url + "/catalog").json()["objects"]["alarm"]["limit_pushdown"] is False
    assert c.post(url + "/preview", json={"object": "alarm"}).status_code == 200
    assert len(statements) == 3 and "LIMIT" not in statements[-1]


def test_lease_released_after_error(fake_catalog, monkeypatch):
    c, url = fake_catalog
    def fail(*a, **kw):
        raise spice.SpiceError("timeout")
    monkeypatch.setattr(spice, "run_bounded", fail)
    assert c.post(url + "/preview", json={"object": "alarm"}).status_code == 504
    lid = limiter.acquire("odbc")
    limiter.release(lid)


def test_backslash_filter_is_422_before_source_read(fake_catalog, monkeypatch):
    c, url = fake_catalog
    def text_columns(*_): return [{'name': 'text', 'type': 'Utf8', 'nullable': True}]
    monkeypatch.setattr(spice, 'describe', text_columns)
    assert c.post(url + '/catalog/refresh').status_code == 200
    def forbidden_read(*a, **kw):
        pytest.fail('invalid filter must never reach SPICE')
    monkeypatch.setattr(spice, 'run_bounded', forbidden_read)
    response = c.post(url + '/preview', json={'object': 'alarm', 'filters': [
        {'column': 'text', 'op': '=', 'value': "x\\'; DROP TABLE t; --"}]})
    assert response.status_code == 422


def test_preview_time_budget_is_enforced(monkeypatch):
    import pyarrow.flight as fl
    budgets = []
    class Client:
        def __init__(self, *_): pass
        def get_flight_info(self, _, options):
            budgets.append(options.timeout)
            time.sleep(0.05)
            return type("Info", (), {"endpoints": [type("Endpoint", (), {"ticket": None})()]})()
        def do_get(self, _, options):
            budgets.append(options.timeout)
            raise fl.FlightTimedOutError("controlled timeout")
        def close(self): pass
    monkeypatch.setattr(fl, "FlightClient", Client)
    monkeypatch.setattr(spice, "flight_endpoint", lambda _: ("127.0.0.1", 50051))
    start = time.perf_counter()
    with pytest.raises(spice.SpiceError) as ex:
        with limiter.lease("odbc"):
            spice.run_bounded(LIVE, 'SELECT 1', max_seconds=1)
    assert ex.value.code == "timeout" and time.perf_counter() - start < 3
    assert 0 < budgets[1] < budgets[0] <= 1
    lid = limiter.acquire("odbc")
    limiter.release(lid)


def test_byte_budget_never_returns_an_oversized_row(monkeypatch):
    import pyarrow as pa
    import pyarrow.flight as fl
    batch = pa.record_batch([pa.array(["x" * 2000])], names=["text"])
    class Reader:
        schema = batch.schema
        def read_chunk(self): return type("Chunk", (), {"data": batch})()
        def cancel(self): pass
    class Client:
        def __init__(self, *_): pass
        def get_flight_info(self, *a):
            return type("Info", (), {"endpoints": [type("Endpoint", (), {"ticket": None})()]})()
        def do_get(self, *a): return Reader()
        def close(self): pass
    monkeypatch.setattr(fl, "FlightClient", Client)
    monkeypatch.setattr(spice, "flight_endpoint", lambda _: ("127.0.0.1", 50051))
    _, rows, truncated = spice.run_bounded(LIVE, 'SELECT 1', max_bytes=100)
    assert rows == [] and truncated


def test_js_safe_integer_boundary_is_a_string():
    assert spice._jsonable(2**53 - 1) == 2**53 - 1
    assert spice._jsonable(2**53) == str(2**53)


def test_arrow_dates_outside_python_range_keep_their_iso_text():
    import pyarrow as pa
    values = pa.array([0, -719528], type=pa.int32()).cast(pa.date32())
    assert spice._arrow_jsonable(values, 0) == "1970-01-01"
    assert spice._arrow_jsonable(values, 1) == "0000-01-01"


def test_row_budget_stops_at_exact_batch_boundary_without_another_read(monkeypatch):
    import pyarrow as pa
    import pyarrow.flight as fl
    batch = pa.record_batch([pa.array([1, 2])], names=['id'])
    class Reader:
        schema = batch.schema
        reads = 0
        cancelled = False
        def read_chunk(self):
            self.reads += 1
            if self.reads > 1: raise fl.FlightUnavailableError('end of stream after budget')
            return type('Chunk', (), {'data': batch})()
        def cancel(self): self.cancelled = True
    reader = Reader()
    class Client:
        def __init__(self, *_): pass
        def get_flight_info(self, *a):
            return type('Info', (), {'endpoints': [type('Endpoint', (), {'ticket': None})()]})()
        def do_get(self, *a): return reader
        def close(self): pass
    monkeypatch.setattr(fl, 'FlightClient', Client)
    monkeypatch.setattr(spice, 'flight_endpoint', lambda _: ('127.0.0.1', 50051))
    _, rows, truncated = spice.run_bounded(LIVE, 'SELECT 1', max_rows=2)
    assert rows == [[1], [2]] and truncated
    assert reader.reads == 1 and reader.cancelled


def test_unlearned_spice_dataset_holds_cross_process_learning_lock(env, fake_catalog, monkeypatch):
    from backend.v2 import db as database
    c, url = fake_catalog
    cid = url.split('/')[-1]
    env.cur.execute("update catalog_snapshot set payload=jsonb_set(payload,'{objects,alarm,kind}','\"other\"') where connection_id=%s", (cid,))
    observations = []
    def read(_, sql, **kw):
        pool = database._get_pool(); probe = pool.getconn()
        try:
            with probe.cursor() as cur:
                cur.execute('select pg_try_advisory_xact_lock(197006,hashtext(%s)) as acquired', (cid + ':alarm',))
                observations.append(cur.fetchone()['acquired'])
        finally:
            probe.rollback(); pool.putconn(probe)
        if ' LIMIT ' in sql: raise spice.SpiceError('rejected')
        return [], [], False
    monkeypatch.setattr(spice, 'run_bounded', read)
    assert c.post(url + '/preview', json={'object': 'alarm'}).status_code == 200
    assert observations == [False, False]


def test_limit_learning_cannot_overwrite_a_refreshed_source_identity(env, fake_catalog, monkeypatch):
    c, url = fake_catalog
    cid = url.split('/')[-1]
    def read(_, sql, **kw):
        if ' LIMIT ' in sql: raise spice.SpiceError('rejected')
        env.cur.execute("insert into catalog_snapshot(connection_id,revision,payload) values (%s,2,%s)",
            (cid, json.dumps({'objects': {'alarm': {'kind': 'postgres', 'columns': [{'name': 'id', 'type': 'Int64'}], 'limit_pushdown': None}}})))
        return [], [], False
    monkeypatch.setattr(spice, 'run_bounded', read)
    assert c.post(url + '/preview', json={'object': 'alarm'}).status_code == 200
    obj = c.get(url + '/catalog').json()['objects']['alarm']
    assert obj['kind'] == 'postgres' and obj['limit_pushdown'] is None


@pytest.mark.parametrize('policy', [None, True, False])
def test_learning_contention_is_busy_but_known_limitless_reads_stay_concurrent(env, fake_catalog, monkeypatch, policy):
    from backend.v2 import db as database
    c, url = fake_catalog
    cid = url.split('/')[-1]
    env.cur.execute("update catalog_snapshot set payload=jsonb_set(jsonb_set(payload,'{objects,alarm,kind}','\"other\"'),'{objects,alarm,limit_pushdown}',%s) where connection_id=%s", (json.dumps(policy), cid))
    calls = []
    def read(_, sql, **kw):
        calls.append(sql)
        if ' LIMIT ' in sql: raise spice.SpiceError('rejected')
        return [], [], False
    monkeypatch.setattr(spice, 'run_bounded', read)
    pool = database._get_pool(); blocker = pool.getconn()
    try:
        with blocker.cursor() as cur:
            cur.execute('select pg_advisory_xact_lock(197006,hashtext(%s))', (cid + ':alarm',))
        response = c.post(url + '/preview', json={'object': 'alarm'})
        if policy is False:
            assert response.status_code == 200 and len(calls) == 1
        else:
            assert response.status_code == 429 and response.headers['Retry-After'] == '1'
            assert len(calls) == (1 if policy else 0)
    finally:
        blocker.rollback(); pool.putconn(blocker)
