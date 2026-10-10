import sqlite3

import pytest

from datasage.sqlguard import (
    QueryTimeoutError,
    SafeExecutor,
    UnsafeQueryError,
    validate_sql,
)

TABLES = ["customers", "orders", "order_items", "products"]


@pytest.fixture
def ex(conn):
    return SafeExecutor(conn, TABLES, max_rows=10, timeout_ms=300)


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM orders",
        "UPDATE orders SET channel = 'x'",
        "DROP TABLE orders",
        "PRAGMA table_info(orders)",
        "ATTACH DATABASE '/tmp/x.db' AS x",
        "SELECT 1; DROP TABLE orders",
        "SELECT 1 /* hi */; DELETE FROM orders",
        "INSERT INTO orders VALUES (1, 1, '2025-01-01', 'web')",
        "SELECT load_extension('x')",
        "",
        "-- only a comment",
        "SELECT " + "1," * 3000 + "1",
    ],
)
def test_rejects_unsafe(sql):
    with pytest.raises(UnsafeQueryError):
        validate_sql(sql)


def test_allows_select_and_cte():
    assert validate_sql("select 1;") == "select 1"
    assert validate_sql("WITH t AS (SELECT 1 AS a) SELECT a FROM t").startswith("WITH")


def test_keywords_inside_strings_are_fine(ex):
    res = ex.execute("SELECT 'drop; delete' AS note")
    assert res.rows == [("drop; delete",)]


def test_non_allowlisted_table_blocked(conn):
    ex = SafeExecutor(conn, ["products"])
    assert ex.execute("SELECT COUNT(*) FROM products").rows == [(9,)]
    with pytest.raises(UnsafeQueryError, match="not allowed"):
        ex.execute("SELECT * FROM customers")


def test_system_tables_blocked(ex):
    with pytest.raises(UnsafeQueryError):
        ex.execute("SELECT * FROM sqlite_master")


def test_row_cap(ex):
    res = ex.execute("SELECT id FROM orders")
    assert len(res.rows) == 10
    assert res.truncated


def test_timeout(ex):
    q = "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r) SELECT COUNT(*) FROM r"
    with pytest.raises(QueryTimeoutError):
        ex.execute(q)


def test_connection_is_read_only(conn):
    with pytest.raises(
        sqlite3.OperationalError, match=r"readonly|read-only|query_only|attempt to write"
    ):
        conn.execute("DELETE FROM orders")


def test_authorizer_reset_after_query(ex, conn):
    ex.execute("SELECT 1")
    assert conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0] > 0
