import pytest

from datasage.analyst import Analyst
from datasage.providers import MockProvider
from datasage.sqlguard import UnsafeQueryError
from datasage.upload import UploadError, load_csv, sanitize_identifier

CSV = "Store Name,Visits,Rating,Note\nA,10,4.5,ok\nB,30,3.9,\nC,20,4.1,'; DROP TABLE orders; --\n"


def test_upload_becomes_queryable_read_only_table(conn):
    a = Analyst(conn, MockProvider())
    up = a.add_csv("Stores 2025!", CSV)
    assert up.name == "stores_2025"
    assert up.columns == [
        ("store_name", "TEXT"),
        ("visits", "INTEGER"),
        ("rating", "REAL"),
        ("note", "TEXT"),
    ]
    assert "stores_2025" in a.tables and "stores_2025(" in a.schema
    res = a.executor.execute("SELECT SUM(visits) FROM stores_2025")
    assert res.rows == [(60,)]
    assert a.ask("how many rows in stores_2025").result.rows == [(3,)]
    assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 600
    with pytest.raises(Exception, match="readonly"):
        conn.execute("DELETE FROM stores_2025")
    with pytest.raises(UnsafeQueryError):
        a.executor.execute("DELETE FROM stores_2025")


@pytest.mark.parametrize(
    ("data", "kwargs", "msg"),
    [
        ("a\n" + "1\n" * 5, {"max_rows": 3}, "rows"),
        ("x" * 50, {"max_bytes": 10}, "larger"),
        (",".join(f"c{i}" for i in range(5)) + "\n" + ",".join("1" * 5), {"max_columns": 4}, "col"),
        ("a,b\n1\n", {}, "same number"),
        ("a,b\n", {}, "header row"),
        (b"a\n\xff\n", {}, "UTF-8"),
        ("a\n\x00\n", {}, "NUL"),
    ],
)
def test_rejections(conn, data, kwargs, msg):
    with pytest.raises(UploadError, match=msg):
        load_csv(conn, "t", data, **kwargs)


def test_name_clash_and_reserved(conn):
    with pytest.raises(UploadError, match="exists"):
        load_csv(conn, "orders", "a\n1\n")
    with pytest.raises(UploadError, match="reserved"):
        load_csv(conn, "sqlite_master", "a\n1\n")


def test_sanitize_identifier():
    assert sanitize_identifier('x"; drop', "f") == "x_drop"
    assert sanitize_identifier("2024 sales", "f") == "c_2024_sales"
    assert sanitize_identifier("!!!", "fallback") == "fallback"


def test_duplicate_headers_are_deduplicated(conn):
    up = load_csv(conn, "dups", "a,A,a\n1,2,3\n")
    assert [c for c, _ in up.columns] == ["a", "a_", "a__"]
