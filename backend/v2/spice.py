"""SPICE wire client (decision D2, docs/v2/09-spice-probe-results.md).

REST  -> health, dataset list and DESCRIBE only (no streaming, no server row cap: never used for data).
Flight-> every data read, batch by batch, with row / byte / time budgets.

Every call re-validates the URL through netpolicy and connects to the pinned IP. Raw SPICE error text
is logged server-side only; callers get a SpiceError carrying a fixed, safe message.
"""
import datetime
import decimal
import http.client
import json
import logging
import re
import socket
import ssl
import time
from urllib.parse import urlparse

from . import config, limiter, netpolicy

log = logging.getLogger("uetl.spice")
IDENT_RE = re.compile(r"^[A-Za-z0-9_]+$")
OBJECT_RE = re.compile(r"^[A-Za-z0-9_]+(\.[A-Za-z0-9_]+){0,2}$")
MAX_ROWS, MAX_BYTES, MAX_SECONDS = 1000, 1_000_000, 10

SAFE = {
    "unreachable": "The source could not be reached.",
    "timeout": "The source did not answer in time.",
    "busy": "Too many source requests are running; try again shortly.",
    "rejected": "The source rejected the request.",
    "protocol": "The source returned an unexpected response.",
    "too_large": "The source response exceeded the allowed size.",
}


class SpiceError(Exception):
    def __init__(self, code, raw=""):
        super().__init__(SAFE[code])
        self.code, self.safe = code, SAFE[code]
        if raw:
            log.warning("spice error %s: %s", code, str(raw)[:500])


class _PinnedTLS(http.client.HTTPSConnection):
    def __init__(self, ip, port, sni, ctx, timeout):
        super().__init__(ip, port, timeout=timeout, context=ctx)
        self._sni = sni

    def connect(self):
        sock = socket.create_connection((self.host, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self._sni)


def _token(conn):
    name = conn.get("secret_ref")
    # defence in depth: a secret_ref may only name a SPICE_* setting, never UETL_* (database / Redis passwords)
    return config.get(name) if name and name.startswith("SPICE_") else None


def _rest(conn, method, path, body=None, max_bytes=2_000_000):
    try:
        ip, port = netpolicy.resolve_pinned(conn["base_url"])
    except netpolicy.PolicyError as e:
        raise SpiceError("rejected", e) from None
    u = urlparse(conn["base_url"])
    timeout = conn["timeout_s"]
    if u.scheme == "https":
        ctx = ssl.create_default_context() if conn["tls_verify"] else ssl._create_unverified_context()
        c = _PinnedTLS(ip, port, u.hostname, ctx, timeout)
    else:
        c = http.client.HTTPConnection(ip, port, timeout=timeout)
    headers = {"Host": u.netloc, "Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "text/plain"
    if (t := _token(conn)):
        headers["Authorization"] = "Bearer " + t
    try:
        with limiter.lease("spice"):
            c.request(method, (u.path or "") + path, body=body.encode() if body else None, headers=headers)
            r = c.getresponse()
            data = r.read(max_bytes + 1)
    except limiter.Busy:
        raise SpiceError("busy") from None
    except SpiceError:
        raise
    except (socket.timeout, TimeoutError):
        raise SpiceError("timeout") from None
    except OSError as e:
        raise SpiceError("unreachable", e) from None
    finally:
        c.close()
    if len(data) > max_bytes:
        raise SpiceError("too_large")
    if r.status >= 400:
        raise SpiceError("rejected", f"{r.status} {data[:300]!r}")
    return data


def health(conn):
    return _rest(conn, "GET", "/health", max_bytes=1000).decode("utf-8", "replace").strip().lower() == "ok"


def list_datasets(conn):
    try:
        rows = json.loads(_rest(conn, "GET", "/v1/datasets"))
        datasets = [{"name": d["name"], "kind": d.get("from", "").split(":", 1)[0]} for d in rows]
    except (ValueError, KeyError, TypeError) as e:
        raise SpiceError("protocol", e) from None
    return sorted(({"name": d["name"], "kind": d["kind"] if d["kind"] in ("postgres", "odbc") else "other"}
                   for d in datasets if isinstance(d["name"], str) and OBJECT_RE.fullmatch(d["name"])),
                  key=lambda d: d["name"])


def quote(obj):
    if not OBJECT_RE.match(obj):
        raise ValueError("bad object name")
    return ".".join('"' + p + '"' for p in obj.split("."))


def describe(conn, obj):
    try:
        rows = json.loads(_rest(conn, "POST", "/v1/sql", "DESCRIBE " + quote(obj)), parse_float=decimal.Decimal)
        cols = [{"name": r["column_name"], "type": r["data_type"], "nullable": r["is_nullable"] in (True, "YES", "true")}
                for r in rows]
    except (ValueError, KeyError, TypeError) as e:
        raise SpiceError("protocol", e) from None
    return [c for c in cols if IDENT_RE.match(str(c["name"]))]


# ---------- typed literals (Flight has no bind parameters) ----------
OPS = {"=": "=", "!=": "<>", "<": "<", "<=": "<=", ">": ">", ">=": ">="}


def literal(col_type, value):
    """Render `value` as a SQL literal of the column's catalog type; raises ValueError if it does not fit."""
    t = col_type.lower()
    if t.startswith(("int", "uint")):
        return str(int(str(value), 10))
    if t.startswith(("decimal", "float")):
        text = str(value)
        if len(text) > 200:
            raise ValueError("number too long")
        try:
            d = decimal.Decimal(text)
        except decimal.InvalidOperation:
            raise ValueError("bad number") from None
        if not d.is_finite() or abs(d.adjusted()) > 1000 or abs(d.as_tuple().exponent) > 1000:
            raise ValueError("not finite")
        return format(d, "f")
    if t.startswith("bool"):
        if str(value).lower() not in ("true", "false"):
            raise ValueError("bad boolean")
        return str(value).lower()
    if t.startswith("date"):
        return "DATE '" + datetime.date.fromisoformat(str(value)).isoformat() + "'"
    if t.startswith("timestamp"):
        return "TIMESTAMP '" + datetime.datetime.fromisoformat(str(value)).replace(tzinfo=None).isoformat(" ") + "'"
    if t in ("utf8", "largeutf8", "utf8view"):
        s = str(value)
        if len(s) > 200 or "\x00" in s:
            raise ValueError("bad string")
        return "'" + s.replace("'", "''") + "'"
    raise ValueError("column type not filterable")


def build_select(obj, columns, filters, limit):
    """`columns` and `filters` are validated against the catalog by the caller (name -> type map in `columns`)."""
    sel = ", ".join('"' + c + '"' for c in columns["select"]) if columns["select"] else "*"
    where = ""
    if filters:
        parts = [f'"{f["column"]}" {OPS[f["op"]]} {literal(columns["types"][f["column"]], f["value"])}' for f in filters]
        where = " WHERE " + " AND ".join(parts)
    sql = f"SELECT {sel} FROM {quote(obj)}{where}" + (f" LIMIT {int(limit)}" if limit else "")
    assert_select_shape(sql, obj, set(columns["types"]))
    return sql


def assert_select_shape(sql: str, allowed_object: str, allowed_columns: set[str]) -> None:
    """Accept only the single-table grammar emitted by build_select, with opaque literals."""
    # Only SQL-standard doubled apostrophes escape a quote. Unclosed literals fail the grammar.
    stripped = re.sub(r"'(?:[^'\x00]|'')*'", "'value'", sql)
    ident = r'"[A-Za-z0-9_]+"'
    value = r"(?:-?[0-9]+(?:\.[0-9]+)?|true|false|(?:DATE |TIMESTAMP )?'value')"
    condition = rf"{ident} (?:<>|<=|>=|=|<|>) {value}"
    match = re.fullmatch(rf"SELECT (?P<cols>\*|{ident}(?:, {ident})*) FROM (?P<obj>{ident}(?:\.{ident}){{0,2}})"
                         rf"(?: WHERE (?P<where>{condition}(?: AND {condition})*))?(?: LIMIT [1-9][0-9]*)?", stripped)
    if not match or match["obj"] != quote(allowed_object):
        raise ValueError("Unexpected SELECT shape")
    identifiers = re.findall(ident, match["cols"] + " " + (match["where"] or ""))
    if any(name[1:-1] not in allowed_columns for name in identifiers):
        raise ValueError("Unknown column")


# ---------- Flight ----------
def flight_endpoint(conn):
    host = urlparse(conn["base_url"]).hostname
    port = int(config.get("UETL_SPICE_FLIGHT_PORT", "50051"))
    try:
        ip, port = netpolicy.resolve_pinned(f"http://{host}:{port}")
    except netpolicy.PolicyError as e:
        raise SpiceError("rejected", e) from None
    return ip, port


def _jsonable(v):
    if v is None or isinstance(v, (bool, str)):
        return v
    if isinstance(v, int):
        return v if abs(v) < 2**53 else str(v)  # beyond JS safe integers -> string
    if isinstance(v, float):
        return v if v == v and abs(v) != float("inf") else str(v)
    if isinstance(v, decimal.Decimal):
        return format(v, "f")
    if isinstance(v, (datetime.datetime, datetime.date, datetime.time)):
        return v.isoformat()
    if isinstance(v, (bytes, bytearray)):
        return "0x" + bytes(v[:32]).hex() + ("..." if len(v) > 32 else "")
    return str(v)


def _arrow_jsonable(column, index):
    try:
        return _jsonable(column[index].as_py())
    except OverflowError:
        # Arrow supports dates/timestamps beyond Python's year 1..9999 range.
        # Let Arrow format the scalar so valid source data remains exact text.
        import pyarrow as pa
        return column.slice(index, 1).cast(pa.string())[0].as_py()


def run_bounded(conn, sql, max_rows=MAX_ROWS, max_bytes=MAX_BYTES, max_seconds=MAX_SECONDS, pool="spice"):
    """Read `sql` over Flight; stop at the first exhausted budget. Returns (columns, rows, truncated)."""
    import pyarrow as pa
    import pyarrow.flight as fl
    ip, port = flight_endpoint(conn)
    deadline = time.monotonic() + max_seconds
    headers = [(b"authorization", ("Bearer " + t).encode())] if (t := _token(conn)) else []
    opts = fl.FlightCallOptions(timeout=max_seconds, headers=headers)
    rows, size, truncated, cols = [], 0, False, []
    try:
        client = fl.FlightClient(f"grpc://{ip}:{port}")
        try:
            info = client.get_flight_info(fl.FlightDescriptor.for_command(sql.encode()), opts)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SpiceError("timeout")
            reader = client.do_get(info.endpoints[0].ticket, fl.FlightCallOptions(timeout=remaining, headers=headers))
            cols = [{"name": f.name, "type": str(f.type)} for f in reader.schema]
            while True:
                try:
                    chunk = reader.read_chunk()
                except StopIteration:
                    break
                b = chunk.data
                for index in range(b.num_rows):
                    if time.monotonic() >= deadline:
                        reader.cancel()
                        raise SpiceError("timeout")
                    if len(rows) >= max_rows:
                        truncated = True
                        break
                    row_bytes = b.slice(index, 1).nbytes
                    if size + row_bytes > max_bytes:
                        truncated = True
                        break
                    row = [_arrow_jsonable(c, index) for c in b.columns]
                    # Bound both Arrow payload and escaped JSON (quotes/control chars may expand).
                    row_bytes = max(row_bytes, len(json.dumps(row, ensure_ascii=False).encode("utf-8")))
                    if size + row_bytes > max_bytes:
                        truncated = True
                        break
                    size += row_bytes
                    rows.append(row)
                if time.monotonic() >= deadline:
                    reader.cancel()
                    raise SpiceError("timeout")
                if truncated:
                    reader.cancel()
                    break
        finally:
            client.close()
    except SpiceError:
        raise
    except fl.FlightTimedOutError:
        raise SpiceError("timeout") from None
    except fl.FlightUnavailableError as e:
        raise SpiceError("unreachable", e) from None
    except (fl.FlightError, pa.ArrowException, OSError) as e:  # ArrowInvalid = SQL rejected by the source
        raise SpiceError("rejected", e) from None
    return cols, rows, truncated
