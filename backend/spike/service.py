"""Memory-only single-owner service. No Registry/Target writes or credential logs."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import hmac
import json
import secrets
import sqlite3
import threading
import time
import re
from backend.foundation.read_budget import ReadBudget, ReadGate, BudgetError
from backend.foundation.oracle_read import OracleReadAdapter, SourceReadFailed, safe_source_error, quote_identifier
from backend.spike.catalog_store import CatalogStore
from backend.spike.target_store import SQLiteTargetStore

CATALOG_PAGE_DEFAULT = 50
CATALOG_PAGE_MAX = 100
MAX_EXTRACT_ROWS = 2_147_483_647
SCALAR_TYPES = frozenset(("VARCHAR2", "NVARCHAR2", "CHAR", "NCHAR", "NUMBER", "FLOAT",
                          "BINARY_FLOAT", "BINARY_DOUBLE", "DATE", "TIMESTAMP",
                          "TIMESTAMP WITH TIME ZONE", "TIMESTAMP WITH LOCAL TIME ZONE"))


class APIError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


def now():
    return datetime.now(timezone.utc).isoformat()


def number(value, maximum):
    if type(value) is not int or not 1 <= value <= maximum:
        raise APIError(400, "Invalid bounded limit")
    return value


def config_validate(data):
    required = {"host", "port", "identifier_type", "identifier", "username", "password", "protocol", "tcp_ack", "readonly_ack"}
    if not isinstance(data, dict) or set(data) != required:
        raise APIError(400, "Invalid connection fields")
    if not isinstance(data["host"], str) or not re.fullmatch(r"[a-zA-Z0-9._-]{1,253}", data["host"]):
        raise APIError(400, "Invalid host")
    number(data["port"], 65535)
    if data["identifier_type"] not in ("Service Name", "SID") or data["protocol"] not in ("tcps", "tcp"):
        raise APIError(400, "Invalid identifier type/protocol")
    for key in ("identifier", "username", "password"):
        if not isinstance(data[key], str) or not 1 <= len(data[key]) <= 1024 or any(ord(c) < 32 for c in data[key]):
            raise APIError(400, "Required connection value invalid")
    if data["readonly_ack"] is not True:
        raise APIError(400, "Confirm authorized read-only account")
    if data["protocol"] == "tcp" and data["tcp_ack"] is not True:
        raise APIError(400, "TCP requires explicit protected-network approval acknowledgement")
    return dict(data)


def oracle_factory(config, timeout):
    def connect():
        import oracledb
        options = {"host": config["host"], "port": config["port"],
                   "protocol": config["protocol"], "tcp_connect_timeout": timeout,
                   "retry_count": 0, "ssl_server_dn_match": True}
        options["service_name" if config["identifier_type"] == "Service Name" else "sid"] = config["identifier"]
        return oracledb.connect(user=config["username"], password=config["password"],
                                params=oracledb.ConnectParams(**options))
    return connect


class Service:
    def __init__(self, passphrase, *, factory=oracle_factory, clock=time.monotonic, catalog_store=None, target_store=None):
        if len(passphrase) < 12:
            raise ValueError("Local application passphrase requires at least 12 characters")
        self.salt = secrets.token_bytes(16)
        self.password_hash = self._hash(passphrase)
        self.factory, self.clock = factory, clock
        self.catalog_store = catalog_store or CatalogStore(":memory:")
        self.target_store = target_store
        self.lock = threading.RLock()
        self.gate = ReadGate()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="oracle-read-worker")
        self.sessions = {}
        self.login_attempts = []
        self.active = False
        self.stop = threading.Event()
        self.reaper = threading.Thread(target=self._reap, daemon=True, name="credential-expiry")
        self.reaper.start()

    def _reap(self):
        while not self.stop.wait(5):
            with self.lock:
                for token, state in list(self.sessions.items()):
                    if self.clock() >= state["expires"] and not state["busy"]:
                        self.sessions.pop(token, None)

    def _hash(self, password):
        return hashlib.scrypt(password.encode(), salt=self.salt, n=16384, r=8, p=1)

    def login(self, password):
        with self.lock:
            self.login_attempts = [t for t in self.login_attempts if self.clock() - t < 60]
            if len(self.login_attempts) >= 5:
                raise APIError(429, "Too many login attempts; wait one minute")
            self.login_attempts.append(self.clock())
            if not isinstance(password, str) or len(password) > 1024 or not hmac.compare_digest(self._hash(password), self.password_hash):
                raise APIError(401, "Application login failed")
            # One local owner/session only; do not permit unlimited memory tokens.
            for old in self.sessions.values():
                if old.get("busy"):
                    raise APIError(409, "Current session has a running read")
            self.sessions.clear()
            token = secrets.token_urlsafe(32)
            self.sessions[token] = {"csrf": secrets.token_urlsafe(24), "expires": self.clock()+1800,
                                    "jobs": {}, "config": None, "revision": 0, "tested": False, "metadata": {}, "profiles": {}, "busy": False}
            return token, self.sessions[token]["csrf"]

    def session(self, token):
        with self.lock:
            state = self.sessions.get(token)
            if state is None or self.clock() >= state["expires"]:
                if state is not None and not state["busy"]:
                    self.sessions.pop(token, None)
                raise APIError(401, "Session expired; sign in and enter credentials again")
            return state

    def logout(self, token):
        with self.lock:
            state = self.session(token)
            if state["busy"]:
                raise APIError(409, "Wait for current bounded read before disconnect")
            del self.sessions[token]

    def profile_statuses(self, token):
        state = self.session(token)
        return {key: {"tested": bool(value.get("tested")), "connected": bool(value.get("connected")),
                      "revision": value.get("revision", 0)} for key, value in state["profiles"].items()}

    @staticmethod
    def _source_key(config, result):
        # Credentials are deliberately excluded. Same endpoint and Oracle principal share metadata.
        identity = [config["host"].lower(), config["port"], config["identifier_type"],
                    config["identifier"].upper(), config["username"].upper(),
                    str(result.get("database", "")).upper(), str(result.get("identity", "")).upper()]
        return hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()

    def catalog_cache(self, token, profile_id):
        with self.lock:
            state = self.session(token)
            profile = state["profiles"].get(profile_id)
            if (not isinstance(profile_id, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", profile_id)
                    or profile is None or not profile.get("tested") or not profile.get("connected")
                    or not profile.get("source_key")):
                raise APIError(409, "Connect this tested Oracle profile before loading its saved catalog")
            snapshot = self.catalog_store.current_snapshot(profile["source_key"])
            if snapshot:
                metadata = []
                for item in snapshot.pop("metadata"):
                    payload = json.loads(item["payload"])
                    schema, name = item["schema_name"], item["object_name"]
                    profile["metadata"][(schema, name)] = payload
                    metadata.append({"schema": schema, "name": name, "kind": item["object_type"],
                                     "payload": payload, "updated_at": item["updated_at"]})
                snapshot["metadata"] = metadata
                return snapshot
            return {"available": False, "objects": [], "metadata": []}

    def local_target_status(self, token):
        state = self.session(token)
        if self.target_store is None:
            raise APIError(503, "Local SQLite target is unavailable")
        stored = self.target_store.statuses()
        tables = {}
        for profile_id, profile in state.get("profiles", {}).items():
            source_key = profile.get("source_key")
            if not source_key:
                continue
            for key, value in stored.items():
                if key.startswith(source_key + "|"):
                    _, schema, name = key.split("|", 2)
                    tables[f"{profile_id}|{schema}|{name}"] = value
        return {"tables": tables}

    def local_target_preview(self, token, profile_id, schema, object_name, limit):
        state = self.session(token)
        if self.target_store is None:
            raise APIError(503, "Local SQLite target is unavailable")
        profile = state.get("profiles", {}).get(profile_id)
        if not profile or not profile.get("source_key"):
            raise APIError(404, "Source profile not found")
        if not isinstance(schema, str) or not re.fullmatch(r"[A-Za-z0-9_$#]{1,128}", schema):
            raise APIError(400, "Invalid schema")
        if not isinstance(object_name, str) or not re.fullmatch(r"[A-Za-z0-9_$#]{1,128}", object_name):
            raise APIError(400, "Invalid object name")
        limit = number(limit, 100)
        source_key = profile["source_key"]
        stored_key = f"{source_key}|{schema}|{object_name}"
        if stored_key not in self.target_store.statuses():
            raise APIError(404, "No locally loaded data found for this table")
        import hashlib
        target_table = "T_" + hashlib.sha256(stored_key.encode()).hexdigest()[:40]
        try:
            return self.target_store.preview(target_table=target_table, limit=limit)
        except (ValueError, sqlite3.OperationalError):
            raise APIError(404, "Stored table is unavailable") from None

    def connect_profile(self, token, profile_id):
        with self.lock:
            state = self.session(token)
            if not isinstance(profile_id, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", profile_id):
                raise APIError(400, "Invalid profile id")
            profile = state["profiles"].get(profile_id)
            if profile is None or not profile.get("tested") or not profile.get("config"):
                raise APIError(409, "Test this Oracle profile successfully before connecting")
            profile["connected"] = True
            state["expires"] = self.clock() + 1800
            return {"profile_id": profile_id, "connected": True}

    def disconnect_profile(self, token, profile_id):
        with self.lock:
            state = self.session(token)
            if not isinstance(profile_id, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", profile_id):
                raise APIError(400, "Invalid profile id")
            if state.get("busy") and state.get("active_profile_id") == profile_id:
                raise APIError(409, "Wait for this profile's bounded read to finish before disconnecting")
            state["profiles"].pop(profile_id, None)
            return {"profile_id": profile_id, "connected": False}

    def submit(self, token, action, data):
        with self.lock:
            state = self.session(token)
            if self.active:
                raise APIError(409, "One read already running; wait for it to finish")
            if action not in ("test", "catalog", "discover", "sample", "extract_load", "match_columns") or not isinstance(data, dict):
                raise APIError(400, "Unsupported action")
            profile_id = data.get("profile_id", "default")
            if not isinstance(profile_id, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", profile_id):
                raise APIError(400, "Invalid profile id")
            profile = state if profile_id == "default" else state["profiles"].setdefault(profile_id, {"config": None, "revision": 0, "tested": False, "connected": False, "metadata": {}, "source_key": None, "catalog_refresh_id": None})
            fields = {key: value for key, value in data.items() if key != "profile_id"}
            if action == "test":
                if set(fields) != {"config", "timeout"}:
                    # Older same-app clients posted the Oracle fields at the
                    # top level. Accept only that exact legacy shape; all
                    # validation below still applies to every credential and
                    # connection parameter.
                    config_fields = {"host", "port", "identifier_type", "identifier", "username",
                                     "password", "protocol", "tcp_ack", "readonly_ack"}
                    if set(fields) == config_fields | {"timeout"}:
                        fields = {"config": {key: fields[key] for key in config_fields},
                                  "timeout": fields["timeout"]}
                    else:
                        # Report field names only: values can include credentials
                        # and must never be echoed to the browser or application logs.
                        received = ", ".join(sorted(fields)) or "none"
                        raise APIError(400, f"Invalid test request fields ({received})")
                config = config_validate(fields["config"])
                timeout = number(fields["timeout"], 30)
                profile.update(config=dict(config), revision=profile.get("revision", 0)+1, tested=False, connected=False, metadata={})
                table = None
                budget = ReadBudget(frozenset(), sample_rows=100, batch_size=25,
                                    timeout_seconds=timeout, catalog_only=True)
            elif action == "catalog":
                if not profile["tested"] or not profile.get("connected", profile_id == "default"):
                    raise APIError(409, "Connect this Oracle profile after Test Connection first")
                if set(fields) != {"cursor", "page_size", "timeout"}:
                    raise APIError(400, "Invalid catalog page fields")
                timeout = number(fields["timeout"], 30)
                page_size = number(fields["page_size"], CATALOG_PAGE_MAX)
                cursor = fields["cursor"]
                if cursor is not None and (not isinstance(cursor, dict) or set(cursor) != {"owner", "name", "kind", "object_id"}):
                    raise APIError(400, "Invalid catalog cursor")
                if not profile.get("source_key"):
                    raise APIError(409, "Test Connection again to establish the Oracle identity for catalog storage")
                if cursor is None:
                    try:
                        profile["catalog_refresh_id"] = self.catalog_store.begin_refresh(profile["source_key"])
                    except RuntimeError:
                        raise APIError(409, "A catalog refresh for this Oracle identity is already running") from None
                elif not profile.get("catalog_refresh_id"):
                    raise APIError(409, "Catalog refresh cursor expired; restart the catalog reload")
                budget = ReadBudget(frozenset(), sample_rows=page_size, batch_size=page_size,
                                    timeout_seconds=timeout, catalog_only=True)
                config = dict(profile["config"])
            elif action == "match_columns":
                if not profile["tested"] or not profile.get("connected", profile_id == "default"):
                    raise APIError(409, "Connect this Oracle profile before searching column names")
                if set(fields) != {"keynames", "match_mode", "timeout"}:
                    raise APIError(400, "Invalid column search fields")
                names = fields["keynames"]
                if not isinstance(names, list) or not 1 <= len(names) <= 20:
                    raise APIError(400, "Enter 1 to 20 column names")
                normalized = []
                for name in names:
                    if not isinstance(name, str):
                        raise APIError(400, "Invalid column name")
                    name = name.strip().upper()
                    try:
                        quote_identifier(name)
                    except BudgetError:
                        raise APIError(400, "Column names must be simple Oracle identifiers") from None
                    if name not in normalized:
                        normalized.append(name)
                if not normalized or fields["match_mode"] not in ("all", "any"):
                    raise APIError(400, "Choose valid column names and match mode")
                if not profile.get("source_key") or not self.catalog_store.current_snapshot(profile["source_key"]):
                    raise APIError(409, "Load all schema metadata before searching columns")
                timeout = number(fields["timeout"], 30)
                budget = ReadBudget(frozenset(), sample_rows=1000, batch_size=250,
                                    timeout_seconds=timeout, catalog_only=True)
                config = dict(profile["config"])
                fields["keynames"] = normalized
            else:
                if not profile["tested"] or not profile.get("connected", profile_id == "default"):
                    raise APIError(409, "Test Connection must pass first")
                expected = {"schema", "table", "timeout"} if action == "discover" else ({"schema", "table", "timeout", "sample_rows", "batch_size", "columns", "budget_ack"} if action == "sample" else {"schema", "table", "timeout", "row_limit", "columns", "budget_ack"})
                if set(fields) != expected:
                    raise APIError(400, "Invalid read fields")
                schema, table = fields["schema"], fields["table"]
                try:
                    quote_identifier(schema); quote_identifier(table)
                except BudgetError:
                    raise APIError(400, "Invalid schema or object identifier")
                timeout = number(fields["timeout"], 30)
                if action == "extract_load":
                    extract_limit = number(fields["row_limit"], MAX_EXTRACT_ROWS)
                    rows, batch = min(extract_limit, 1000), min(extract_limit, 1000)
                else:
                    rows, batch = (100, 25) if action == "discover" else (number(fields["sample_rows"], 100), number(fields["batch_size"], 25))
                budget = ReadBudget(frozenset({(schema, table)}), sample_rows=rows,
                                    batch_size=batch, timeout_seconds=timeout)
                config = dict(profile["config"])
                if action in ("sample", "extract_load"):
                    if fields["budget_ack"] is not True:
                        raise APIError(400, "Confirm source query budget before reading")
                    if action == "extract_load" and (self.target_store is None or not profile.get("source_key")):
                        raise APIError(503, "Local SQLite target is unavailable")
                    metadata = profile["metadata"].get((schema, table))
                    if not metadata or not isinstance(fields["columns"], list) or not fields["columns"]:
                        raise APIError(409, "Discover the table metadata first")
                    allowed_objects = ("TABLE", "VIEW", "MATERIALIZED VIEW") if action == "sample" else ("TABLE",)
                    if not any(row[2] in allowed_objects for row in metadata["object"]):
                        raise APIError(409, "Extract & Load currently supports discovered Oracle TABLE objects only")
                    allowed = {r[0] for r in metadata["columns"] if r[2] in SCALAR_TYPES}
                    if len(fields["columns"]) > 200 or any(c not in allowed for c in fields["columns"]) or len(set(fields["columns"])) != len(fields["columns"]):
                        raise APIError(403, "Only discovered scalar columns may be extracted (max 200)")
                    if action == "extract_load":
                        primary_keys = [key[2] for key in metadata.get("keys", []) if len(key) > 3 and key[1] == "P"]
                        if not primary_keys:
                            raise APIError(409, "This table has no discovered Primary Key; load is blocked to prevent duplicates")
                        fields["columns"] = list(dict.fromkeys([*primary_keys, *fields["columns"]]))
            if len(state["jobs"]) >= 20:
                # Retain bounded current-session history only.
                state["jobs"].pop(next(iter(state["jobs"])))
            job_id = secrets.token_hex(12)
            job = {"id": job_id, "action": action, "profile_id": profile_id, "schema": fields.get("schema"), "table": fields.get("table"),
                   "keynames": fields.get("keynames"), "match_mode": fields.get("match_mode"),
                   "cursor": fields.get("cursor"), "catalog_refresh_id": profile.get("catalog_refresh_id") if action == "catalog" else None,
                   "revision": profile.get("revision", 0),
                   "columns": list(fields.get("columns", [])), "row_limit": fields.get("row_limit"),
                   "limits": {"sample_rows": budget.sample_rows if action == "sample" else 0,
                   "page_size": budget.batch_size if action == "catalog" else 0,
                   "batch_size": budget.batch_size, "timeout_seconds": budget.timeout_seconds},
                   "state": "running", "started_at": now(), "result": None, "etl_published": False}
            state["jobs"][job_id] = job
            self.active = state["busy"] = True
            state["active_profile_id"] = profile_id
            self.pool.submit(self._run, state, profile, job, config, budget, list(fields.get("columns", [])))
            return {"job_id": job_id, "state": "running"}

    def _run(self, state, profile, job, config, budget, columns):
        try:
            adapter = OracleReadAdapter(self.factory(config, budget.timeout_seconds), budget, gate=self.gate)
            if job["action"] == "test":
                result = adapter.test_connection()
                profile["tested"] = True
                profile["source_key"] = self._source_key(config, result)
            elif job["action"] == "catalog":
                result = adapter.discover_catalog_page(job["cursor"])
                refresh_id = job["catalog_refresh_id"]
                self.catalog_store.append_page(refresh_id, result["objects"])
                if result["next_cursor"] is None:
                    result.update(self.catalog_store.complete_refresh(refresh_id))
                    with self.lock:
                        profile["catalog_refresh_id"] = None
            elif job["action"] == "match_columns":
                result = adapter.find_objects_by_columns(job["keynames"], job["match_mode"])
                snapshot = self.catalog_store.current_snapshot(profile.get("source_key"))
                catalog = {(o["schema"], o["name"]): o for o in (snapshot or {}).get("objects", [])}
                result["objects"] = [{**catalog[(o["schema"], o["name"])], **o}
                    for o in result["objects"] if (o["schema"], o["name"]) in catalog]
                result["catalog_refreshed_at"] = (snapshot or {}).get("refreshed_at")
            elif job["action"] == "discover":
                schema, table = job["schema"], job["table"]
                source_key = profile.get("source_key")
                snapshot = self.catalog_store.current_snapshot(source_key) if source_key else None
                catalog_object = next((o for o in (snapshot or {}).get("objects", [])
                                       if o["schema"] == schema and o["name"] == table), None)
                result = self.catalog_store.get_metadata(source_key, schema, table,
                    catalog_object["kind"], catalog_object.get("last_ddl_time")) if catalog_object else None
                if result is None:
                    result = adapter.discover_table(schema, table)
                    object_type = next((row[2] for row in result["object"]), "TABLE")
                    self.catalog_store.save_metadata(source_key, schema, table, object_type,
                        catalog_object.get("last_ddl_time") if catalog_object else None, result)
                with self.lock:
                    profile["metadata"][(schema, table)] = result
            else:
                if job["action"] == "extract_load":
                    extracted = adapter.extract_bounded(job["schema"], job["table"], columns,
                                                        row_limit=job["row_limit"])
                    metadata = profile["metadata"][(job["schema"], job["table"])]
                    primary_keys = list(dict.fromkeys(key[2] for key in metadata.get("keys", []) if len(key) > 3 and key[1] == "P"))
                    column_types = {row[0]: row[2] for row in metadata["columns"]}
                    column_defs = [{"name": name, "type": column_types[name]} for name in columns]
                    import hashlib
                    source_key = profile.get("source_key")
                    target_table = "T_" + hashlib.sha256((source_key+"|"+job["schema"]+"|"+job["table"]).encode()).hexdigest()[:40]
                    loaded = self.target_store.load_rows(target_table=target_table, columns=column_defs,
                        primary_keys=primary_keys, rows=extracted["rows"])
                    self.target_store.record_source_status(source_id=source_key, schema=job["schema"],
                        object_name=job["table"], target_table=target_table,
                        last_load_at=loaded["last_load_at"], last_received=loaded["rows_received"],
                        target_rows=loaded["target_rows"])
                    result = {"source": f"{job['schema']}.{job['table']}", "columns": columns,
                              "primary_keys": primary_keys, **loaded, "row_limit": job["row_limit"],
                              "target": "Local SQLite", "limitations": extracted["limitations"]}
                else:
                    result = adapter.sample(job["schema"], job["table"], columns)
                    result["profiles"] = [{"column": c, "sample_count": len(result["rows"]),
                                           "null_count": sum(r[i] is None for r in result["rows"]),
                                           "distinct_in_sample": len({r[i] for r in result["rows"] if r[i] is not None})}
                                          for i, c in enumerate(columns)]
            with self.lock:
                job.update(state="read_completed", result=result, ended_at=now(), is_simulation=False)
        except (SourceReadFailed, BudgetError) as exc:
            with self.lock:
                if job["action"] == "catalog" and job.get("catalog_refresh_id"):
                    self.catalog_store.fail_refresh(job["catalog_refresh_id"])
                    if profile.get("catalog_refresh_id") == job["catalog_refresh_id"]:
                        profile["catalog_refresh_id"] = None
                error = safe_source_error(exc) if isinstance(exc, SourceReadFailed) else "Read budget exceeded; reduce the requested limits and retry manually."
                job.update(state="failed", error=f"{error} No automatic retry.", ended_at=now())
                if job["action"] == "test":
                    profile["config"] = None
        except Exception:
            with self.lock:
                if job["action"] == "catalog" and job.get("catalog_refresh_id"):
                    self.catalog_store.fail_refresh(job["catalog_refresh_id"])
                    if profile.get("catalog_refresh_id") == job["catalog_refresh_id"]:
                        profile["catalog_refresh_id"] = None
                job.update(state="failed", error="Runtime/driver unavailable or read failed; no diagnostic secrets returned", ended_at=now())
                if job["action"] == "test": profile["config"] = None
        finally:
            config.clear()
            with self.lock:
                self.active = state["busy"] = False
                state["active_profile_id"] = None
                if self.clock() >= state["expires"]:
                    state.update(config=None, metadata={}, jobs={}, profiles={})

    def job(self, token, job_id):
        with self.lock:
            job = self.session(token)["jobs"].get(job_id)
            if job is None: raise APIError(404, "Job not found in this session")
            return dict(job)

    def close(self):
        self.stop.set()
        self.reaper.join(timeout=1)
        self.pool.shutdown(wait=True)
        self.sessions.clear()
        self.catalog_store.close()
