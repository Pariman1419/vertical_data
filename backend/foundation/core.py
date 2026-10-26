"""Durable synthetic metadata/jobs. No network, Source SQL or Target publishing.

SQLite is a disposable local integration-test adapter, NOT an approved live registry.
Principals below are trusted test fixtures, NOT authentication or client role claims.
"""
from contextlib import contextmanager
from dataclasses import dataclass
import json
from pathlib import Path
import re
import sqlite3
import time
import uuid


class Conflict(Exception):
    pass


class Denied(Exception):
    pass


class Invalid(Exception):
    pass


class LeaseLost(Exception):
    pass


@dataclass(frozen=True)
class Principal:
    actor: str
    role: str


PERMISSIONS = {
    "metadata.write": {"Admin"},
    "bundle.write": {"Admin", "Data Steward"},
    "job.start": {"Admin", "Operator"},
    "read": {"Admin", "Data Steward", "Operator", "Viewer"},
}


def authorize(principal, action):
    # The future HTTP adapter must authenticate before constructing this object.
    if not isinstance(principal, Principal) or principal.role not in PERMISSIONS.get(action, set()):
        raise Denied("Permission denied")
    if not re.fullmatch(r"synthetic-[a-z-]{1,40}", principal.actor):
        raise Denied("Only trusted synthetic principals are supported")


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,120}", value):
        raise Invalid("Invalid synthetic identifier")
    return value


class Registry:
    def __init__(self, path, *, environment="synthetic-test", clock=time.time):
        if environment != "synthetic-test":
            raise Invalid("Only synthetic-test environment is enabled")
        self.path = Path(path)
        self.clock = clock
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise Invalid("Unsupported registry schema; no automatic downgrade")
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
            expected_tables = {"registry_info", "metadata", "bundles", "jobs", "audit"}
            if (version == 0 and tables) or (version == 1 and tables != expected_tables):
                raise Invalid("Refusing foreign or incomplete database; use a disposable synthetic registry")
            db.execute("CREATE TABLE IF NOT EXISTS registry_info (id INTEGER PRIMARY KEY CHECK(id=1), environment TEXT NOT NULL)")
            info = db.execute("SELECT environment FROM registry_info WHERE id=1").fetchone()
            if info and info[0] != environment:
                raise Invalid("Registry environment mismatch")
            db.execute("INSERT OR IGNORE INTO registry_info VALUES(1,?)", (environment,))
            db.execute("CREATE TABLE IF NOT EXISTS metadata (id TEXT PRIMARY KEY, revision INTEGER NOT NULL, payload TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS bundles (id TEXT PRIMARY KEY, revision INTEGER NOT NULL)")
            db.execute("""CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, request_id TEXT UNIQUE NOT NULL, signature TEXT NOT NULL,
                scope TEXT NOT NULL, bundle_id TEXT NOT NULL, bundle_revision INTEGER NOT NULL,
                fixture_id TEXT NOT NULL, retry_of TEXT, state TEXT NOT NULL,
                checkpoint INTEGER NOT NULL DEFAULT 0, lease_token TEXT, lease_until REAL,
                attempts INTEGER NOT NULL DEFAULT 0, result TEXT, actor TEXT NOT NULL,
                created_at REAL NOT NULL, updated_at REAL NOT NULL)""")
            db.execute("""CREATE UNIQUE INDEX IF NOT EXISTS active_scope ON jobs(scope)
                WHERE state IN ('queued','running','cancel_requested')""")
            db.execute("CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, actor TEXT NOT NULL, action TEXT NOT NULL, entity TEXT NOT NULL, at REAL NOT NULL)")
            db.execute("PRAGMA user_version=1")

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def audit(self, db, actor, action, entity):
        # Never persist arbitrary exception text, request bodies or credentials.
        db.execute("INSERT INTO audit(actor,action,entity,at) VALUES(?,?,?,?)",
                   (actor, action, entity, self.clock()))

    def save_metadata(self, principal, connection_id, expected_revision, config):
        authorize(principal, "metadata.write")
        identifier(connection_id)
        required = {"role", "engine", "host", "database", "authentication"}
        if not isinstance(config, dict) or set(config) != required:
            raise Invalid("Only allowlisted non-secret metadata is accepted")
        if (config["role"] not in ("Source", "Target") or config["engine"] != "synthetic"
                or config["authentication"] != "none"
                or not isinstance(config["host"], str)
                or not re.fullmatch(r"demo-[a-z0-9-]+\.invalid", config["host"])
                or not isinstance(config["database"], str)
                or not re.fullmatch(r"DEMO_[A-Z0-9_]+", config["database"])):
            raise Invalid("Real connection metadata is disabled in this harness")
        with self.transaction() as db:
            row = db.execute("SELECT revision FROM metadata WHERE id=?", (connection_id,)).fetchone()
            current = row[0] if row else 0
            if type(expected_revision) is not int or current != expected_revision:
                raise Conflict("Metadata revision conflict")
            revision = current + 1
            db.execute("INSERT INTO metadata VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,payload=excluded.payload",
                       (connection_id, revision, json.dumps(config, sort_keys=True)))
            self.audit(db, principal.actor, "metadata.saved", connection_id)
            return {"id": connection_id, "revision": revision, "state": "not_connected",
                    "environment": "synthetic-test", "is_simulation": True}

    def save_bundle(self, principal, bundle_id, expected_revision):
        authorize(principal, "bundle.write")
        identifier(bundle_id)
        with self.transaction() as db:
            row = db.execute("SELECT revision FROM bundles WHERE id=?", (bundle_id,)).fetchone()
            current = row[0] if row else 0
            if type(expected_revision) is not int or current != expected_revision:
                raise Conflict("Bundle revision conflict")
            db.execute("INSERT INTO bundles VALUES(?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision",
                       (bundle_id, current + 1))
            self.audit(db, principal.actor, "bundle.revised", bundle_id)
            return current + 1

    def enqueue(self, principal, request_id, scope, bundle_id, expected_revision,
                *, fixture_id="manufacturing-small-v1", retry_of=None):
        authorize(principal, "job.start")
        for value in (request_id, scope, bundle_id):
            identifier(value)
        if fixture_id != "manufacturing-small-v1":
            raise Invalid("Only the built-in synthetic probe is enabled")
        if type(expected_revision) is not int:
            raise Invalid("Revision must be an integer")
        signature = json.dumps([scope, bundle_id, expected_revision, fixture_id, retry_of])
        with self.transaction() as db:
            existing = db.execute("SELECT * FROM jobs WHERE request_id=?", (request_id,)).fetchone()
            if existing:
                if existing["signature"] != signature or existing["actor"] != principal.actor:
                    raise Conflict("Idempotency key already used for another request")
                return dict(existing)
            bundle = db.execute("SELECT revision FROM bundles WHERE id=?", (bundle_id,)).fetchone()
            if not bundle:
                raise Conflict("Bundle does not exist")
            pinned_revision = expected_revision
            if retry_of:
                original = db.execute("SELECT * FROM jobs WHERE id=?", (retry_of,)).fetchone()
                if not original or original["state"] != "failed":
                    raise Conflict("Retry requires a failed synthetic job")
                if (scope, bundle_id, fixture_id, expected_revision) != (original["scope"], original["bundle_id"], original["fixture_id"], original["bundle_revision"]):
                    raise Conflict("Retry scope/revision differs from original job")
            elif bundle[0] != expected_revision:
                raise Conflict("Bundle revision conflict")
            job_id = "JOB-SYNTH-" + uuid.uuid4().hex
            now = self.clock()
            try:
                db.execute("""INSERT INTO jobs(id,request_id,signature,scope,bundle_id,bundle_revision,
                    fixture_id,retry_of,state,actor,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (job_id, request_id, signature, scope, bundle_id, pinned_revision,
                     fixture_id, retry_of, "queued", principal.actor, now, now))
            except sqlite3.IntegrityError:
                raise Conflict("Synthetic scope already has an active job") from None
            self.audit(db, principal.actor, "job.enqueued", job_id)
            return dict(db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())

    def get_job(self, principal, job_id):
        authorize(principal, "read")
        with self.transaction() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (identifier(job_id),)).fetchone()
            if not row:
                raise Invalid("Job not found")
            result = dict(row)
            # Lease token is internal worker authority, never a client response.
            result.pop("lease_token")
            result.pop("signature")
            result.update(environment="synthetic-test", is_simulation=True,
                          database_connected=False, etl_published=False)
            return result

    def claim(self, worker, *, ttl=30):
        identifier(worker)
        if ttl <= 0:
            raise Invalid("Lease TTL must be positive")
        with self.transaction() as db:
            now = self.clock()
            # Only this deterministic synthetic handler permits checkpoint recovery.
            expired = db.execute("SELECT id FROM jobs WHERE state IN ('running','cancel_requested') AND lease_until<=?", (now,)).fetchall()
            for row in expired:
                db.execute("""UPDATE jobs SET state=CASE WHEN state='cancel_requested' THEN 'cancelled' ELSE 'queued' END,
                    lease_token=NULL,lease_until=NULL,updated_at=? WHERE id=?""", (now, row[0]))
                self.audit(db, worker, "job.lease_recovered", row[0])
            row = db.execute("SELECT id FROM jobs WHERE state='queued' ORDER BY created_at,id LIMIT 1").fetchone()
            if not row:
                return None
            token = uuid.uuid4().hex
            db.execute("UPDATE jobs SET state='running',lease_token=?,lease_until=?,attempts=attempts+1,updated_at=? WHERE id=?",
                       (token, now + ttl, now, row[0]))
            self.audit(db, worker, "job.claimed", row[0])
            return dict(db.execute("SELECT * FROM jobs WHERE id=?", (row[0],)).fetchone())

    def _owned(self, db, job_id, token):
        row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row or row["state"] not in ("running", "cancel_requested") or row["lease_token"] != token or row["lease_until"] <= self.clock():
            raise LeaseLost("Worker lease is stale; write rejected")
        return row

    def heartbeat(self, job_id, token, *, ttl=30):
        if ttl <= 0:
            raise Invalid("Lease TTL must be positive")
        with self.transaction() as db:
            self._owned(db, job_id, token)
            db.execute("UPDATE jobs SET lease_until=?,updated_at=? WHERE id=?", (self.clock() + ttl, self.clock(), job_id))

    def checkpoint(self, job_id, token, step):
        with self.transaction() as db:
            row = self._owned(db, job_id, token)
            if row["state"] == "cancel_requested":
                db.execute("UPDATE jobs SET state='cancelled',lease_token=NULL,lease_until=NULL,updated_at=? WHERE id=?", (self.clock(), job_id))
                return False
            if type(step) is not int or not row["checkpoint"] <= step <= 3:
                raise Invalid("Invalid synthetic checkpoint")
            db.execute("UPDATE jobs SET checkpoint=?,updated_at=? WHERE id=?", (step, self.clock(), job_id))
            return True

    def complete(self, job_id, token):
        with self.transaction() as db:
            row = self._owned(db, job_id, token)
            if row["state"] == "cancel_requested":
                db.execute("UPDATE jobs SET state='cancelled',lease_token=NULL,lease_until=NULL,updated_at=? WHERE id=?", (self.clock(), job_id))
                return
            if row["checkpoint"] != 3:
                raise Conflict("Synthetic checkpoints incomplete")
            # Deliberately not an ETL Success or a Target Publish.
            result = json.dumps({"fixture_records_verified": 3, "is_simulation": True, "etl_published": False})
            db.execute("UPDATE jobs SET state='synthetic_completed',result=?,lease_token=NULL,lease_until=NULL,updated_at=? WHERE id=?", (result, self.clock(), job_id))
            self.audit(db, "synthetic-worker", "job.synthetic_completed", job_id)

    def fail(self, job_id, token):
        with self.transaction() as db:
            self._owned(db, job_id, token)
            db.execute("UPDATE jobs SET state='failed',result=NULL,lease_token=NULL,lease_until=NULL,updated_at=? WHERE id=?", (self.clock(), job_id))
            self.audit(db, "synthetic-worker", "job.failed", job_id)

    def cancel(self, principal, job_id):
        authorize(principal, "job.start")
        with self.transaction() as db:
            row = db.execute("SELECT state FROM jobs WHERE id=?", (identifier(job_id),)).fetchone()
            if not row:
                raise Invalid("Job not found")
            if row[0] in ("queued", "running"):
                state = "cancelled" if row[0] == "queued" else "cancel_requested"
                db.execute("UPDATE jobs SET state=?,updated_at=? WHERE id=?", (state, self.clock(), job_id))
                self.audit(db, principal.actor, "job.cancel_requested", job_id)


# Read-only fixture records; there is no source connector or credentials.
FIXTURE = (("102", "000123"), ("103", "000124"), ("104", "UTL2-000123"))


def process_one(registry, worker="synthetic-worker", *, ttl=30, crash_after=None):
    job = registry.claim(worker, ttl=ttl)
    if not job:
        return None
    token = job["lease_token"]
    for step in range(job["checkpoint"] + 1, len(FIXTURE) + 1):
        event_id, lot = FIXTURE[step - 1]
        if not event_id or not lot:
            registry.fail(job["id"], token)
            return job["id"]
        registry.heartbeat(job["id"], token, ttl=ttl)
        if not registry.checkpoint(job["id"], token, step):
            return job["id"]
        if step == crash_after:
            # Testing exception interrupts the worker, leaving durable lease/checkpoint.
            raise RuntimeError("Injected synthetic worker interruption")
    registry.complete(job["id"], token)
    return job["id"]
