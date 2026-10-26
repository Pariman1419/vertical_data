"""Synthetic local SQLite integration tests; never connect a factory DB."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import uuid

from backend.foundation.core import (Conflict, Denied, Invalid, LeaseLost,
                                     Principal, Registry, process_one)
from backend.foundation.secrets import CredentialsRequired, UnavailableSecretStore


class FoundationTests(unittest.TestCase):
    def setUp(self):
        test_root = Path(__file__).resolve().parents[1] / ".foundation-test"
        test_root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="registry-", dir=test_root)
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "registry.sqlite3"
        self.now = 1000.0
        self.registry = Registry(self.path, clock=lambda: self.now)
        self.admin = Principal("synthetic-admin", "Admin")
        self.viewer = Principal("synthetic-viewer", "Viewer")
        self.operator = Principal("synthetic-operator", "Operator")
        self.steward = Principal("synthetic-steward", "Data Steward")
        self.config = {"role": "Source", "engine": "synthetic", "host": "demo-source.invalid",
                       "database": "DEMO_MES", "authentication": "none"}
        self.registry.save_bundle(self.admin, "bundle-demo", 0)

    def enqueue(self, request="request-demo", scope="source/table/target/generation-1", revision=1, **kw):
        return self.registry.enqueue(self.operator, request, scope, "bundle-demo", revision, **kw)

    def test_bootstrap_without_target_and_safe_metadata(self):
        result = self.registry.save_metadata(self.admin, "source-demo", 0, self.config)
        self.assertEqual(result["state"], "not_connected")
        reopened = Registry(self.path)
        with reopened.transaction() as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT revision FROM metadata").fetchone()[0], 1)
        self.assertTrue(result["is_simulation"])

    def test_secret_store_unavailable_never_echoes_or_saves(self):
        provider = UnavailableSecretStore()
        marker = uuid.uuid4().hex
        self.assertFalse(provider.available)
        for operation in (lambda: provider.resolve(marker), lambda: provider.save(marker)):
            with self.assertRaises(CredentialsRequired) as error:
                operation()
            self.assertNotIn(marker, str(error.exception))

    def test_bootstrap_refuses_foreign_or_newer_database(self):
        foreign = Path(self.temp.name) / "foreign.sqlite3"
        with closing(sqlite3.connect(foreign)) as db, db:
            db.execute("CREATE TABLE user_owned (id INTEGER)")
            db.execute("INSERT INTO user_owned VALUES(42)")
        with self.assertRaises(Invalid):
            Registry(foreign)
        with closing(sqlite3.connect(foreign)) as db, db:
            self.assertEqual(db.execute("SELECT id FROM user_owned").fetchone()[0], 42)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0], 1)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("PRAGMA user_version=99")
        with self.assertRaises(Invalid):
            Registry(self.path)

    def test_unknown_secret_fields_and_real_endpoints_fail_closed(self):
        marker = uuid.uuid4().hex  # In-memory test marker, not an actual credential.
        for field in ("password", "username", "secret_ref", "connection_string", "token"):
            with self.assertRaises(Invalid) as error:
                self.registry.save_metadata(self.admin, "source-demo", 0, {**self.config, field: marker})
            self.assertNotIn(marker, str(error.exception))
        with self.assertRaises(Invalid):
            self.registry.save_metadata(self.admin, "source-demo", 0, {**self.config, "host": "factory.example"})
        self.assertNotIn(marker.encode(), self.path.read_bytes())
        with self.assertRaises(Invalid):
            Registry(self.path, environment="production")
        with self.assertRaises(Invalid):
            self.enqueue(fixture_id="sql-server-extract")

    def test_metadata_and_bundle_revision_conflicts(self):
        self.registry.save_metadata(self.admin, "source-demo", 0, self.config)
        with self.assertRaises(Conflict):
            self.registry.save_metadata(self.admin, "source-demo", 0, self.config)
        self.assertEqual(self.registry.save_metadata(self.admin, "source-demo", 1, self.config)["revision"], 2)
        with self.assertRaises(Conflict):
            self.registry.save_bundle(self.steward, "bundle-demo", 0)
        self.registry.save_bundle(self.steward, "bundle-demo", 1)
        with self.assertRaises(Conflict):
            self.enqueue(revision=1)

    def test_deny_by_default_role_policy(self):
        for principal in (self.viewer, self.operator, self.steward, None,
                          Principal("synthetic-unknown", "Owner")):
            with self.assertRaises(Denied):
                self.registry.save_metadata(principal, "source-demo", 0, self.config)
        for principal in (self.viewer, self.steward, None):
            with self.assertRaises(Denied):
                self.registry.enqueue(principal, "req", "scope", "bundle-demo", 1)
        job = self.enqueue()
        self.assertEqual(self.registry.get_job(self.viewer, job["id"])["state"], "queued")

    def test_idempotency_and_scope_lock(self):
        job = self.enqueue()
        self.assertEqual(self.enqueue()["id"], job["id"])
        with self.assertRaises(Conflict):
            self.enqueue(scope="other-scope")
        with self.assertRaises(Conflict):
            self.enqueue(request="other-request")
        # Target/generation identities are a separate explicit scope.
        self.assertNotEqual(self.enqueue(request="next-generation", scope="source/table/target/generation-2")["id"], job["id"])

    def test_concurrent_idempotency_single_row_and_claim(self):
        def submit(_):
            return Registry(self.path, clock=lambda: self.now).enqueue(
                self.operator, "same-request", "same-scope", "bundle-demo", 1)["id"]
        with ThreadPoolExecutor(max_workers=4) as pool:
            ids = list(pool.map(submit, range(8)))
        self.assertEqual(len(set(ids)), 1)
        with ThreadPoolExecutor(max_workers=4) as pool:
            claimed = list(pool.map(lambda n: Registry(self.path, clock=lambda: self.now).claim("synthetic-worker-" + str(n)), range(4)))
        self.assertEqual(sum(job is not None for job in claimed), 1)

    def test_interruption_reopen_resume_and_fence_old_worker(self):
        job = self.enqueue()
        claim = self.registry.claim("synthetic-worker-old", ttl=5)
        self.registry.checkpoint(job["id"], claim["lease_token"], 1)
        self.assertIsNone(self.registry.claim("synthetic-worker-new"))
        self.now += 6
        new_registry = Registry(self.path, clock=lambda: self.now)
        recovered = new_registry.claim("synthetic-worker-new")
        self.assertEqual(recovered["id"], job["id"])
        self.assertEqual(recovered["checkpoint"], 1)
        self.assertEqual(recovered["attempts"], 2)
        with self.assertRaises(LeaseLost):
            self.registry.checkpoint(job["id"], claim["lease_token"], 2)
        with self.assertRaises(LeaseLost):
            self.registry.complete(job["id"], claim["lease_token"])
        for step in (2, 3):
            new_registry.checkpoint(job["id"], recovered["lease_token"], step)
        new_registry.complete(job["id"], recovered["lease_token"])
        result = new_registry.get_job(self.viewer, job["id"])
        self.assertEqual(result["state"], "synthetic_completed")
        self.assertNotIn("lease_token", result)
        self.assertFalse(result["etl_published"])
        self.assertFalse(result["database_connected"])
        self.assertIsNone(new_registry.claim("synthetic-worker-again"))

    def test_injected_crash_keeps_checkpoint_and_no_success(self):
        job = self.enqueue()
        with self.assertRaises(RuntimeError):
            process_one(self.registry, ttl=5, crash_after=2)
        current = self.registry.get_job(self.viewer, job["id"])
        self.assertEqual(current["checkpoint"], 2)
        self.assertEqual(current["state"], "running")
        self.assertIsNone(current["result"])
        self.now += 6
        process_one(Registry(self.path, clock=lambda: self.now))
        self.assertEqual(self.registry.get_job(self.viewer, job["id"])["state"], "synthetic_completed")

    def test_failure_retry_pins_bundle_after_new_revision(self):
        job = self.enqueue()
        claim = self.registry.claim("synthetic-worker")
        self.registry.fail(job["id"], claim["lease_token"])
        self.registry.save_bundle(self.steward, "bundle-demo", 1)
        retry = self.enqueue(request="retry-request", retry_of=job["id"])
        self.assertEqual(retry["bundle_revision"], 1)
        self.assertEqual(retry["retry_of"], job["id"])
        process_one(self.registry)
        self.assertEqual(self.registry.get_job(self.viewer, job["id"])["state"], "failed")
        self.assertEqual(self.registry.get_job(self.viewer, retry["id"])["state"], "synthetic_completed")
        with self.assertRaises(Conflict):
            self.enqueue(request="wrong-retry", revision=2, retry_of=job["id"])

    def test_cancel_at_safe_checkpoint_and_queued_cancel(self):
        job = self.enqueue()
        claim = self.registry.claim("synthetic-worker")
        self.registry.cancel(self.operator, job["id"])
        self.assertFalse(self.registry.checkpoint(job["id"], claim["lease_token"], 1))
        result = self.registry.get_job(self.viewer, job["id"])
        self.assertEqual(result["state"], "cancelled")
        self.assertIsNone(result["result"])
        second = self.enqueue(request="second-request")
        self.registry.cancel(self.operator, second["id"])
        self.assertIsNone(self.registry.claim("synthetic-worker"))

    def test_checkpoint_and_audit_transaction_rollback(self):
        job = self.enqueue()
        claim = self.registry.claim("synthetic-worker")
        with self.assertRaises(Conflict):
            self.registry.complete(job["id"], claim["lease_token"])
        with self.assertRaises(Invalid):
            self.registry.checkpoint(job["id"], claim["lease_token"], 4)
        self.assertEqual(self.registry.get_job(self.viewer, job["id"])["checkpoint"], 0)
        with self.registry.transaction() as db:
            actions = [row[0] for row in db.execute("SELECT action FROM audit")]
        self.assertIn("job.enqueued", actions)
        self.assertNotIn("job.synthetic_completed", actions)

    def test_separate_worker_process_and_restarted_caller(self):
        # Actual subprocess reads a file-backed registry independent of UI lifecycle.
        registry = Registry(self.path)  # Wall clock for the process lease.
        job = registry.enqueue(self.operator, "process-request", "process-scope", "bundle-demo", 1)
        outcome = subprocess.run([sys.executable, "-m", "backend.foundation.worker", "--registry", str(self.path)],
                                 cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=20)
        self.assertEqual(outcome.returncode, 0, outcome.stderr)
        reopened = Registry(self.path)
        result = reopened.get_job(self.viewer, job["id"])
        self.assertEqual(result["state"], "synthetic_completed")
        self.assertEqual(result["checkpoint"], 3)
        self.assertFalse(json.loads(result["result"])["etl_published"])


if __name__ == "__main__":
    unittest.main()
