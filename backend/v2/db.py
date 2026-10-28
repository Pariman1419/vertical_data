"""PostgreSQL access for the API. Always connects as uetl_app (DML only, no DDL)."""
import threading

import psycopg2
import psycopg2.extras
import psycopg2.pool

from . import config

psycopg2.extras.register_uuid()  # adapt uuid.UUID path parameters

_pool = None
_init_lock = threading.Lock()


def _get_pool():
    global _pool
    with _init_lock:
        if _pool is None:
            _pool = psycopg2.pool.ThreadedConnectionPool(
                1, 16, host=config.get("UETL_PG_HOST"), port=config.get("UETL_PG_PORT", "5432"),
                dbname=config.get("UETL_PG_DB"), user="uetl_app", password=config.get("UETL_APP_PASSWORD"),
                connect_timeout=5, application_name="uetl-api", options="-c search_path=uetl_meta",
                cursor_factory=psycopg2.extras.RealDictCursor)
    return _pool


def get_db():
    """FastAPI dependency: one transaction per request, committed on success."""
    pool = _get_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


def ping():
    pool = _get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute("select 1")
        conn.rollback()
    finally:
        pool.putconn(conn)
