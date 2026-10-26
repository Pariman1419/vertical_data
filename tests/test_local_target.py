import tempfile
import unittest
import sqlite3
from contextlib import closing
from pathlib import Path

from backend.spike.target_store import SQLiteTargetStore


class LocalTargetTests(unittest.TestCase):
    def test_primary_key_upsert_is_durable_and_status_is_reported(self):
        test_root = Path(__file__).resolve().parents[1] / ".test-temp"
        test_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=test_root) as directory:
            store = SQLiteTargetStore(Path(directory) / "local.sqlite3")
            columns = [{"name": "LOT_NO", "type": "VARCHAR2"},
                       {"name": "REV", "type": "NUMBER"}]
            first = store.load_rows(target_table="T_FIXTURE", columns=columns,
                                    primary_keys=["LOT_NO"], rows=[("L-1", 1), ("L-2", 1)])
            store.record_source_status(source_id="source-key", schema="S", object_name="T",
                                       target_table="T_FIXTURE", last_load_at=first["last_load_at"],
                                       last_received=first["rows_received"], target_rows=first["target_rows"])
            second = store.load_rows(target_table="T_FIXTURE", columns=columns,
                                     primary_keys=["LOT_NO"], rows=[("L-1", 2)])
            with closing(sqlite3.connect(store.path)) as db:
                values = db.execute('SELECT LOT_NO,REV FROM "T_FIXTURE" ORDER BY LOT_NO').fetchall()
            self.assertEqual(values, [("L-1", 2), ("L-2", 1)])
            self.assertEqual(second["target_rows"], 2)
            self.assertEqual(store.statuses()["source-key|S|T"]["target_rows"], 2)
            preview = store.preview(target_table="T_FIXTURE", limit=1)
            self.assertEqual(preview["columns"], ["LOT_NO", "REV"])
            self.assertEqual(preview["rows"], [["L-1", 2]])
            self.assertEqual(preview["object"], "T")

    def test_preview_rejects_unsafe_or_unbounded_request(self):
        test_root = Path(__file__).resolve().parents[1] / ".test-temp"
        test_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=test_root) as directory:
            store = SQLiteTargetStore(Path(directory) / "local.sqlite3")
            with self.assertRaises(ValueError):
                store.preview(target_table='T_FIXTURE"; DROP TABLE X; --', limit=1)
            with self.assertRaises(ValueError):
                store.preview(target_table="T_FIXTURE", limit=1000)

    def test_load_requires_primary_key_and_row_shape(self):
        test_root = Path(__file__).resolve().parents[1] / ".test-temp"
        test_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=test_root) as directory:
            store = SQLiteTargetStore(Path(directory) / "local.sqlite3")
            column = [{"name": "C", "type": "VARCHAR2"}]
            with self.assertRaises(ValueError):
                store.load_rows(target_table="T_FIXTURE", columns=column, primary_keys=[], rows=[])
            with self.assertRaises(ValueError):
                store.load_rows(target_table="T_FIXTURE", columns=column, primary_keys=["C"], rows=[("a", "b")])


if __name__ == "__main__":
    unittest.main()
