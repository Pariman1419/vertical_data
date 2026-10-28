"""Cross-process source capacity. A crashed caller loses its slot after the TTL."""
import logging
import math
import random
import threading
import time
from contextlib import contextmanager

import psycopg2
from psycopg2.pool import PoolError, ThreadedConnectionPool

from . import config

CAPS = {"spice": max(1, int(config.get("UETL_SPICE_CONCURRENCY", "2"))), "odbc": 1}
_pool = None
_init_lock = threading.Lock()
log = logging.getLogger("uetl.limiter")


class Busy(Exception):
    def __init__(self, retry_after=1):
        super().__init__("Source capacity is busy")
        self.retry_after = max(1, math.ceil(retry_after))


def _get_pool():
    global _pool
    with _init_lock:
        if _pool is None:
            _pool = ThreadedConnectionPool(
                1, 4, host=config.get("UETL_PG_HOST"), port=config.get("UETL_PG_PORT", "5432"),
                dbname=config.get("UETL_PG_DB"), user="uetl_app", password=config.get("UETL_APP_PASSWORD"),
                connect_timeout=2, application_name="uetl-source-leases",
                options="-c search_path=uetl_meta -c statement_timeout=750 -c lock_timeout=250")
    return _pool


@contextmanager
def _transaction():
    try:
        pool = _get_pool()
        conn = pool.getconn()
    except (PoolError, psycopg2.OperationalError):
        raise Busy() from None
    try:
        with conn:
            with conn.cursor() as cur:
                yield cur
    except (psycopg2.errors.LockNotAvailable, psycopg2.errors.QueryCanceled):
        raise Busy() from None
    finally:
        pool.putconn(conn)


def acquire(pool: str, ttl_s: int = 30, wait_s: float | None = None):
    if pool not in CAPS:
        raise ValueError("Unknown source pool")
    if type(ttl_s) is not int or ttl_s < 1:
        raise ValueError("TTL must be a positive integer")
    if wait_s is None:
        wait_s = float(config.get('UETL_LIMITER_WAIT_S', '2.0'))
    if type(wait_s) not in (int, float) or not math.isfinite(wait_s) or wait_s < 0:
        raise ValueError('Wait must be a finite nonnegative number')
    deadline = time.monotonic() + wait_s
    while True:
        try:
            return _acquire_once(pool, ttl_s)
        except Busy:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise
            time.sleep(min(remaining, random.uniform(0.05, 0.1)))
            if time.monotonic() >= deadline:
                raise


def _acquire_once(pool, ttl_s):
    with _transaction() as cur:
        # Namespace the lock to avoid colliding with unrelated users of the shared DB.
        cur.execute("select pg_try_advisory_xact_lock(197004, hashtext(%s))", (pool,))
        if not cur.fetchone()[0]:
            raise Busy()
        cur.execute("delete from source_lease where pool=%s and expires_at <= clock_timestamp()", (pool,))
        cur.execute("select count(*), extract(epoch from min(expires_at)-clock_timestamp())"
                    " from source_lease where pool=%s", (pool,))
        count, remaining = cur.fetchone()
        if count >= CAPS[pool]:
            raise Busy(float(remaining or 1))
        cur.execute("insert into source_lease(pool,expires_at)"
                    " values (%s,clock_timestamp()+make_interval(secs => %s)) returning id", (pool, ttl_s))
        lid = cur.fetchone()[0]
    return lid


def release(lease_id):
    with _transaction() as cur:
        cur.execute("delete from source_lease where id=%s", (lease_id,))


@contextmanager
def lease(pool: str, ttl_s: int = 30, on_wait=None):
    started = time.monotonic()
    try:
        lid = acquire(pool, ttl_s)
    finally:
        if on_wait is not None:
            try:
                on_wait(max(0, math.ceil((time.monotonic() - started) * 1000)))
            except Exception as error:
                log.warning('Source wait observer unavailable (%s)', type(error).__name__)
    try:
        yield lid
    finally:
        try:
            release(lid)
        except (Busy, psycopg2.Error) as error:
            # Capacity remains reserved until TTL; never replace a completed read or its error.
            log.warning("Source lease cleanup deferred to TTL (%s)", type(error).__name__)
