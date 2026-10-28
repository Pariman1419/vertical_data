"""Real PostgreSQL lease races; every acquired lease is removed in fixture teardown."""
import concurrent.futures
import threading
import time

import pytest

from backend.v2 import limiter


@pytest.fixture()
def leases():
    acquired = []
    def take(pool="odbc", ttl_s=30):
        lid = limiter.acquire(pool, ttl_s)
        acquired.append(lid)
        return lid
    yield take
    for lid in acquired:
        limiter.release(lid)


def test_cap_is_enforced(leases):
    for _ in range(limiter.CAPS["odbc"]):
        leases()
    with pytest.raises(limiter.Busy) as ex:
        leases()
    assert ex.value.retry_after >= 1


def test_release_frees_slot(leases):
    limiter.release(leases())
    assert leases()


def test_expired_lease_is_reclaimed(leases):
    leases(ttl_s=1)
    time.sleep(1.2)
    assert leases()


def test_pools_are_independent(leases):
    leases("odbc")
    assert leases("spice")


def test_concurrent_acquire_one_winner(leases):
    barrier = threading.Barrier(8)
    def race(_):
        barrier.wait()
        try:
            leases()
            return True
        except limiter.Busy:
            return False
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        assert sum(executor.map(race, range(8))) == 1


def test_unknown_pool_rejected():
    with pytest.raises(ValueError):
        limiter.acquire("unknown")


@pytest.mark.parametrize("ttl", [0, -1, 0.5, True])
def test_invalid_ttl_rejected(ttl):
    with pytest.raises(ValueError):
        limiter.acquire("odbc", ttl)


@pytest.mark.parametrize("source_error", [False, True])
def test_cleanup_busy_preserves_source_outcome(monkeypatch, source_error):
    from backend.v2.spice import SpiceError
    release = limiter.release
    lid = None
    def busy(_): raise limiter.Busy()
    monkeypatch.setattr(limiter, "release", busy)
    try:
        if source_error:
            with pytest.raises(SpiceError) as ex:
                with limiter.lease("odbc") as lid:
                    raise SpiceError("timeout")
            assert ex.value.code == "timeout"
        else:
            with limiter.lease("odbc") as lid:
                result = "success"
            assert result == "success"
    finally:
        if lid: release(lid)
