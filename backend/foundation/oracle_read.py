"""Oracle read-only query adapter, not enabled in UI or the synthetic Worker.

An approved runtime supplies a fresh, authenticated DB-API connection. This
module never builds connection strings, collects/stores secrets or imports a
driver. Application authentication/credential transport remain prerequisites.
"""
from contextlib import contextmanager
import re
import socket
import ssl
import time
from datetime import date, datetime
from decimal import Decimal
from .read_budget import BudgetError, ReadGate


class SourceReadFailed(Exception):
    """Sanitized failure; never expose driver message/connection string."""


_ORACLE_CODES = {
    "ORA-01017": "Oracle rejected the username/password (ORA-01017). Re-enter credentials locally and confirm account status with DBA.",
    "ORA-28000": "Oracle account is locked (ORA-28000). Contact DBA; no automatic retry was made.",
    "ORA-12514": "Listener does not recognize this Service Name (ORA-12514). Confirm Service Name with DBA.",
    "ORA-12505": "Listener does not recognize this SID (ORA-12505). Confirm SID with DBA.",
    "ORA-12541": "Oracle listener is unreachable (ORA-12541). Check host, port, VPN and listener availability.",
    "ORA-12170": "Oracle connection timed out (ORA-12170). Check VPN, firewall, endpoint and timeout.",
    "ORA-29024": "Oracle TLS certificate validation failed (ORA-29024). Use the DBA-approved certificate/wallet; validation remains enabled.",
    "DPY-6001": "Oracle service name is unknown (DPY-6001). Confirm Service Name/SID and listener configuration with DBA.",
    "DPY-3010": "This Oracle server version is unsupported by the current Thin driver (DPY-3010). Confirm server version and an approved runtime with DBA.",
    "DPY-3015": "The account uses a password verifier unsupported by this driver mode (DPY-3015). Ask DBA for an approved authentication/runtime option; do not change Source settings here.",
    "DPY-3001": "The server requires Oracle Native Network Encryption (DPY-3001), which this Thin-mode connector does not support. Confirm an approved transport/runtime with DBA.",
    "DPY-4011": "Oracle/network closed the connection (DPY-4011). Check endpoint, VPN and server/network policy.",
    "DPY-4024": "Oracle round-trip timed out (DPY-4024). Check network latency and approved timeout.",
    "DPY-6005": "Could not connect to Oracle (DPY-6005). Check host, port, Service Name/SID, VPN and listener.",
}


def safe_source_error(exc):
    """Return a safe category/code only; never surface the driver's raw message."""
    if isinstance(exc, (ssl.SSLCertVerificationError, ssl.SSLError)):
        return "TCPS certificate/TLS negotiation failed. Confirm the DBA-approved certificate or wallet; validation remains enabled."
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "Oracle connection timed out. Check VPN, endpoint and approved timeout."
    if isinstance(exc, ConnectionRefusedError):
        return "Oracle listener refused the connection. Check host, port and listener availability."
    if isinstance(exc, socket.gaierror):
        return "Oracle host name could not be resolved. Check host and VPN/DNS."
    # Parse only an allowlisted diagnostic token from driver text. Never return its message.
    raw = str(exc).upper()
    codes = re.findall(r"(?<![A-Z0-9])(?:ORA-\d{5}|DPY-\d{4}|DPI-\d{4})(?!\d)", raw)
    for code in codes:
        if code in _ORACLE_CODES:
            return _ORACLE_CODES[code]
        if code.startswith(("ORA-", "DPY-", "DPI-")):
            return f"Oracle connection/read failed ({code}). Check endpoint, protocol, access and runtime; diagnostic details are hidden."
    return "Oracle connection/read failed (diagnostic details hidden). Check protocol, certificate, endpoint, access and timeout."


def quote_identifier(value):
    # Deliberately reject unusual names until connector policy is reviewed.
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_$#]{0,127}", value):
        raise BudgetError("Unsupported Oracle identifier")
    return '"' + value + '"'


class OracleReadAdapter:
    def __init__(self, connection_factory, budget, *, gate, clock=time.monotonic):
        if not isinstance(gate, ReadGate):
            raise BudgetError("Shared admission gate required")
        self.factory, self.budget, self.gate, self.clock = connection_factory, budget, gate, clock

    @contextmanager
    def session(self):
        with self.gate.operation():
            cn = None
            try:
                cn = self.factory()  # Factory must enforce login/TLS timeout.
                cn.autocommit = False
                cn.call_timeout = self.budget.timeout_seconds * 1000
                with cn.cursor() as cursor:
                    cursor.execute("SET TRANSACTION READ ONLY")
                yield cn, self.clock()
            except BudgetError:
                raise
            except SourceReadFailed:
                raise
            except Exception as exc:
                raise SourceReadFailed(safe_source_error(exc)) from None
            finally:
                if cn is not None:
                    try:
                        cn.close()  # Never commit; dispose read-only transaction.
                    except Exception:
                        pass

    def _query(self, cn, started, sql, binds, cap):
        rows = []
        with cn.cursor() as cursor:
            cursor.arraysize = self.budget.batch_size
            cursor.prefetchrows = 0
            remaining = self.budget.timeout_seconds - (self.clock() - started)
            if remaining <= 0:
                raise BudgetError("Sample deadline exceeded")
            cn.call_timeout = max(1, int(remaining * 1000))
            cursor.execute(sql, binds)
            while len(rows) < cap:
                remaining = self.budget.timeout_seconds - (self.clock() - started)
                if remaining <= 0:
                    raise BudgetError("Sample deadline exceeded")
                cn.call_timeout = max(1, int(remaining * 1000))
                batch = cursor.fetchmany(min(self.budget.batch_size, cap - len(rows)))
                if self.clock() - started >= self.budget.timeout_seconds:
                    raise BudgetError("Sample deadline exceeded")
                if not batch:
                    break
                rows.extend(batch)
        return rows

    def test_connection(self):
        with self.session() as (cn, started):
            rows = self._query(cn, started,
                "SELECT SYS_CONTEXT('USERENV','SESSION_USER'), SYS_CONTEXT('USERENV','DB_NAME') FROM DUAL",
                {}, 1)
            if len(rows) != 1:
                raise SourceReadFailed("Runtime identity unavailable")
            return {"is_simulation": False, "database_connected": True,
                    "etl_published": False, "identity": rows[0][0],
                    "database": rows[0][1], "version": cn.version}

    def discover_catalog_page(self, cursor=None):
        """Page through object metadata visible to this Oracle identity only.

        ALL_OBJECTS is privilege-filtered by Oracle. No row data is read and no
        ALL_USERS/DBA_* catalog is used. Keyset pagination avoids COUNT/OFFSET.
        """
        if not self.budget.catalog_only:
            raise BudgetError("Catalog-only read budget required")
        if cursor is None:
            cursor = {"owner": "", "name": "", "kind": "", "object_id": 0}
        if not isinstance(cursor, dict) or set(cursor) != {"owner", "name", "kind", "object_id"}:
            raise BudgetError("Invalid catalog cursor")
        for key in ("owner", "name", "kind"):
            value = cursor[key]
            if not isinstance(value, str) or len(value) > 128 or any(ord(ch) < 32 for ch in value):
                raise BudgetError("Invalid catalog cursor")
        if type(cursor["object_id"]) is not int or cursor["object_id"] < 0:
            raise BudgetError("Invalid catalog cursor")
        first_page = cursor == {"owner": "", "name": "", "kind": "", "object_id": 0}
        binds = {"cap": self.budget.batch_size}
        where = "WHERE OBJECT_TYPE IN ('TABLE','VIEW','MATERIALIZED VIEW') "
        if not first_page:
            # Oracle treats zero-length strings as NULL. Never bind empty cursor
            # strings into the first-page keyset predicate: comparisons with
            # NULL would filter out every row.
            binds.update(owner=cursor["owner"], name=cursor["name"], kind=cursor["kind"],
                         object_id=cursor["object_id"])
            where += ("AND (OWNER > :owner OR (OWNER = :owner AND OBJECT_NAME > :name) OR "
                      "(OWNER = :owner AND OBJECT_NAME = :name AND OBJECT_TYPE > :kind) OR "
                      "(OWNER = :owner AND OBJECT_NAME = :name AND OBJECT_TYPE = :kind AND OBJECT_ID > :object_id)) ")
        sql = ("SELECT OWNER, OBJECT_NAME, OBJECT_TYPE, OBJECT_ID, LAST_DDL_TIME FROM ALL_OBJECTS "
               + where + "ORDER BY OWNER, OBJECT_NAME, OBJECT_TYPE, OBJECT_ID FETCH NEXT :cap ROWS ONLY")
        with self.session() as (cn, started):
            rows = self._query(cn, started, sql, binds, self.budget.batch_size)
        objects = [{"schema": row[0], "name": row[1], "kind": row[2],
                    "last_ddl_time": row[4].isoformat() if len(row) > 4 and hasattr(row[4], "isoformat")
                    else str(row[4]) if len(row) > 4 and row[4] is not None else None} for row in rows]
        next_cursor = ({"owner": rows[-1][0], "name": rows[-1][1], "kind": rows[-1][2], "object_id": rows[-1][3]}
                       if len(rows) == self.budget.batch_size else None)
        return {"objects": objects, "next_cursor": next_cursor,
                "page_size": self.budget.batch_size, "is_simulation": False,
                "etl_published": False,
                "limitations": "Catalog metadata visible to this Oracle identity only; keyset page is not a cross-page snapshot; no table rows or full-catalog count read."}

    def find_objects_by_columns(self, keynames, match_mode):
        """Find visible objects by exact column names using Oracle dictionary metadata only."""
        if not self.budget.catalog_only:
            raise BudgetError("Catalog-only read budget required")
        if not isinstance(keynames, list) or not 1 <= len(keynames) <= 20:
            raise BudgetError("Enter 1..20 column names")
        if match_mode not in ("all", "any"):
            raise BudgetError("Invalid column match mode")
        normalized = []
        for value in keynames:
            if not isinstance(value, str):
                raise BudgetError("Invalid column name")
            name = value.strip().upper()
            quote_identifier(name)
            if name not in normalized:
                normalized.append(name)
        if not normalized:
            raise BudgetError("Enter at least one column name")
        binds = {f"key{i}": name for i, name in enumerate(normalized)}
        binds["cap"] = 10000
        placeholders = ",".join(f":key{i}" for i in range(len(normalized)))
        sql = ("SELECT OWNER, TABLE_NAME, COLUMN_NAME FROM ALL_TAB_COLUMNS "
               f"WHERE COLUMN_NAME IN ({placeholders}) "
               "ORDER BY OWNER, TABLE_NAME, COLUMN_ID FETCH NEXT :cap ROWS ONLY")
        with self.session() as (cn, started):
            rows = self._query(cn, started, sql, binds, 10000)
        grouped = {}
        for owner, table, column in rows:
            grouped.setdefault((owner, table), set()).add(column.upper())
        expected = set(normalized)
        objects = [{"schema": owner, "name": table, "matched_columns": sorted(found)}
                   for (owner, table), found in sorted(grouped.items())
                   if (expected <= found if match_mode == "all" else bool(expected & found))]
        return {"objects": objects, "truncated": len(rows) == 10000,
                "column_names": normalized, "match_mode": match_mode,
                "is_simulation": False, "etl_published": False,
                "limitations": "Exact column-name search in ALL_TAB_COLUMNS visible to the current Oracle identity; metadata only, capped at 10,000 column matches; no table rows read."}

    def discover_table(self, schema, table):
        self.budget.check_table(schema, table)
        quote_identifier(schema)
        quote_identifier(table)
        binds = {"owner": schema, "name": table, "cap": 1000}
        queries = {
            "object": "SELECT OWNER, OBJECT_NAME, OBJECT_TYPE FROM ALL_OBJECTS WHERE OWNER=:owner AND OBJECT_NAME=:name AND OBJECT_TYPE IN ('TABLE','VIEW','MATERIALIZED VIEW') AND ROWNUM <= :cap",
            "columns": "SELECT COLUMN_NAME, COLUMN_ID, DATA_TYPE, NULLABLE FROM ALL_TAB_COLUMNS WHERE OWNER=:owner AND TABLE_NAME=:name AND ROWNUM <= :cap",
            "keys": "SELECT c.CONSTRAINT_NAME, c.CONSTRAINT_TYPE, cc.COLUMN_NAME, cc.POSITION, c.R_OWNER, c.R_CONSTRAINT_NAME FROM ALL_CONSTRAINTS c JOIN ALL_CONS_COLUMNS cc ON c.OWNER=cc.OWNER AND c.CONSTRAINT_NAME=cc.CONSTRAINT_NAME AND c.TABLE_NAME=cc.TABLE_NAME WHERE c.OWNER=:owner AND c.TABLE_NAME=:name AND c.CONSTRAINT_TYPE IN ('P','R') AND ROWNUM <= :cap",
            "foreign_keys": "SELECT c.CONSTRAINT_NAME, cc.COLUMN_NAME, cc.POSITION, rc.OWNER, rc.TABLE_NAME, rcc.COLUMN_NAME FROM ALL_CONSTRAINTS c JOIN ALL_CONS_COLUMNS cc ON c.OWNER=cc.OWNER AND c.CONSTRAINT_NAME=cc.CONSTRAINT_NAME AND c.TABLE_NAME=cc.TABLE_NAME LEFT JOIN ALL_CONSTRAINTS rc ON rc.OWNER=c.R_OWNER AND rc.CONSTRAINT_NAME=c.R_CONSTRAINT_NAME LEFT JOIN ALL_CONS_COLUMNS rcc ON rcc.OWNER=rc.OWNER AND rcc.CONSTRAINT_NAME=rc.CONSTRAINT_NAME AND rcc.POSITION=cc.POSITION WHERE c.OWNER=:owner AND c.TABLE_NAME=:name AND c.CONSTRAINT_TYPE='R' AND ROWNUM <= :cap",
        }
        with self.session() as (cn, started):
            object_rows = self._query(cn, started, queries["object"], binds, 10)
            if not object_rows:
                raise SourceReadFailed("Object is not visible to the current Oracle identity")
            result = {"object": object_rows}
            result.update({name: self._query(cn, started, sql, binds, 1000)
                           for name, sql in queries.items() if name != "object"})
        result["limitations"] = "Visible metadata only; empty keys or null FK references may mean restricted visibility. 1000-entry cap may truncate. Referenced objects are metadata only and are not sampled unless separately selected."
        return result

    def sample(self, schema, table, columns):
        self.budget.check_table(schema, table)
        if not isinstance(columns, (tuple, list)) or not 1 <= len(columns) <= 50:
            raise BudgetError("Select 1..50 approved scalar columns")
        names = ', '.join(quote_identifier(c) for c in columns)
        obj = quote_identifier(schema) + '.' + quote_identifier(table)
        # Nested stop-key; no ORDER BY/DISTINCT/count or user-provided SQL.
        sql = f"SELECT {names} FROM {obj} WHERE ROWNUM <= :row_cap"
        with self.session() as (cn, started):
            rows = self._query(cn, started, sql, {"row_cap": self.budget.sample_rows}, self.budget.sample_rows)
            # Never dereference LOBs or stringify driver-specific objects.
            def scalar(v):
                if isinstance(v, (date, datetime)): return v.isoformat()
                if isinstance(v, Decimal): return str(v)
                if type(v) is str: return v[:1000] + (" [truncated]" if len(v) > 1000 else "")
                if type(v) in (int, float, bool, type(None)): return v
                return "[unsupported value]"
            safe_rows = [[scalar(v) for v in row] for row in rows]
        return {"columns": list(columns), "rows": safe_rows, "sample_count": len(rows),
                "is_simulation": False, "etl_published": False,
                "limitations": "Unordered bounded sample, not whole-table statistics or an IO budget proof"}

    def extract_bounded(self, schema, table, columns, row_limit=None):
        """Read a user-approved, capped set of discovered scalar columns from a table."""
        self.budget.check_table(schema, table)
        if not isinstance(columns, (tuple, list)) or not 1 <= len(columns) <= 200:
            raise BudgetError("Select 1..200 discovered scalar columns")
        if row_limit is None:
            row_limit = self.budget.sample_rows
        if type(row_limit) is not int or not 1 <= row_limit <= 2_147_483_647:
            raise BudgetError("Extract row limit must be a positive Oracle-compatible integer")
        names = ', '.join(quote_identifier(c) for c in columns)
        obj = quote_identifier(schema) + '.' + quote_identifier(table)
        sql = f"SELECT {names} FROM {obj} WHERE ROWNUM <= :row_cap"
        with self.session() as (cn, started):
            rows = self._query(cn, started, sql, {"row_cap": row_limit}, row_limit)
            def scalar(value):
                if isinstance(value, (date, datetime)): return value.isoformat()
                if isinstance(value, Decimal): return str(value)
                if type(value) is str: return value
                if type(value) in (int, float, bool, type(None)): return value
                raise BudgetError("Unsupported Oracle value type; no rows were loaded")
            safe_rows = [[scalar(value) for value in row] for row in rows]
        return {"columns": list(columns), "rows": safe_rows, "row_count": len(rows),
                "is_simulation": False, "etl_published": False,
                "limitations": "Bounded pilot extract; unordered row cap, not a complete table copy or physical IO budget proof."}
