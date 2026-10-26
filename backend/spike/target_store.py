"""Local SQLite analytics target for explicitly bounded Oracle pilot loads."""
import sqlite3
import threading
import re
from datetime import datetime, timezone
from contextlib import closing


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_$#]{0,127}", value):
        raise ValueError("Unsupported target identifier")
    return '"' + value.replace('"', '""') + '"'


def sqlite_type(oracle_type):
    value = str(oracle_type or "").upper()
    if "NUMBER" in value or "FLOAT" in value:
        return "NUMERIC"
    if value in ("DATE",) or value.startswith("TIMESTAMP"):
        return "TEXT"
    if value in ("BLOB", "RAW", "LONG RAW"):
        return "BLOB"
    return "TEXT"


class SQLiteTargetStore:
    def __init__(self, path):
        self.path = str(path)
        self.lock = threading.RLock()

    def load_rows(self, *, target_table, columns, primary_keys, rows):
        column_names = {column.get("name") for column in columns if isinstance(column, dict)}
        if not columns or not primary_keys or not set(primary_keys).issubset(column_names):
            raise ValueError("A discovered Primary Key and all its columns are required")
        if any(len(row) != len(columns) for row in rows):
            raise ValueError("Extracted row width does not match metadata")
        table = identifier(target_table)
        column_sql = ", ".join(f"{identifier(c['name'])} {sqlite_type(c['type'])}" for c in columns)
        pk_sql = ", ".join(identifier(c) for c in primary_keys)
        names = ", ".join(identifier(c["name"]) for c in columns)
        placeholders = ", ".join("?" for _ in columns)
        updates = ", ".join(f"{identifier(c['name'])}=excluded.{identifier(c['name'])}"
                             for c in columns if c["name"] not in primary_keys)
        sql = f"INSERT INTO {table} ({names}) VALUES ({placeholders}) ON CONFLICT ({pk_sql}) "
        sql += f"DO UPDATE SET {updates}" if updates else "DO NOTHING"
        with self.lock, closing(sqlite3.connect(self.path, timeout=15)) as db:
            with db:
                db.execute("PRAGMA busy_timeout=15000")
                db.execute("CREATE TABLE IF NOT EXISTS _utl_table_registry (source_id TEXT NOT NULL, schema_name TEXT NOT NULL, object_name TEXT NOT NULL, target_table TEXT NOT NULL UNIQUE, last_load_at TEXT NOT NULL, last_received INTEGER NOT NULL, target_rows INTEGER NOT NULL, PRIMARY KEY(source_id,schema_name,object_name))")
                db.execute(f"CREATE TABLE IF NOT EXISTS {table} ({column_sql}, PRIMARY KEY ({pk_sql}))")
                before = db.total_changes
                db.executemany(sql, rows)
                affected = db.total_changes - before
                total = db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                result = {"rows_received": len(rows), "rows_written": affected, "target_rows": total,
                          "last_load_at": datetime.now(timezone.utc).isoformat()}
        return result

    def record_source_status(self, *, source_id, schema, object_name, target_table, last_load_at, last_received, target_rows):
        with self.lock, closing(sqlite3.connect(self.path, timeout=15)) as db:
            with db:
                db.execute("CREATE TABLE IF NOT EXISTS _utl_table_registry (source_id TEXT NOT NULL, schema_name TEXT NOT NULL, object_name TEXT NOT NULL, target_table TEXT NOT NULL UNIQUE, last_load_at TEXT NOT NULL, last_received INTEGER NOT NULL, target_rows INTEGER NOT NULL, PRIMARY KEY(source_id,schema_name,object_name))")
                db.execute("INSERT INTO _utl_table_registry VALUES(?,?,?,?,?,?,?) ON CONFLICT(source_id,schema_name,object_name) DO UPDATE SET target_table=excluded.target_table,last_load_at=excluded.last_load_at,last_received=excluded.last_received,target_rows=excluded.target_rows",
                           (source_id, schema, object_name, target_table, last_load_at, last_received, target_rows))

    def statuses(self):
        with self.lock:
            try:
                with closing(sqlite3.connect(self.path, timeout=5)) as db:
                    rows = db.execute("SELECT source_id,schema_name,object_name,last_load_at,last_received,target_rows FROM _utl_table_registry").fetchall()
            except sqlite3.OperationalError:
                return {}
        return {f"{source}|{schema}|{name}": {"last_load_at": loaded, "rows_received": received, "target_rows": total}
                for source, schema, name, loaded, received, total in rows}

    def preview(self, *, target_table, limit=100):
        table = identifier(target_table)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Preview limit must be between 1 and 100")
        with self.lock, closing(sqlite3.connect(self.path, timeout=5)) as db:
            db.row_factory = sqlite3.Row
            registry = db.execute(
                "SELECT schema_name,object_name,target_table,target_rows,last_load_at "
                "FROM _utl_table_registry WHERE target_table=?", (target_table,)
            ).fetchone()
            if registry is None:
                raise ValueError("Stored table not found")
            cursor = db.execute(f"SELECT * FROM {table} LIMIT ?", (limit,))
            columns = [item[0] for item in cursor.description]
            rows = [[value.isoformat() if isinstance(value, datetime) else value
                     for value in row] for row in cursor.fetchall()]
        return {"schema": registry[0], "object": registry[1], "target_rows": registry[3],
                "last_load_at": registry[4], "columns": columns, "rows": rows,
                "preview_limit": limit}
