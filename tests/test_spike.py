import http.client
import json
import ssl
import threading
import tempfile
import os
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from backend.spike.service import Service, APIError, config_validate
from backend.spike.server import handler_for, tls_context
from backend.spike.catalog_store import CatalogStore
from backend.spike.target_store import SQLiteTargetStore
from backend.foundation.oracle_read import SourceReadFailed
from test_oracle_read import Connection

PASSWORD = "synthetic-app-passphrase"


def config():
    return dict(host="fixture.invalid", port=1521, identifier_type="Service Name", identifier="fixture",
                username="synthetic-user", password="synthetic-password", protocol="tcps", tcp_ack=False, readonly_ack=True)


class SpikeTests(unittest.TestCase):
    def setUp(self):
        test_temp_root = Path(__file__).resolve().parents[1] / ".test-temp"
        test_temp_root.mkdir(exist_ok=True)
        self.target_temp = tempfile.TemporaryDirectory(prefix="target-", dir=test_temp_root)
        os.environ["TEMP"] = str(test_temp_root)
        os.environ["TMP"] = str(test_temp_root)
        self.connections = []
        def factory(c, t):
            def connect():
                cn = Connection([("synthetic-user", "synthetic-db")], query_rows={
                    "catalog": [("BIDPITDBA", "DP_WIP_DATA", "TABLE", 1), ("QA_SCHEMA", "LOT_QC", "VIEW", 2)],
                    "column_match": [("BIDPITDBA", "DP_WIP_DATA", "LOT_NO"),
                                     ("QA_SCHEMA", "LOT_QC", "LOT_NO"),
                                     ("QA_SCHEMA", "LOT_QC", "ORDER_NO")],
                    "object": [("BIDPITDBA", "DP_WIP_DATA", "TABLE")],
                    "columns": [("LOT_NO", 1, "VARCHAR2", "N"), ("PAYLOAD", 2, "CLOB", "Y")],
                    "keys": [("PK_DP_WIP_DATA", "P", "LOT_NO", 1, None, None)],
                    "sample": [("LOT-1",)],
                })
                self.connections.append(cn)
                return cn
            return connect
        self.service = Service(PASSWORD, factory=factory, target_store=SQLiteTargetStore(Path(self.target_temp.name) / "local.sqlite3"))
        self.token, self.csrf = self.service.login(PASSWORD)
    def tearDown(self):
        self.service.close()
        self.target_temp.cleanup()
    def wait(self, receipt):
        for _ in range(100):
            job = self.service.job(self.token, receipt["job_id"])
            if job["state"] != "running": return job
            time.sleep(.01)
        self.fail("Worker did not finish")
    def test_auth_and_no_client_role_override(self):
        with self.assertRaises(APIError): self.service.session("unknown")
        with self.assertRaises(APIError): self.service.login("wrong")
        with self.assertRaises(APIError): self.service.submit(self.token, "test", {"config": config(), "timeout": 15, "role": "Admin"})
    def test_connection_snapshot_and_restart_no_credentials(self):
        supplied = config()
        job = self.wait(self.service.submit(self.token, "test", {"config": supplied, "timeout": 15}))
        self.assertEqual(job["state"], "read_completed")
        self.assertFalse(job["etl_published"])
        self.assertNotIn("synthetic-password", json.dumps(job))
        self.assertTrue(self.service.session(self.token)["config"]["password"])
        other = Service(PASSWORD)
        try:
            with self.assertRaises(APIError): other.session(self.token)
        finally: other.close()
    def test_legacy_flat_test_request_shape_is_normalized_safely(self):
        payload = config() | {"timeout": 15, "profile_id": "legacy-profile"}
        job = self.wait(self.service.submit(self.token, "test", payload))
        self.assertEqual(job["state"], "read_completed")
        self.assertNotIn("synthetic-password", json.dumps(job))
        with self.assertRaisesRegex(APIError, "unexpected"):
            self.service.submit(self.token, "test", payload | {"unexpected": "not-a-secret"})
    def test_catalog_spans_schemas_but_rows_require_explicit_discovery(self):
        profile_id = "oracle-catalog-test"
        self.wait(self.service.submit(self.token, "test", {"profile_id": profile_id, "config": config(), "timeout": 15}))
        self.service.connect_profile(self.token, profile_id)
        page = self.wait(self.service.submit(self.token, "catalog", {"profile_id": profile_id, "cursor": None, "page_size": 2, "timeout": 15}))
        self.assertEqual(page["state"], "read_completed")
        self.assertEqual({x["schema"] for x in page["result"]["objects"]}, {"BIDPITDBA", "QA_SCHEMA"})
        self.assertFalse(page["result"]["etl_published"])
        with self.assertRaises(APIError): self.service.submit(self.token, "discover", {"profile_id": profile_id, "table": "DP_WIP_DATA", "timeout": 15})
        with self.assertRaises(APIError): self.service.submit(self.token, "discover", {"profile_id": profile_id, "schema": "BIDPITDBA", "table": "DP_WIP_DATA;DELETE", "timeout": 15})
        with self.assertRaises(APIError): self.service.submit(self.token, "sample", {"profile_id": profile_id, "schema": "BIDPITDBA", "table": "DP_WIP_DATA", "timeout": 15, "sample_rows": 5, "batch_size": 5, "columns": ["LOT_NO"], "budget_ack": True})
        discovered = self.wait(self.service.submit(self.token, "discover", {"profile_id": profile_id, "schema": "BIDPITDBA", "table": "DP_WIP_DATA", "timeout": 15}))
        self.assertEqual(discovered["state"], "read_completed")
        sampled = self.wait(self.service.submit(self.token, "sample", {"profile_id": profile_id, "schema": "BIDPITDBA", "table": "DP_WIP_DATA", "timeout": 15, "sample_rows": 5, "batch_size": 5, "columns": ["LOT_NO"], "budget_ack": True}))
        self.assertEqual(sampled["result"]["sample_count"], 1)

    def test_bounded_extract_load_requires_discovery_primary_key_and_upserts_to_local_sqlite(self):
        profile_id = "local-load-profile"
        self.wait(self.service.submit(self.token, "test", {"profile_id": profile_id, "config": config(), "timeout": 15}))
        self.service.connect_profile(self.token, profile_id)
        discovered = self.wait(self.service.submit(self.token, "discover", {"profile_id": profile_id, "schema": "BIDPITDBA", "table": "DP_WIP_DATA", "timeout": 15}))
        self.assertEqual(discovered["state"], "read_completed")
        request = {"profile_id": profile_id, "schema": "BIDPITDBA", "table": "DP_WIP_DATA",
                   "timeout": 15, "row_limit": 5, "columns": ["LOT_NO"], "budget_ack": True}
        loaded = self.wait(self.service.submit(self.token, "extract_load", request))
        self.assertEqual(loaded["state"], "read_completed")
        self.assertEqual(loaded["result"]["rows_received"], 1)
        self.assertEqual(loaded["result"]["primary_keys"], ["LOT_NO"])
        self.assertEqual(self.service.local_target_status(self.token)["tables"][f"{profile_id}|BIDPITDBA|DP_WIP_DATA"]["target_rows"], 1)
        preview = self.service.local_target_preview(self.token, profile_id, "BIDPITDBA", "DP_WIP_DATA", 100)
        self.assertEqual(preview["columns"], ["LOT_NO"])
        self.assertEqual(preview["rows"], [["LOT-1"]])
        with self.assertRaises(APIError):
            self.service.local_target_preview(self.token, profile_id, "BIDPITDBA", "NOT_LOADED", 100)
        self.assertNotIn("LOT-1", json.dumps(loaded))
        expanded = self.wait(self.service.submit(self.token, "extract_load", request | {"row_limit": 101}))
        self.assertEqual(expanded["result"]["row_limit"], 101)
        with self.assertRaises(APIError):
            self.service.submit(self.token, "extract_load", request | {"row_limit": 2_147_483_648})

    def test_column_key_search_uses_loaded_visible_catalog_and_selects_matching_object_types(self):
        profile_id = "column-key-search"
        self.wait(self.service.submit(self.token, "test", {"profile_id": profile_id, "config": config(), "timeout": 15}))
        self.service.connect_profile(self.token, profile_id)
        catalog = self.wait(self.service.submit(self.token, "catalog", {
            "profile_id": profile_id, "cursor": None, "page_size": 100, "timeout": 15,
        }))
        self.assertEqual(catalog["state"], "read_completed")
        common = {"profile_id": profile_id, "keynames": ["lot_no", "ORDER_NO"], "timeout": 15}
        all_keys = self.wait(self.service.submit(self.token, "match_columns", common | {"match_mode": "all"}))
        self.assertEqual(all_keys["state"], "read_completed")
        self.assertEqual([(o["schema"], o["name"], o["kind"]) for o in all_keys["result"]["objects"]],
                         [("QA_SCHEMA", "LOT_QC", "VIEW")])
        any_key = self.wait(self.service.submit(self.token, "match_columns", common | {"match_mode": "any"}))
        self.assertEqual({(o["schema"], o["name"]) for o in any_key["result"]["objects"]},
                         {("BIDPITDBA", "DP_WIP_DATA"), ("QA_SCHEMA", "LOT_QC")})
        self.assertFalse(any_key["result"]["etl_published"])
        with self.assertRaises(APIError):
            self.service.submit(self.token, "match_columns", common | {"match_mode": "all", "keynames": ["X;DELETE"]})

    def test_catalog_snapshot_and_discovered_metadata_are_server_persistent(self):
        profile_id = "persistent-profile"
        root = Path(__file__).resolve().parents[1] / ".test-temp"
        root.mkdir(exist_ok=True)
        store_path = root / f"catalog-{time.time_ns()}.sqlite3"
        store = CatalogStore(store_path)
        service = Service(PASSWORD, factory=self.service.factory, catalog_store=store)
        try:
            token, _ = service.login(PASSWORD)
            tested = service.submit(token, "test", {"profile_id": profile_id, "config": config(), "timeout": 15})
            job = self._wait(service, token, tested)
            self.assertEqual(job["state"], "read_completed")
            service.connect_profile(token, profile_id)
            receipt = service.submit(token, "catalog", {"profile_id": profile_id, "cursor": None, "page_size": 100, "timeout": 15})
            self.assertEqual(self._wait(service, token, receipt)["state"], "read_completed")
            discover = service.submit(token, "discover", {"profile_id": profile_id, "schema": "BIDPITDBA", "table": "DP_WIP_DATA", "timeout": 15})
            self.assertEqual(self._wait(service, token, discover)["state"], "read_completed")
            cached = service.catalog_cache(token, profile_id)
            self.assertEqual(cached["object_count"], 2)
            self.assertEqual(len(cached["metadata"]), 1)
            self.assertNotIn("rows", str(cached))
        finally:
            service.close()
            for candidate in root.glob(store_path.name + "*"):
                candidate.unlink(missing_ok=True)

    @staticmethod
    def _wait(service, token, receipt):
        for _ in range(100):
            job = service.job(token, receipt["job_id"])
            if job["state"] != "running": return job
            time.sleep(.01)
        raise AssertionError("Worker did not finish")
    def test_selected_scalar_columns_and_budget(self):
        state = self.service.session(self.token)
        state.update(tested=True, config=config())
        state["metadata"][("BIDPITDBA", "DP_WIP_DATA")] = {"object": [("BIDPITDBA","DP_WIP_DATA","TABLE")], "columns": [("LOT_NO",1,"VARCHAR2","N"),("PAYLOAD",2,"CLOB","Y")]}
        base = {"schema":"BIDPITDBA", "table":"DP_WIP_DATA", "timeout": 15, "sample_rows": 5, "batch_size": 5, "columns": ["LOT_NO"], "budget_ack": True}
        for change in ({"columns": ["PAYLOAD"]}, {"sample_rows": 101}, {"budget_ack": False}):
            with self.assertRaises(APIError): self.service.submit(self.token, "sample", base | change)
        self.assertEqual(self.wait(self.service.submit(self.token, "sample", base))["state"], "read_completed")

    def test_bounded_preview_can_read_explicitly_discovered_view(self):
        state = self.service.session(self.token)
        state.update(tested=True, config=config())
        state["metadata"][("BIDPITDBA", "LOT_VIEW")] = {
            "object": [["BIDPITDBA", "LOT_VIEW", "VIEW"]],
            "columns": [["LOT_NO", 1, "VARCHAR2", "N"]],
        }
        request = {"schema": "BIDPITDBA", "table": "LOT_VIEW", "timeout": 15,
                   "sample_rows": 5, "batch_size": 5, "columns": ["LOT_NO"], "budget_ack": True}
        result = self.wait(self.service.submit(self.token, "sample", request))
        self.assertEqual(result["state"], "read_completed")
        self.assertEqual(result["result"]["sample_count"], 1)
    def test_concurrency_and_failed_worker_releases_admission(self):
        entered, release = threading.Event(), threading.Event()
        def factory(c,t):
            def broken():
                entered.set(); release.wait(2)
                raise SourceReadFailed("fixture secret should not leak")
            return broken
        self.service.factory = factory
        receipt = self.service.submit(self.token, "test", {"config": config(), "timeout": 15})
        self.assertTrue(entered.wait(1))
        with self.assertRaises(APIError): self.service.submit(self.token, "test", {"config": config(), "timeout": 15})
        with self.assertRaises(APIError): self.service.logout(self.token)
        release.set()
        job = self.wait(receipt)
        self.assertEqual(job["state"], "failed")
        self.assertNotIn("fixture secret", json.dumps(job))
        self.assertIsNone(self.service.session(self.token)["config"])
        self.assertFalse(self.service.active)
    def test_multiple_profiles_can_stay_connected_and_disconnect_independently(self):
        for profile_id in ("oracle-iot", "oracle-bsm"):
            receipt = self.service.submit(self.token, "test", {"profile_id": profile_id, "config": config(), "timeout": 15})
            self.assertEqual(self.wait(receipt)["state"], "read_completed")
            self.service.connect_profile(self.token, profile_id)
        statuses = self.service.profile_statuses(self.token)
        self.assertTrue(statuses["oracle-iot"]["connected"])
        self.assertTrue(statuses["oracle-bsm"]["connected"])
        self.service.disconnect_profile(self.token, "oracle-iot")
        statuses = self.service.profile_statuses(self.token)
        self.assertNotIn("oracle-iot", statuses)
        self.assertTrue(statuses["oracle-bsm"]["connected"])
    def test_transport_acknowledgement(self):
        with self.assertRaises(APIError): config_validate(config() | {"protocol": "tcp"})
        config_validate(config() | {"protocol": "tcp", "tcp_ack": True})
    def test_session_expiration_and_rate_limit(self):
        self.service.sessions[self.token]["expires"] = 0
        with self.assertRaises(APIError): self.service.session(self.token)
        for _ in range(5):
            try: self.service.login("bad")
            except APIError: pass
        with self.assertRaises(APIError) as caught: self.service.login(PASSWORD)
        self.assertEqual(caught.exception.status, 429)


class HttpsTests(unittest.TestCase):
    def test_authenticated_https_origin_csrf_and_static_allowlist(self):
        service = Service(PASSWORD)
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(service, "placeholder"))
        port = server.server_port
        origin = f"https://localhost:{port}"
        server.RequestHandlerClass = handler_for(service, origin)
        tls_temp = Path(__file__).resolve().parents[1] / ".test-temp" / "tls-temp"
        tls_temp.mkdir(parents=True, exist_ok=True)
        tempfile.tempdir = str(tls_temp)
        context, _ = tls_context(PASSWORD, temp_dir=Path(__file__).resolve().parents[1] / ".test-temp")
        server.socket = context.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        # Certificate bypass is confined to this disposable integration-test client.
        client = http.client.HTTPSConnection("localhost", port, timeout=5, context=ssl._create_unverified_context())
        try:
            client.request("GET", "/"); response=client.getresponse(); shell=response.read().decode()
            self.assertEqual(response.status,200); self.assertIn('id="app"',shell); self.assertIn("real-source-ui.js",shell)
            self.assertIn("script-src 'self' 'unsafe-inline'",response.getheader("Content-Security-Policy"))
            client.request("GET", "/ui-reference-theme.css"); response=client.getresponse(); theme=response.read().decode()
            self.assertEqual(response.status, 200); self.assertIn(".masthead", theme); self.assertIn("#122442", theme)
            client.request("GET","/real-source-ui.js"); response=client.getresponse(); self.assertEqual(response.status,200); self.assertIn("realSourceTest",response.read().decode())
            client.request("GET","/dataset-workflow.js"); response=client.getresponse(); self.assertEqual(response.status,200); self.assertIn("rankDatasetField",response.read().decode())
            client.request("GET","/assets/utac-logo-source.png"); response=client.getresponse(); logo=response.read(); self.assertEqual(response.status,200); self.assertEqual(response.getheader("Content-Type"),"image/png"); self.assertTrue(logo.startswith(b"\x89PNG\r\n\x1a\n"))
            client.request("GET","/live.html"); response=client.getresponse(); response.read(); self.assertEqual(response.status,404)
            client.request("GET", "/api/session"); response=client.getresponse(); response.read()
            self.assertEqual(response.status, 401)
            headers={"Content-Type":"application/json","Origin":origin}
            client.request("POST","/api/login",json.dumps({"passphrase":PASSWORD}),headers)
            response=client.getresponse(); body=json.loads(response.read()); cookie=response.getheader("Set-Cookie")
            self.assertEqual(response.status,200); self.assertIn("Secure; HttpOnly; SameSite=Strict",cookie)
            headers["Cookie"]=cookie.split(";")[0]
            client.request("POST","/api/logout","{}",headers); response=client.getresponse(); response.read()
            self.assertEqual(response.status,403)
            headers["X-CSRF"]=body["csrf"]; headers["Origin"]="https://evil.invalid"
            client.request("POST","/api/logout","{}",headers); response=client.getresponse(); response.read()
            self.assertEqual(response.status,403)
            client.request("GET","/backend/requirements-spike.lock.txt"); response=client.getresponse(); response.read()
            self.assertEqual(response.status,404)
            headers["Origin"]=origin
            client.request("POST","/api/logout","{}",headers); response=client.getresponse(); response.read()
            self.assertEqual(response.status,200)
        finally:
            client.close(); server.shutdown(); server.server_close(); thread.join(); service.close()


if __name__ == "__main__": unittest.main()
