"""Best-effort structured source metrics. Raw source text/SQL/secrets have no storage field."""
import datetime
import logging
import re
import uuid
from typing import Literal

import psycopg2
from fastapi import APIRouter, Depends, HTTPException, Query

from . import db as database

Kind = Literal['queue_wait', 'busy_429', 'timeout', 'read_ok', 'read_error']
KINDS = {'queue_wait', 'busy_429', 'timeout', 'read_ok', 'read_error'}
DATASET = r'^[A-Za-z0-9_]+(\.[A-Za-z0-9_]+){0,2}$'
FIELDS = 'id,at,kind,workspace_id,connection_id,dataset,user_id,waited_ms,rows,bytes'
log = logging.getLogger('uetl.activity')


def _insert(cur, values):
    cur.execute('insert into source_event(kind,workspace_id,connection_id,dataset,user_id,waited_ms,rows,bytes)'
                ' values (%s,%s,%s,%s,%s,%s,%s,%s)', values)


def record(kind: Kind, *, workspace_id, connection_id, dataset=None, user_id=None,
           waited_ms=None, rows=None, bytes=None, db=None):
    """Never throw for invalid metrics, missing migration, DB/logging capacity or insert failure.

    Request callers use their own transaction via a savepoint. Standalone callers borrow a
    short-lived app connection. Events deliberately keep UUIDs after an entity is deleted.
    """
    pool, connection, owned = None, db, db is None
    try:
        if kind not in KINDS or (dataset is not None and (not isinstance(dataset, str) or len(dataset) > 200 or not re.fullmatch(DATASET, dataset))):
            return False
        identifiers = [uuid.UUID(str(value)) if value is not None else None for value in (workspace_id, connection_id, user_id)]
        if identifiers[0] is None or identifiers[1] is None:
            return False
        if any(value is not None and (type(value) is not int or not 0 <= value < 2**63) for value in (waited_ms, rows, bytes)):
            return False
        if owned:
            pool = database._get_pool()
            connection = pool.getconn()
        with connection.cursor() as cur:
            cur.execute('savepoint source_activity_write')
            try:
                cur.execute("select current_setting('statement_timeout') as statement_timeout, current_setting('lock_timeout') as lock_timeout")
                previous = cur.fetchone()
                previous = (previous['statement_timeout'], previous['lock_timeout']) if isinstance(previous, dict) else previous
                cur.execute("select set_config('statement_timeout','250ms',true),set_config('lock_timeout','100ms',true)")
                _insert(cur, (kind, identifiers[0], identifiers[1], dataset, identifiers[2], waited_ms, rows, bytes))
                cur.execute("select set_config('statement_timeout',%s,true),set_config('lock_timeout',%s,true)", previous)
            except Exception:
                cur.execute('rollback to savepoint source_activity_write')
                raise
            finally:
                cur.execute('release savepoint source_activity_write')
        if owned:
            connection.commit()
        return True
    except Exception as error:
        if owned and connection is not None:
            try: connection.rollback()
            except Exception: pass
        try: log.warning('Source activity write unavailable (%s)', type(error).__name__)
        except Exception: pass
        return False
    finally:
        if owned and pool is not None and connection is not None:
            try: pool.putconn(connection)
            except Exception: pass


def build(workspace_access, DB):
    router = APIRouter()

    @router.get('/api/v2/workspaces/{workspace_id}/source-activity')
    def source_activity(since: datetime.datetime | None = None, kind: Kind | None = None,
                        dataset: str | None = Query(default=None, pattern=DATASET, max_length=200),
                        cursor: int | None = Query(default=None, ge=1, le=2**63 - 1),
                        limit: int = Query(default=100, ge=1, le=500),
                        ctx=Depends(workspace_access('connection.read')), db=DB):
        clauses, values = ['workspace_id=%s'], [ctx['workspace_id']]
        for condition, value in [('at>=%s', since), ('kind=%s', kind), ('dataset=%s', dataset), ('id<%s', cursor)]:
            if value is not None:
                clauses.append(condition); values.append(value)
        try:
            with db.cursor() as cur:
                cur.execute('select ' + FIELDS + ' from source_event where ' + ' and '.join(clauses)
                            + ' order by id desc limit %s', (*values, limit + 1))
                found = cur.fetchall()
        except psycopg2.Error:
            raise HTTPException(503, 'Source activity is not available yet') from None
        items = []
        for row in found[:limit]:
            items.append({key: str(value) if value is not None and (isinstance(value, (int, uuid.UUID))) else value
                          for key, value in row.items()})
        return {'items': items, 'next_cursor': str(found[limit - 1]['id']) if len(found) > limit else None}

    return router
