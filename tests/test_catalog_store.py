import uuid
import unittest
from pathlib import Path

from backend.spike.catalog_store import CatalogStore


class CatalogStoreTests(unittest.TestCase):
    def test_snapshot_survives_store_reopen_and_metadata_invalidates_on_ddl(self):
        root = Path(__file__).resolve().parents[1] / ".test-temp"
        root.mkdir(exist_ok=True)
        path = root / f"catalog-{uuid.uuid4().hex}.sqlite3"
        store = None
        try:
            store = CatalogStore(path)
            source = "one-way-hash"
            snapshot = store.begin_refresh(source)
            store.append_page(snapshot, [{"schema": "S", "name": "T", "kind": "TABLE", "last_ddl_time": "v1"}])
            store.complete_refresh(snapshot)
            payload = {"object": [["S", "T", "TABLE"]], "columns": [["ID", 1, "NUMBER", "N"]],
                       "keys": [], "foreign_keys": [], "limitations": "metadata only"}
            store.save_metadata(source, "S", "T", "TABLE", "v1", payload)
            store.close()

            store = CatalogStore(path)
            cached = store.current_snapshot(source)
            self.assertTrue(cached["available"])
            self.assertEqual(cached["objects"][0]["last_ddl_time"], "v1")
            self.assertEqual(store.get_metadata(source, "S", "T", "TABLE", "v1"), payload)

            refreshed = store.begin_refresh(source)
            store.append_page(refreshed, [{"schema": "S", "name": "T", "kind": "TABLE", "last_ddl_time": "v2"}])
            store.complete_refresh(refreshed)
            self.assertIsNone(store.get_metadata(source, "S", "T", "TABLE", "v2"))
            self.assertIsNone(store.get_metadata(source, "S", "T", "TABLE", "v1"))
            store.close()
        finally:
            if store is not None:
                try: store.close()
                except Exception: pass
            for candidate in root.glob(path.stem + "*"):
                candidate.unlink(missing_ok=True)

    def test_incomplete_refresh_does_not_replace_last_complete_snapshot(self):
        store = CatalogStore(":memory:")
        source = "stable-key"
        first = store.begin_refresh(source)
        store.append_page(first, [{"schema": "S", "name": "OLD", "kind": "TABLE"}])
        store.complete_refresh(first)
        second = store.begin_refresh(source)
        store.append_page(second, [{"schema": "S", "name": "NEW", "kind": "TABLE"}])
        self.assertEqual(store.current_snapshot(source)["objects"][0]["name"], "OLD")
        store.fail_refresh(second)
        self.assertEqual(store.current_snapshot(source)["objects"][0]["name"], "OLD")
        store.close()
