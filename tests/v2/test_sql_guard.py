"""Closed SELECT grammar with hostile literal/property inputs, no parser dependency."""
import random
import re

import pytest

from backend.v2 import spice


def test_generated_sql_always_has_the_expected_shape():
    rng = random.Random(1)
    corpus = ["x'; DROP TABLE t; --", "/* UNION */", "\x00", "a\nb", "ไทย", "a" * 10000,
              "0012", "-12", "1.5", "NaN", "1e999999999", "2026-10-27", True, "o'brien", "\\", "x\\'; DROP TABLE t; --"]
    for _ in range(2000):
        obj = rng.choice(["t", "s.t", "d.s.t", "DROP"])
        types = {"a": rng.choice(["Utf8", "Int64", "Decimal128(38,10)", "Boolean", "Date32"]), "b": "Utf8"}
        filters = [{"column": rng.choice(list(types)), "op": rng.choice(list(spice.OPS)), "value": rng.choice(corpus)}]
        try:
            sql = spice.build_select(obj, {"select": rng.choice([[], ["a"], ["a", "b"]]), "types": types}, filters, rng.choice([None, 1, 1000]))
        except ValueError:
            continue
        assert re.fullmatch(r'SELECT (\*|"[A-Za-z0-9_]+"(, "[A-Za-z0-9_]+")*) FROM "[A-Za-z0-9_]+"(\."[A-Za-z0-9_]+"){0,2}( WHERE .+)?( LIMIT \d+)?', sql, re.S)
        # Independent scanner: doubled apostrophes stay in literals, all other SQL is structural.
        structural = re.sub(r"'(?:[^']|'')*'", "?", sql)
        structural = re.sub(r'"[A-Za-z0-9_]+"', 'identifier', structural)
        assert ";" not in structural
        assert not re.search(r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|COPY|GRANT|UNION)\b", structural)
        spice.assert_select_shape(sql, obj, set(types))


@pytest.mark.parametrize("sql", [
    'SELECT "unknown" FROM "t"', 'SELECT * FROM "t" WHERE "unknown" = 1',
    'SELECT * FROM "t"; DROP TABLE "t"', 'SELECT * FROM "other"',
    'SELECT * FROM "t" UNION SELECT * FROM "t"', 'SELECT * FROM "t" --comment',
    'SELECT * FROM "t" WHERE "a" = 1 OR true', 'SELECT * FROM "t" WHERE "a" = \'unterminated',
])
def test_guard_rejects_unknown_column_or_second_statement(sql):
    with pytest.raises(ValueError):
        spice.assert_select_shape(sql, "t", {"a"})


def test_guard_accepts_keywords_and_punctuation_inside_literals():
    spice.assert_select_shape('SELECT "a" FROM "t" WHERE "a" = \'x\'\'; DROP t; --\' LIMIT 1', "t", {"a"})


def test_build_select_checks_column_identifiers():
    with pytest.raises(ValueError):
        spice.build_select("t", {"select": ['a" FROM "evil'], "types": {'a" FROM "evil': "Utf8"}}, [], 1)


@pytest.mark.parametrize('col_type', ['Utf8', 'LargeUtf8', 'Utf8View'])
@pytest.mark.parametrize('value', ['\\', 'a\\b', "x\\'; DROP TABLE t; --"])
def test_string_literals_reject_backslash(col_type, value):
    with pytest.raises(ValueError):
        spice.build_select('t', {'select': [], 'types': {'a': col_type}},
                           [{'column': 'a', 'op': '=', 'value': value}], 1)
