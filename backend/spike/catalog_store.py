"""Durable Oracle metadata snapshots; intentionally stores no credentials or row data."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import threading
import uuid


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class CatalogStore:
    def __init__(self, path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.path, check_same_thread=False, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        if self.path != ":memory:":
            self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS catalog_snapshots (
                id TEXT PRIMARY KEY, source_key TEXT NOT NULL, state TEXT NOT NULL,
                started_at TEXT NOT NULL, completed_at TEXT, object_count INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS catalog_snapshots_source ON catalog_snapshots(source_key, state, completed_at);
            CREATE TABLE IF NOT EXISTS catalog_heads (
                source_key TEXT PRIMARY KEY, snapshot_id TEXT NOT NULL REFERENCES catalog_snapshots(id)
            );
            CREATE TABLE IF NOT EXISTS catalog_objects (
                snapshot_id TEXT NOT NULL REFERENCES catalog_snapshots(id) ON DELETE CASCADE,
                schema_name TEXT NOT NULL, object_name TEXT NOT NULL, object_type TEXT NOT NULL,
                last_ddl_time TEXT,
                PRIMARY KEY(snapshot_id, schema_name, object_name, object_type)
            );
            CREATE TABLE IF NOT EXISTS object_metadata (
                source_key TEXT NOT NULL, schema_name TEXT NOT NULL, object_name TEXT NOT NULL,
                object_type TEXT NOT NULL, last_ddl_time TEXT, payload TEXT NOT NULL, updated_at TEXT NOT NULL,
                PRIMARY KEY(source_key, schema_name, object_name, object_type)
            );
        """)
        self.db.commit()

    def begin_refresh(self, source_key):
        with self.lock, self.db:
            pending = self.db.execute("SELECT 1 FROM catalog_snapshots WHERE source_key=? AND state='loading'", (source_key,)).fetchone()
            if pending:
                raise RuntimeError("A catalog refresh is already running for this Oracle identity")
            snapshot_id = uuid.uuid4().hex
            self.db.execute("INSERT INTO catalog_snapshots(id,source_key,state,started_at) VALUES(?,?,'loading',?)",
                            (snapshot_id, source_key, utc_now()))
            return snapshot_id

    def append_page(self, snapshot_id, objects):
        with self.lock, self.db:
            row = self.db.execute("SELECT state FROM catalog_snapshots WHERE id=?", (snapshot_id,)).fetchone()
            if row is None or row["state"] != "loading":
                raise RuntimeError("Catalog refresh is no longer active")
            self.db.executemany("""INSERT OR REPLACE INTO catalog_objects
                (snapshot_id,schema_name,object_name,object_type,last_ddl_time) VALUES(?,?,?,?,?)""",
                [(snapshot_id, o["schema"], o["name"], o["kind"], o.get("last_ddl_time")) for o in objects])

    def complete_refresh(self, snapshot_id):
        with self.lock, self.db:
            row = self.db.execute("SELECT source_key FROM catalog_snapshots WHERE id=? AND state='loading'", (snapshot_id,)).fetchone()
            if row is None:
                raise RuntimeError("Catalog refresh is no longer active")
            source_key = row["source_key"]
            completed = utc_now()
            count = self.db.execute("SELECT COUNT(*) FROM catalog_objects WHERE snapshot_id=?", (snapshot_id,)).fetchone()[0]
            self.db.execute("UPDATE catalog_snapshots SET state='complete',completed_at=?,object_count=? WHERE id=?",
                            (completed, count, snapshot_id))
            # Metadata remains valid only for unchanged catalog objects. Oracle LAST_DDL_TIME
            # lets an explicit catalog reload invalidate changed/dropped tables and views.
            self.db.execute("""DELETE FROM object_metadata WHERE source_key=? AND NOT EXISTS (
                SELECT 1 FROM catalog_objects o WHERE o.snapshot_id=?
                AND o.schema_name=object_metadata.schema_name AND o.object_name=object_metadata.object_name
                AND o.object_type=object_metadata.object_type
                AND COALESCE(o.last_ddl_time,'')=COALESCE(object_metadata.last_ddl_time,''))""",
                (source_key, snapshot_id))
            self.db.execute("INSERT INTO catalog_heads(source_key,snapshot_id) VALUES(?,?) ON CONFLICT(source_key) DO UPDATE SET snapshot_id=excluded.snapshot_id",
                            (source_key, snapshot_id))
            return {"snapshot_id": snapshot_id, "refreshed_at": completed, "object_count": count}

    def fail_refresh(self, snapshot_id):
        with self.lock, self.db:
            self.db.execute("UPDATE catalog_snapshots SET state='failed' WHERE id=? AND state='loading'", (snapshot_id,))

    def current_snapshot(self, source_key):
        with self.lock:
            row = self.db.execute("""SELECT s.id,s.completed_at,s.object_count FROM catalog_heads h
                JOIN catalog_snapshots s ON s.id=h.snapshot_id WHERE h.source_key=? AND s.state='complete'""", (source_key,)).fetchone()
            if row is None:
                return None
            objects = [dict(o) for o in self.db.execute("SELECT schema_name AS schema,object_name AS name,object_type AS kind,last_ddl_time FROM catalog_objects WHERE snapshot_id=? ORDER BY schema_name,object_name,object_type", (row["id"],))]
            metadata = [dict(m) for m in self.db.execute("SELECT schema_name,object_name,object_type,last_ddl_time,payload,updated_at FROM object_metadata WHERE source_key=?", (source_key,))]
            return {"available": True, "snapshot_id": row["id"], "refreshed_at": row["completed_at"],
                    "object_count": row["object_count"], "objects": objects, "metadata": metadata}

    def get_metadata(self, source_key, schema, name, kind, last_ddl_time):
        with self.lock:
            row = self.db.execute("""SELECT payload FROM object_metadata WHERE source_key=? AND schema_name=?
                AND object_name=? AND object_type=? AND COALESCE(last_ddl_time,'')=COALESCE(?,'')""",
                (source_key, schema, name, kind, last_ddl_time)).fetchone()
            return json.loads(row["payload"]) if row else None

    def save_metadata(self, source_key, schema, name, kind, last_ddl_time, payload):
        with self.lock, self.db:
            self.db.execute("""INSERT INTO object_metadata(source_key,schema_name,object_name,object_type,last_ddl_time,payload,updated_at)
                VALUES(?,?,?,?,?,?,?) ON CONFLICT(source_key,schema_name,object_name,object_type) DO UPDATE SET
                last_ddl_time=excluded.last_ddl_time,payload=excluded.payload,updated_at=excluded.updated_at""",
                (source_key, schema, name, kind, last_ddl_time,
                 json.dumps(payload, ensure_ascii=False, separators=(",", ":")), utc_now()))

    def close(self):
        with self.lock:
            self.db.close()
