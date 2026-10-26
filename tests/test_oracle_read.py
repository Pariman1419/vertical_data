import unittest
from backend.foundation.oracle_read import OracleReadAdapter, SourceReadFailed, quote_identifier
from backend.foundation.read_budget import ReadBudget, ReadGate, BudgetError


class Cursor:
    def __init__(self, cn): self.cn = cn
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def execute(self, sql, binds=None):
        self.cn.commands.append((sql, binds))
        if self.cn.fail: raise RuntimeError("password=DO_NOT_ECHO")
        key = ("catalog" if "FETCH NEXT" in sql and "ALL_OBJECTS" in sql else
               "column_match" if "FROM ALL_TAB_COLUMNS" in sql and "COLUMN_NAME IN" in sql else
               "object" if "ALL_OBJECTS" in sql else
               "foreign_keys" if "LEFT JOIN" in sql else "columns" if "ALL_TAB_COLUMNS" in sql else
               "keys" if "ALL_CONSTRAINTS" in sql else "sample" if ":row_cap" in sql else "default")
        self.rows = iter(self.cn.query_rows.get(key, self.cn.rows))
    def fetchmany(self, n):
        self.cn.fetch_sizes.append(n)
        result = []
        for _ in range(n):
            try: result.append(next(self.rows))
            except StopIteration: break
        return result


class Connection:
    version = "fixture-version"
    def __init__(self, rows=(), fail=False, query_rows=None):
        self.rows, self.fail = rows, fail
        self.query_rows = query_rows or {}
        self.commands, self.fetch_sizes, self.closed = [], [], False
    def cursor(self): return Cursor(self)
    def close(self): self.closed = True


class OracleReadTests(unittest.TestCase):
    def adapter(self, cn):
        return OracleReadAdapter(lambda: cn, ReadBudget(frozenset({("MES", "EVENTS")}), sample_rows=3, batch_size=2), gate=ReadGate())
    def test_server_cap_and_no_dml_or_secret(self):
        cn = Connection([(1,), (2,), (3,), (4,)])
        result = self.adapter(cn).sample("MES", "EVENTS", ["LOT_NO"])
        self.assertEqual(result["sample_count"], 3)
        self.assertEqual(cn.fetch_sizes, [2, 1])
        self.assertTrue(cn.closed)
        self.assertEqual(cn.commands[0][0], "SET TRANSACTION READ ONLY")
        self.assertIn("ROWNUM <= :row_cap", cn.commands[1][0])
        self.assertEqual(cn.commands[1][1], {"row_cap": 3})
        self.assertFalse(result["etl_published"])
    def test_bounded_extract_uses_only_requested_columns_and_hard_row_cap(self):
        cn = Connection(query_rows={"sample": [(1, "A"), (2, "B"), (3, "C"), (4, "D")]})
        result = self.adapter(cn).extract_bounded("MES", "EVENTS", ["ID", "LOT_NO"])
        self.assertEqual(result["rows"], [[1, "A"], [2, "B"], [3, "C"]])
        self.assertEqual(result["row_count"], 3)
        self.assertIn('SELECT "ID", "LOT_NO" FROM "MES"."EVENTS"', cn.commands[1][0])
        self.assertEqual(cn.commands[1][1], {"row_cap": 3})
        self.assertEqual(cn.commands[0][0], "SET TRANSACTION READ ONLY")
        self.assertTrue(cn.closed)
    def test_extract_row_limit_can_be_configured_above_default_100(self):
        cn = Connection(query_rows={"sample": [(1, "A"), (2, "B"), (3, "C"), (4, "D")]})
        result = self.adapter(cn).extract_bounded("MES", "EVENTS", ["ID", "LOT_NO"], row_limit=101)
        self.assertEqual(result["row_count"], 4)
        self.assertEqual(cn.commands[1][1], {"row_cap": 101})
        with self.assertRaises(BudgetError):
            self.adapter(Connection()).extract_bounded("MES", "EVENTS", ["ID"], row_limit=2_147_483_648)
    def test_allowlist_and_identifier_before_connection(self):
        cn = Connection()
        for table in ("OTHER", "EVENTS;DELETE"):
            with self.assertRaises(BudgetError): self.adapter(cn).sample("MES", table, ["LOT_NO"])
        with self.assertRaises(BudgetError): quote_identifier('x" OR 1=1')
        self.assertEqual(cn.commands, [])
    def test_error_sanitized_and_closed(self):
        cn = Connection(fail=True)
        with self.assertRaises(SourceReadFailed) as caught:
            self.adapter(cn).sample("MES", "EVENTS", ["LOT_NO"])
        self.assertNotIn("DO_NOT_ECHO", str(caught.exception))
        self.assertTrue(cn.closed)
    def test_metadata_scoped_and_parameterized(self):
        cn = Connection([("MES", "EVENTS", "TABLE")])
        result = self.adapter(cn).discover_table("MES", "EVENTS")
        self.assertEqual(set(result), {"object", "columns", "keys", "foreign_keys", "limitations"})
        for sql, binds in cn.commands[1:]:
            self.assertIn(":owner", sql)
            self.assertEqual(binds["name"], "EVENTS")
            self.assertNotIn("COUNT(", sql)

    def test_catalog_page_is_visible_metadata_only_and_stable_keyset(self):
        rows = [("A_SCHEMA", "T1", "TABLE", 10, None), ("B_SCHEMA", "T2", "VIEW", 11, None)]
        cn = Connection(query_rows={"catalog": rows})
        budget = ReadBudget(frozenset(), sample_rows=2, batch_size=2, timeout_seconds=15, catalog_only=True)
        result = OracleReadAdapter(lambda: cn, budget, gate=ReadGate()).discover_catalog_page()
        self.assertEqual(result["objects"], [{"schema":"A_SCHEMA","name":"T1","kind":"TABLE","last_ddl_time":None}, {"schema":"B_SCHEMA","name":"T2","kind":"VIEW","last_ddl_time":None}])
        self.assertEqual(result["next_cursor"], {"owner":"B_SCHEMA","name":"T2","kind":"VIEW","object_id":11})
        sql, binds = next((sql, binds) for sql, binds in cn.commands if "FETCH NEXT" in sql)
        self.assertIn("ALL_OBJECTS", sql)
        # The first page must not use empty-string binds: Oracle treats those
        # as NULL, which would make every keyset comparison UNKNOWN.
        self.assertNotIn("OBJECT_ID > :object_id", sql)
        self.assertNotIn("owner", binds)
        self.assertIn("ORDER BY OWNER, OBJECT_NAME, OBJECT_TYPE, OBJECT_ID", sql)
        self.assertNotIn("COUNT(", sql.upper())
        self.assertEqual(binds["cap"], 2)
        self.assertFalse(result["etl_published"])

        catalog_adapter = OracleReadAdapter(lambda: cn, budget, gate=ReadGate())
        next_page = catalog_adapter.discover_catalog_page(result["next_cursor"])
        self.assertEqual(len(next_page["objects"]), 2)
        next_sql, next_binds = next((sql, binds) for sql, binds in cn.commands if "FETCH NEXT" in sql and "OBJECT_ID > :object_id" in sql)
        self.assertIn("OBJECT_ID > :object_id", next_sql)
        self.assertEqual(next_binds["owner"], "B_SCHEMA")

    def test_catalog_rejects_malformed_or_unbounded_cursor_before_connection(self):
        budget = ReadBudget(frozenset(), sample_rows=2, batch_size=2, timeout_seconds=15, catalog_only=True)
        cn = Connection()
        adapter = OracleReadAdapter(lambda: cn, budget, gate=ReadGate())
        for cursor in ({"owner":"X","name":"Y","kind":"TABLE"},
                       {"owner":"X","name":"Y","kind":"TABLE","object_id":-1}):
            with self.assertRaises(BudgetError): adapter.discover_catalog_page(cursor)
        self.assertEqual(cn.commands, [])

    def test_column_key_search_matches_all_or_any_names_using_metadata_only(self):
        rows = [("A", "T1", "LOT_NO"), ("A", "T2", "LOT_NO"),
                ("A", "T2", "ORDER_NO"), ("B", "V1", "ORDER_NO")]
        cn = Connection(query_rows={"column_match": rows})
        budget = ReadBudget(frozenset(), sample_rows=1000, batch_size=250,
                            timeout_seconds=15, catalog_only=True)
        adapter = OracleReadAdapter(lambda: cn, budget, gate=ReadGate())
        all_result = adapter.find_objects_by_columns(["LOT_NO", "ORDER_NO"], "all")
        any_result = adapter.find_objects_by_columns(["LOT_NO", "ORDER_NO"], "any")
        self.assertEqual([(o["schema"], o["name"]) for o in all_result["objects"]], [("A", "T2")])
        self.assertEqual({o["name"] for o in any_result["objects"]}, {"T1", "T2", "V1"})
        sql, binds = next((sql, binds) for sql, binds in cn.commands if "COLUMN_NAME IN" in sql)
        self.assertIn("ALL_TAB_COLUMNS", sql)
        self.assertEqual(binds["key0"], "LOT_NO")
        self.assertEqual(binds["key1"], "ORDER_NO")
        self.assertEqual(binds["cap"], 10000)
        self.assertTrue(all(cn.closed for _ in [0]))
        with self.assertRaises(BudgetError): adapter.find_objects_by_columns(["X;DROP"], "any")

    def test_identity_is_driver_evidence_only(self):
        cn = Connection([("fixture-user", "fixture-db")])
        self.assertEqual(self.adapter(cn).test_connection()["identity"], "fixture-user")
    def test_lob_not_read(self):
        class Lob:
            def read(self): raise AssertionError("LOB read forbidden")
        cn = Connection([(Lob(),)])
        self.assertEqual(self.adapter(cn).sample("MES", "EVENTS", ["LOT_NO"])["rows"], [["[unsupported value]"]])


if __name__ == "__main__": unittest.main()
