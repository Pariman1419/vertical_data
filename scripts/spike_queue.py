"""THROWAWAY Task 2 spike. No app imports, shared DB, Docker or production use.

Linux/WSL only. Requires approved dramatiq==2.2.1 and redis==8.1.0.
PostgreSQL is unpacked temporarily from an Ubuntu package, not installed.
Run --self-test before --run. All runtime artifacts live in TemporaryDirectory.
"""

import argparse
import concurrent.futures
import hashlib
import json
import logging
import os
from pathlib import Path
import resource
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import unittest
import urllib.request
import uuid


class AuthorityTests(unittest.TestCase):
    """Real isolated PG contract, NOT the future Task 3 schema/migration."""

    def setUp(self):
        self.db = PgAuthority()
        self.db.sql("TRUNCATE writes, runs")
        self.run = self.db.create("quick")

    def test_only_one_concurrent_claim(self):
        with concurrent.futures.ThreadPoolExecutor(8) as pool:
            claims = list(pool.map(lambda _: self.db.claim(self.run), range(8)))
        self.assertEqual(sum(token is not None for token in claims), 1)

    def test_expired_claim_fences_old_writer(self):
        first = self.db.claim(self.run)
        self.db.expire(self.run)
        second = self.db.claim(self.run)
        self.assertEqual(second, first + 1)
        self.assertFalse(self.db.complete(self.run, first))
        self.assertFalse(self.db.heartbeat(self.run, first))
        self.assertFalse(self.db.write(self.run, first))
        self.assertTrue(self.db.write(self.run, second))
        self.assertTrue(self.db.complete(self.run, second))
        self.assertIsNone(self.db.claim(self.run))

    def test_expiry_without_takeover_still_rejects_writer(self):
        token = self.db.claim(self.run)
        self.db.expire(self.run)
        self.assertFalse(self.db.complete(self.run, token))
        self.assertFalse(self.db.heartbeat(self.run, token))
        self.assertFalse(self.db.write(self.run, token))

    def test_reaper_reads_durable_queued_state(self):
        self.assertEqual(self.db.queued(), [self.run])
        self.db.claim(self.run)
        self.assertEqual(self.db.queued(), [])

    def test_inherited_pg_settings_cannot_redirect_the_connection(self):
        from unittest.mock import patch

        with patch.dict(os.environ, {"PGSERVICE": "uetl_spike_nonexistent_service",
                                    "PGHOSTADDR": "127.0.0.1"}):
            self.assertEqual(self.db.sql("SELECT 1"), "1")


PG_VERSION = "16.15-0ubuntu0.24.04.1"
PG_SHA256 = "d60ae76fb862cd4cca7bfdcdcdcc271c5e1d75f6b7915305ce2d962735a4b666"
PG_URL = ("https://archive.ubuntu.com/ubuntu/pool/main/p/postgresql-16/"
          f"postgresql-16_{PG_VERSION}_amd64.deb")
LEASE_SECONDS = 6
BROKER_TIMEOUT_MS = 1500
NAMESPACE = "uetl_throwaway"
QUEUE = "spike"


def run_key(value):
    return str(uuid.UUID(value))


def wait_for(predicate, timeout=20):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        result = predicate()
        if result:
            return result
        time.sleep(0.1)
    raise AssertionError("spike condition timed out")


class PgAuthority:
    """Throwaway SQL only. psql always has an explicit private Unix socket.

    No app config/.env is imported. UUIDs and integers are validated before SQL.
    Diagnostic delivery counters are not ETL writes; writes has a fence trigger.
    """

    def sql(self, query, *, reject_ok=False):
        # libpq's PGHOSTADDR/PGSERVICE can override host routing despite -h.
        # Do not inherit any PG settings or credential files from the caller.
        pg_env = {key: value for key, value in os.environ.items() if not key.startswith("PG")}
        pg_env["PGPASSFILE"] = "/dev/null"
        result = subprocess.run(
            ["/usr/lib/postgresql/16/bin/psql", "-XqAt", "-v", "ON_ERROR_STOP=1",
             "-h", os.environ["SPIKE_PG_SOCKET"], "-p", os.environ["SPIKE_PG_PORT"],
             "-U", os.environ["USER"], "-d", "postgres", "-c", query],
            capture_output=True, text=True, timeout=10, env=pg_env,
        )
        if result.returncode:
            if reject_ok and "stale_fence" in result.stderr:
                return None
            # Never forward raw SQL/server diagnostics to a report/log.
            raise RuntimeError("isolated_pg_statement_failed")
        return result.stdout.strip()

    def create(self, mode):
        assert mode in {"quick", "crash", "hold", "long", "memory"}
        run = str(uuid.uuid4())
        self.sql(f"INSERT INTO runs(id,mode) VALUES ('{run}','{mode}')")
        return run

    def get(self, run):
        return json.loads(self.sql(f"SELECT row_to_json(r) FROM runs r WHERE id='{run_key(run)}'"))

    def claim(self, run):
        value = self.sql(f"""UPDATE runs SET state='running', fence=fence+1,
            lease_until=clock_timestamp()+interval '{LEASE_SECONDS} seconds'
            WHERE id='{run_key(run)}' AND (state='queued' OR
              (state='running' AND lease_until<clock_timestamp())) RETURNING fence""")
        return int(value) if value else None

    def heartbeat(self, run, token):
        return bool(self.sql(f"""UPDATE runs SET heartbeat_count=heartbeat_count+1,
            lease_until=clock_timestamp()+interval '{LEASE_SECONDS} seconds'
            WHERE id='{run_key(run)}' AND fence={int(token)} AND state='running'
            AND lease_until>clock_timestamp() RETURNING id"""))

    def complete(self, run, token):
        return bool(self.sql(f"""UPDATE runs SET state='done', completed=completed+1
            WHERE id='{run_key(run)}' AND fence={int(token)} AND state='running'
            AND lease_until>clock_timestamp() RETURNING id"""))

    def write(self, run, token):
        return self.sql(f"INSERT INTO writes VALUES ('{run_key(run)}',{int(token)}) RETURNING token",
                        reject_ok=True) is not None

    def expire(self, run):
        self.sql(f"UPDATE runs SET lease_until='2000-01-01Z' WHERE id='{run_key(run)}'")

    def queued(self):
        return self.sql("SELECT id FROM runs WHERE state='queued' ORDER BY id").splitlines()

    def reaper(self, actor):
        runs = self.sql("""UPDATE runs SET state='queued'
            WHERE state='queued' OR (state='running' AND lease_until<clock_timestamp())
            RETURNING id""").splitlines()
        for run in runs:
            actor.send({"run_id": run})
        return runs

    def observe(self, run, values):
        # JSON here contains only generated identifiers/numeric measurements.
        encoded = json.dumps(values, separators=(",", ":")).replace("'", "''")
        self.sql(f"UPDATE runs SET observations=observations||'{encoded}'::jsonb WHERE id='{run_key(run)}'")


SCHEMA = """
CREATE TABLE runs (
 id uuid PRIMARY KEY, mode text NOT NULL, state text NOT NULL DEFAULT 'queued',
 fence bigint NOT NULL DEFAULT 0, lease_until timestamptz,
 heartbeat_count int NOT NULL DEFAULT 0, completed int NOT NULL DEFAULT 0,
 invocations int NOT NULL DEFAULT 0, noops int NOT NULL DEFAULT 0,
 message_ids uuid[] NOT NULL DEFAULT '{}', observations jsonb NOT NULL DEFAULT '{}'
);
CREATE TABLE writes (run_id uuid REFERENCES runs(id), token bigint NOT NULL);
CREATE FUNCTION fence_write() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 PERFORM 1 FROM runs WHERE id=NEW.run_id AND fence=NEW.token AND state='running'
   AND lease_until>clock_timestamp() FOR UPDATE;
 IF NOT FOUND THEN RAISE EXCEPTION 'stale_fence'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER fence_write BEFORE INSERT ON writes FOR EACH ROW EXECUTE FUNCTION fence_write();
"""


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def stop_process(process, *, force=False):
    if process is None:
        return
    if process.poll() is None:
        process.send_signal(signal.SIGKILL if force else signal.SIGTERM)
    try:
        process.wait(timeout=12)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


class Sandbox:
    def __init__(self, root):
        self.root = root
        self.pg = self.redis = None
        self.workers = []
        self.old_env = {name: os.environ.get(name) for name in (
            "SPIKE_PG_SOCKET", "SPIKE_PG_PORT", "SPIKE_REDIS_PORT", "SPIKE_REDIS_PASSWORD")}

    def start_pg(self):
        package = self.root / "pg.deb"
        urllib.request.urlretrieve(PG_URL, package)
        assert hashlib.sha256(package.read_bytes()).hexdigest() == PG_SHA256
        prefix = self.root / "unpacked"
        subprocess.run(["dpkg-deb", "-x", str(package), str(prefix)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        binaries = prefix / "usr/lib/postgresql/16/bin"
        data = self.root / "pgdata"
        sockets = self.root / "socket"
        sockets.mkdir(mode=0o700)
        subprocess.run([str(binaries / "initdb"), "-D", str(data), "-L",
                        str(prefix / "usr/share/postgresql/16"), "--locale=C",
                        "--auth-local=trust", "--auth-host=reject", "--no-sync"],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.environ["SPIKE_PG_SOCKET"] = str(sockets)
        os.environ["SPIKE_PG_PORT"] = str(free_port())
        # Session group lets cleanup reap PG background children after an abort.
        self.pg = subprocess.Popen([str(binaries / "postgres"), "-D", str(data),
            "-k", str(sockets), "-p", os.environ["SPIKE_PG_PORT"],
            "-c", "listen_addresses=", "-c", "jit=off", "-c", "shared_buffers=16MB"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        def ready():
            if self.pg.poll() is not None:
                raise RuntimeError("isolated_pg_start_failed")
            try:
                return PgAuthority().sql("SELECT 1") == "1"
            except RuntimeError:
                return False
        wait_for(ready)
        PgAuthority().sql(SCHEMA)

    def start_redis(self):
        import redis
        if "SPIKE_REDIS_PASSWORD" not in os.environ:
            os.environ["SPIKE_REDIS_PASSWORD"] = secrets.token_urlsafe(32)
            os.environ["SPIKE_REDIS_PORT"] = str(free_port())
        directory = self.root / "aof"
        directory.mkdir(exist_ok=True, mode=0o700)
        # Config exists only in memory/stdin. In particular, NO redis.conf file.
        config = (f"bind 127.0.0.1\nport {os.environ['SPIKE_REDIS_PORT']}\n"
                  f"requirepass {os.environ['SPIKE_REDIS_PASSWORD']}\n"
                  f"dir {directory}\nappendonly yes\nappendfsync always\n"
                  "save \"\"\nprotected-mode yes\ndaemonize no\nloglevel warning\n")
        self.redis = subprocess.Popen(["redis-server", "-"], stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.redis.stdin.write(config.encode())
        self.redis.stdin.close()
        self.client = redis.Redis(host="127.0.0.1", port=int(os.environ["SPIKE_REDIS_PORT"]),
            password=os.environ["SPIKE_REDIS_PASSWORD"], socket_timeout=2)
        def ready():
            if self.redis.poll() is not None:
                raise RuntimeError("isolated_redis_start_failed")
            try:
                return self.client.ping()
            except redis.ConnectionError:
                return False
        wait_for(ready)
        assert self.client.info("server")["redis_version"] == "7.0.15"
        assert self.client.config_get("bind")["bind"] == "127.0.0.1"
        assert self.client.config_get("appendonly")["appendonly"] == "yes"
        unauthenticated = redis.Redis(host="127.0.0.1", port=int(os.environ["SPIKE_REDIS_PORT"]))
        try:
            unauthenticated.ping()
            raise AssertionError("Redis allowed unauthenticated access")
        except redis.AuthenticationError:
            pass
        finally:
            unauthenticated.close()

    def worker(self):
        process = subprocess.Popen([sys.executable, "-B", str(Path(__file__).resolve()), "--worker"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.workers.append(process)
        return process

    def stop_workers(self):
        for process in self.workers:
            stop_process(process)
        self.workers.clear()

    def cleanup(self):
        self.stop_workers()
        stop_process(self.redis)
        # PG uses smart shutdown for SIGTERM; all psql calls are short-lived.
        stop_process(self.pg)
        if self.pg is not None:
            try:
                os.killpg(self.pg.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        secret = os.environ.get("SPIKE_REDIS_PASSWORD", "").encode()
        leaked = False
        if secret:
            for path in self.root.rglob("*"):
                if path.is_file() and secret in path.read_bytes():
                    leaked = True
        for name, original in self.old_env.items():
            if original is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = original
        assert not leaked, "temporary secret appeared in a scratch file"
        assert all(p.poll() is not None for p in (self.pg, self.redis) if p is not None)


def make_actor():
    import dramatiq
    from dramatiq.brokers.redis import RedisBroker
    from dramatiq.middleware import CurrentMessage, Retries

    broker = RedisBroker(host="127.0.0.1", port=int(os.environ["SPIKE_REDIS_PORT"]),
        password=os.environ["SPIKE_REDIS_PASSWORD"], namespace=NAMESPACE,
        heartbeat_timeout=BROKER_TIMEOUT_MS, maintenance_chance=1_000_000,
        middleware=[Retries(max_retries=0), CurrentMessage()], socket_timeout=2)

    @dramatiq.actor(broker=broker, queue_name=QUEUE, max_retries=0)
    def execute(payload):
        assert set(payload) == {"run_id"}
        run = run_key(payload["run_id"])
        db = PgAuthority()
        message_id = run_key(CurrentMessage.get_current_message().message_id)
        db.sql(f"UPDATE runs SET invocations=invocations+1, message_ids=array_append(message_ids,'{message_id}') WHERE id='{run}'")
        token = db.claim(run)
        if token is None:
            db.sql(f"UPDATE runs SET noops=noops+1 WHERE id='{run}'")
            return
        row = db.get(run)
        db.observe(run, {"broker_id": broker.broker_id, "pid": os.getpid()})
        finished = threading.Event()
        lost = threading.Event()

        def heartbeat():
            while not finished.wait(1):
                try:
                    if not db.heartbeat(run, token):
                        lost.set()
                        return
                except RuntimeError:
                    lost.set()
                    return

        heartbeat_thread = threading.Thread(target=heartbeat, daemon=True)
        heartbeat_thread.start()
        start = time.monotonic()
        try:
            if row["mode"] == "crash" and token == 1:
                time.sleep(60)  # Parent sends actual Linux SIGKILL mid-job.
            elif row["mode"] == "hold":
                wait_for(lambda: db.get(run)["observations"].get("release"), 30)
            elif row["mode"] == "long":
                while time.monotonic() - start < 300:
                    if lost.wait(0.1):
                        raise AssertionError("PG lease lost during five-minute job")
            elif row["mode"] == "memory":
                def rss():
                    for line in Path("/proc/self/status").read_text().splitlines():
                        if line.startswith("VmRSS:"):
                            return int(line.split()[1]) * 1024
                    raise AssertionError("RSS unavailable")
                before = rss()
                peak_before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024
                count = checksum = 0
                peak_sampled = before
                rows = ((i, f"synthetic-{i:08d}", i % 97) for i in range(5_000_000))
                for row in rows:
                    count += 1
                    checksum += row[0]
                    if count % 10_000 == 0:
                        peak_sampled = max(peak_sampled, rss())
                db.observe(run, {"rows": count, "checksum": checksum, "rss_before_bytes": before,
                    "rss_after_bytes": rss(), "rss_peak_sampled_bytes": peak_sampled,
                    "ru_maxrss_before_bytes": peak_before,
                    "ru_maxrss_after_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024})
            assert not lost.is_set()
            assert db.write(run, token)
            db.observe(run, {"duration_s": round(time.monotonic() - start, 3)})
            assert db.complete(run, token)
        except BaseException as exc:
            db.observe(run, {"actor_failure_class": type(exc).__name__,
                "actor_failure_lines": [frame.lineno for frame in traceback.extract_tb(exc.__traceback__)
                                        if frame.filename == __file__]})
            raise
        finally:
            finished.set()
            heartbeat_thread.join(timeout=10)

    return broker, execute


def worker_main():
    from dramatiq import Worker
    broker, _ = make_actor()
    stopped = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    worker = Worker(broker, worker_threads=1, worker_timeout=100)
    # One in-flight run per process; do not reserve a duplicate behind a held job.
    worker.queue_prefetch = 1
    worker.start()
    try:
        stopped.wait()
    finally:
        worker.stop(timeout=10_000)
        broker.close()


def experiments(sandbox, results):
    db = PgAuthority()
    db.sql("TRUNCATE writes, runs")
    broker, actor = make_actor()

    def done(run):
        row = db.get(run)
        return row if row["state"] == "done" else None

    def emit(key, values):
        results[key] = {"evidence": "TESTED LIVE / ISOLATED", **values}
        print(json.dumps({key: results[key]}), flush=True)

    # (a) Immediate replacement may ACK a duplicate while PG lease is live.
    # The PG reaper must recover it when that lease expires: do not lose the run.
    run = db.create("crash")
    message = actor.send({"run_id": run})
    killed = sandbox.worker()
    wait_for(lambda: db.get(run)["observations"].get("pid"))
    kill_at = time.monotonic()
    stop_process(killed, force=True)
    assert killed.returncode == -signal.SIGKILL
    sandbox.worker()
    wait_for(lambda: db.get(run)["invocations"] >= 2)
    redelivered_s = time.monotonic() - kill_at
    row = db.get(run)
    assert row["message_ids"][0] == row["message_ids"][1] == message.message_id
    reaped = []
    if row["state"] != "done":
        wait_for(lambda: db.sql(f"SELECT lease_until<clock_timestamp() FROM runs WHERE id='{run}'") == "t")
        reaped = db.reaper(actor)
    row = wait_for(lambda: done(run))
    assert row["fence"] == 2 and row["completed"] == 1
    assert not db.write(run, 1)
    emit("a", {"sigkill_exit": killed.returncode, "same_message_id_redelivered": True,
        "redelivery_after_kill_s": round(redelivered_s, 3), "fence": row["fence"],
        "invocations": row["invocations"], "noops": row["noops"], "completed": row["completed"],
        "pg_reaper_needed": run in reaped, "stale_writer_rejected": True})
    sandbox.stop_workers()

    # (b) Independent processes, duplicate both during the lease and after success.
    print(json.dumps({"starting": "b"}), flush=True)
    run = db.create("hold")
    actor.send({"run_id": run})
    sandbox.worker()
    wait_for(lambda: db.get(run)["state"] == "running")
    actor.send({"run_id": run})
    sandbox.worker()
    wait_for(lambda: db.get(run)["noops"] == 1)
    db.observe(run, {"release": True})
    wait_for(lambda: done(run))
    actor.send({"run_id": run})
    wait_for(lambda: db.get(run)["noops"] == 2)
    row = db.get(run)
    writes = int(db.sql(f"SELECT count(*) FROM writes WHERE run_id='{run}'"))
    assert row["fence"] == row["completed"] == writes == 1
    emit("b", {"deliveries": row["invocations"], "noops": row["noops"],
        "fence": row["fence"], "completed": row["completed"], "guarded_writes": writes})
    sandbox.stop_workers()
    wait_for(lambda: sandbox.client.hlen(f"{NAMESPACE}:{QUEUE}.msgs") == 0)

    # (c) Stronger than a graceful restart: SIGKILL after fsynced enqueue.
    run = db.create("quick")
    message = actor.send({"run_id": run})
    envelope_before = sandbox.client.hgetall(f"{NAMESPACE}:{QUEUE}.msgs")
    assert len(envelope_before) == 1
    stop_process(sandbox.redis, force=True)
    sandbox.start_redis()
    envelope_after = sandbox.client.hgetall(f"{NAMESPACE}:{QUEUE}.msgs")
    assert envelope_before == envelope_after
    sandbox.worker()
    row = wait_for(lambda: done(run))
    assert row["message_ids"] == [message.message_id] and row["completed"] == 1
    emit("c", {"redis_sigkill_exit": -signal.SIGKILL, "appendfsync": "always",
        "queued_before": len(envelope_before), "queued_after": len(envelope_after),
        "identical_envelope": True, "completed": row["completed"]})
    sandbox.stop_workers()

    # (d) Dedicated server only: FLUSHALL must never target the existing 6379.
    run = db.create("quick")
    actor.send({"run_id": run})
    sandbox.client.flushall()
    assert sandbox.client.dbsize() == 0 and db.get(run)["state"] == "queued"
    recovered = db.reaper(actor)
    assert recovered == [run]
    sandbox.worker()
    row = wait_for(lambda: done(run))
    assert row["completed"] == 1
    emit("d", {"keys_after_flush": 0, "pg_queued_rows_reenqueued": len(recovered),
        "fence": row["fence"], "completed": row["completed"]})
    sandbox.stop_workers()

    # Gate: any assertion in (a)-(d) aborts, cleans up and never starts (e)/(f).
    run = db.create("long")
    actor.send({"run_id": run})
    sandbox.worker()
    owner = wait_for(lambda: db.get(run)["observations"].get("broker_id"))
    sandbox.worker()  # Idle competitor drives maintenance throughout the job.
    max_age_ms = 0
    minimum_lease_remaining_s = LEASE_SECONDS
    samples = 0
    begun = last_progress = time.monotonic()
    while True:
        row = db.get(run)
        assert row["invocations"] == 1 and row["fence"] == 1
        score = sandbox.client.zscore(f"{NAMESPACE}:__heartbeats__", owner)
        assert score is not None
        max_age_ms = max(max_age_ms, int(time.time() * 1000 - score))
        if row["state"] == "done":
            break
        remaining = float(db.sql(f"SELECT extract(epoch FROM lease_until-clock_timestamp()) FROM runs WHERE id='{run}'"))
        minimum_lease_remaining_s = min(minimum_lease_remaining_s, remaining)
        assert remaining > 0
        samples += 1
        if time.monotonic() - last_progress >= 30:
            print(json.dumps({"e_progress_s": round(time.monotonic() - begun, 1),
                              "pg_heartbeats": row["heartbeat_count"]}), flush=True)
            last_progress = time.monotonic()
        assert time.monotonic() - begun < 340
        time.sleep(0.5)
    assert row["observations"]["duration_s"] >= 300 and row["heartbeat_count"] > 0
    emit("e", {"duration_s": row["observations"]["duration_s"],
        "broker_heartbeat_timeout_ms": BROKER_TIMEOUT_MS, "max_broker_heartbeat_age_ms": max_age_ms,
        "pg_lease_seconds": LEASE_SECONDS, "pg_heartbeat_count": row["heartbeat_count"],
        "minimum_pg_lease_remaining_s": round(minimum_lease_remaining_s, 3),
        "samples": samples, "deliveries": row["invocations"], "completed": row["completed"]})
    sandbox.stop_workers()

    run = db.create("memory")
    actor.send({"run_id": run})
    sandbox.worker()
    row = wait_for(lambda: done(run), 60)
    observations = row["observations"]
    assert observations["rows"] == 5_000_000
    assert observations["checksum"] == 5_000_000 * 4_999_999 // 2
    # Omit generated PID/broker identifiers from the retained result.
    emit("f", {key: value for key, value in observations.items() if key not in {"pid", "broker_id"}})
    sandbox.stop_workers()
    broker.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    if args.worker:
        worker_main()
        return
    if not (args.self_test or args.run):
        parser.error("choose --self-test or --run")
    results = {}
    failed = None
    scratch = None
    # SIGTERM/INT becomes an exception so the finally block always owns cleanup.
    def interrupted(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    try:
        with tempfile.TemporaryDirectory(prefix="uetl-queue-spike-") as name:
            scratch = Path(name)
            sandbox = Sandbox(scratch)
            try:
                sandbox.start_pg()
                suite = unittest.defaultTestLoader.loadTestsFromTestCase(AuthorityTests)
                outcome = unittest.TextTestRunner(verbosity=1).run(suite)
                assert outcome.wasSuccessful()
                results["pg_contract_tests"] = outcome.testsRun
                if args.run:
                    sandbox.start_redis()
                    experiments(sandbox, results)
            except BaseException as exc:
                # Keep partial evidence, but never exception values/raw SQL/config.
                failed = type(exc).__name__
                results["failure_lines"] = [frame.lineno for frame in traceback.extract_tb(exc.__traceback__)
                                            if frame.filename == __file__]
                try:
                    results["failure_diagnostics"] = json.loads(PgAuthority().sql(
                        "SELECT coalesce(json_agg(t),'[]') FROM (SELECT mode,state,fence,invocations,noops,"
                        "completed,heartbeat_count,observations FROM runs) t"))
                except Exception:
                    pass
            finally:
                sandbox.cleanup()
        assert not scratch.exists()
        results["cleanup"] = {"owned_processes_remaining": 0, "scratch_exists": False,
                              "secret_found_in_scratch_files": False}
    finally:
        print(json.dumps({"final": results, "failure_class": failed}), flush=True)
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
