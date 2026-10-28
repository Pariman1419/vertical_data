"""ISOLATED local PG migrations/API; source reads are MOCKED, never real/SCADA."""
import datetime
import json
import uuid

import psycopg2
import pytest

from local_pg import ROOT, postgres
from test_api import env  # noqa: F401
from backend.v2 import activity, db, limiter, spice


@pytest.fixture(scope='module')
def isolated_pg():
    with postgres() as settings:
        yield settings


@pytest.fixture()
def local_config(isolated_pg, monkeypatch):
    for key, value in {'UETL_PG_HOST': '127.0.0.1', 'UETL_PG_PORT': str(isolated_pg['port']),
                       'UETL_PG_DB': 'activity_fixture', 'UETL_APP_PASSWORD': 'fixture-only'}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(db, '_pool', None)
    monkeypatch.setattr(limiter, '_pool', None)
    yield
    if db._pool: db._pool.closeall()
    if limiter._pool: limiter._pool.closeall()


@pytest.fixture()
def activity_env(local_config, env, monkeypatch):
    client = env.client('t_admin1')
    base = f'/api/v2/workspaces/{env.ws1}/connections'
    response = client.post(base, json={'name': 'fixture', 'kind': 'rest', 'base_url': 'http://10.153.90.17:8091'})
    assert response.status_code == 201
    cid = response.json()['id']
    monkeypatch.setattr(spice, 'list_datasets', lambda _: [{'name': 'sample_mock', 'kind': 'postgres'}])
    monkeypatch.setattr(spice, 'describe', lambda *_: [{'name': 'id', 'type': 'Int64', 'nullable': False}])
    assert client.post(base + '/' + cid + '/catalog/refresh').status_code == 200
    assert client.put(base + '/' + cid + '/allowed-objects', json={'objects': ['sample_mock']}).status_code == 200
    return env, client, base + '/' + cid, cid


def events(env):
    env.cur.execute('select * from source_event where workspace_id=%s order by id', (env.ws1,))
    return env.cur.fetchall()


def test_busy_emits_one_scoped_busy_event_and_wait_time(activity_env, monkeypatch):
    env, client, connection, cid = activity_env
    def busy(*a, **kw): raise limiter.Busy(3)
    monkeypatch.setattr(limiter, 'acquire', busy)
    response = client.post(connection + '/preview', json={'object': 'sample_mock'})
    assert response.status_code == 429 and response.headers['Retry-After'] == '3'
    rows = [e for e in events(env) if e['kind'] == 'busy_429']
    assert len(rows) == 1 and str(rows[0]['connection_id']) == cid
    assert rows[0]['dataset'] == 'sample_mock' and rows[0]['user_id'] == env.admin1
    assert rows[0]['waited_ms'] >= 0
    assert len([e for e in events(env) if e['kind'] == 'queue_wait']) == 1


@pytest.mark.parametrize('code,expected,status', [(None, 'read_ok', 200), ('timeout', 'timeout', 504), ('rejected', 'read_error', 502), ('busy', 'busy_429', 429)])
def test_outcomes_have_only_safe_metrics(activity_env, monkeypatch, code, expected, status):
    env, client, connection, cid = activity_env
    canary = 'raw SQL SELECT private_table; token=never-store-this'
    def read(*a, **kw):
        if code: raise spice.SpiceError(code, canary)
        return [{'name': 'id', 'type': 'Int64'}], [['9007199254740993']], False
    monkeypatch.setattr(spice, 'run_bounded', read)
    assert client.post(connection + '/preview', json={'object': 'sample_mock'}).status_code == status
    stored = [e for e in events(env) if e['kind'] == expected]
    assert len(stored) == 1
    assert canary not in json.dumps(stored, default=str)
    response = client.get(f'/api/v2/workspaces/{env.ws1}/source-activity')
    assert response.status_code == 200
    assert canary not in response.text and 'private_table' not in response.text and 'never-store-this' not in response.text
    assert all(set(e) == {'id', 'at', 'kind', 'workspace_id', 'connection_id', 'dataset', 'user_id', 'waited_ms', 'rows', 'bytes'} for e in response.json()['items'])
    if not code:
        assert stored[0]['rows'] == 1 and stored[0]['bytes'] > 0


@pytest.mark.parametrize('code,status,outcome', [(None, 200, 'allow'), ('timeout', 504, 'error'), ('rejected', 502, 'error'), ('busy', 429, 'deny')])
def test_logging_failure_does_not_fail_preview_or_abort_request_transaction(activity_env, monkeypatch, code, status, outcome):
    env, client, connection, _ = activity_env
    # Inject a real PostgreSQL statement error; the savepoint must preserve later writes.
    def broken_insert(cur, values): cur.execute('select 1/0')
    monkeypatch.setattr(activity, '_insert', broken_insert)
    def read(*a, **kw):
        if code: raise spice.SpiceError(code)
        return [], [], False
    monkeypatch.setattr(spice, 'run_bounded', read)
    if code == 'busy':
        def busy(*a, **kw): raise limiter.Busy(2)
        monkeypatch.setattr(limiter, 'acquire', busy)
    response = client.post(connection + '/preview', json={'object': 'sample_mock'})
    assert response.status_code == status
    env.cur.execute("select count(*) as n from audit_event where workspace_id=%s and action='preview.run' and outcome=%s", (env.ws1, outcome))
    assert env.cur.fetchone()['n'] == 1


def test_workspace_isolation_and_keyset_filters(activity_env):
    env, client, _, cid = activity_env
    for kind in ('queue_wait', 'read_ok', 'timeout'):
        assert activity.record(kind, workspace_id=env.ws1, connection_id=cid, dataset='sample_mock',
            user_id=env.admin1, waited_ms=10, rows=1, bytes=20, db=env.cur.connection)
    url = f'/api/v2/workspaces/{env.ws1}/source-activity'
    assert env.client('t_admin2').get(url).status_code == 404
    assert env.client('t_viewer1').get(url).status_code == 200
    response = client.get(url, params={'limit': 2}).json()
    assert len(response['items']) == 2 and response['next_cursor']
    older = client.get(url, params={'limit': 2, 'cursor': response['next_cursor']}).json()
    assert len(older['items']) == 1
    assert set(e['id'] for e in response['items']).isdisjoint(e['id'] for e in older['items'])
    filtered = client.get(url, params={'kind': 'timeout', 'dataset': 'sample_mock'}).json()
    assert [e['kind'] for e in filtered['items']] == ['timeout']
    future = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=1)
    assert client.get(url, params={'since': future.isoformat()}).json()['items'] == []
    assert client.get(url, params={'limit': 501}).status_code == 422
    assert client.get(url, params={'dataset': "x'; SELECT token"}).status_code == 422


def test_append_only_and_retention_remove_only_expired_rows(activity_env):
    from backend.v2 import reaper
    env, client, _, cid = activity_env
    for age in (31, 29, 0):
        env.cur.execute("insert into source_event(workspace_id,connection_id,user_id,dataset,kind,at) values (%s,%s,%s,'sample_mock','read_ok',clock_timestamp()-make_interval(days=>%s))", (env.ws1, cid, env.admin1, age))
    for statement in ('update source_event set rows=2', 'delete from source_event', 'truncate source_event'):
        env.cur.execute('savepoint guard_check')
        with pytest.raises(psycopg2.Error): env.cur.execute(statement)
        env.cur.execute('rollback to savepoint guard_check')
        env.cur.execute('release savepoint guard_check')
    assert reaper.prune_source_events(env.cur.connection) == 1
    assert len(events(env)) == 2


def test_record_rejects_unstructured_secrets_without_poisoning_transaction(activity_env):
    env, _, _, cid = activity_env
    for kind, dataset in [('raw SQL SELECT token', 'sample_mock'), ('read_ok', 'token=canary'), ('read_error', 'SELECT secret FROM table')]:
        assert activity.record(kind, workspace_id=env.ws1, connection_id=cid, dataset=dataset,
            user_id=env.admin1, waited_ms=0, rows=None, bytes=None, db=env.cur.connection) is False
    assert events(env) == []


def test_migration_down_up_isolated_and_permissions(isolated_pg):
    assert isolated_pg['host'] == '127.0.0.1' and isolated_pg['dbname'] == 'activity_fixture'
    with psycopg2.connect(**isolated_pg, options='-c search_path=uetl_meta') as connection:
        with connection.cursor() as cur:
            cur.execute((ROOT / 'backend/migrations/0006_activity.down.sql').read_text())
            cur.execute("select to_regclass('source_event')")
            assert cur.fetchone()[0] is None
            cur.execute((ROOT / 'backend/migrations/0006_activity.up.sql').read_text())
            cur.execute("select has_table_privilege('uetl_app','source_event','INSERT'), has_table_privilege('uetl_app','source_event','UPDATE'), has_table_privilege('uetl_app','source_event','DELETE')")
            assert cur.fetchone() == (True, False, False)


def test_append_only_trigger_also_protects_unexpired_rows_from_table_owner(isolated_pg):
    connection = psycopg2.connect(**isolated_pg, options='-c search_path=uetl_meta')
    try:
        with connection.cursor() as cur:
            cur.execute("insert into source_event(workspace_id,connection_id,kind) values (%s,%s,'read_ok')", (uuid.uuid4(), uuid.uuid4()))
            for statement in ('update source_event set rows=2', 'delete from source_event', 'truncate source_event'):
                cur.execute('savepoint owner_guard')
                with pytest.raises(psycopg2.errors.InsufficientPrivilege): cur.execute(statement)
                cur.execute('rollback to savepoint owner_guard')
                cur.execute('release savepoint owner_guard')
    finally:
        connection.rollback(); connection.close()


def test_page_size_is_capped_and_large_metrics_stay_exact(activity_env):
    env, client, _, cid = activity_env
    env.cur.execute("insert into source_event(workspace_id,connection_id,dataset,kind,rows,bytes)"
                    " select %s,%s,'sample_mock','read_ok',9007199254740993,9223372036854775807 from generate_series(1,501)", (env.ws1, cid))
    url = f'/api/v2/workspaces/{env.ws1}/source-activity'
    page = client.get(url, params={'limit': 500}).json()
    assert len(page['items']) == 500 and isinstance(page['next_cursor'], str)
    assert page['items'][0]['rows'] == '9007199254740993'
    assert page['items'][0]['bytes'] == '9223372036854775807'
    assert len(client.get(url, params={'limit': 500, 'cursor': page['next_cursor']}).json()['items']) == 1
