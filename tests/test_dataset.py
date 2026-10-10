from datasage.dataset import build_sample_db, describe, schema_prompt


def test_tables_and_counts(conn):
    tables = {t.name: t.row_count for t in describe(conn)}
    assert tables["customers"] == 120
    assert tables["orders"] == 600
    assert tables["products"] == 9
    assert tables["order_items"] > 600


def test_deterministic():
    a = build_sample_db().execute("SELECT SUM(quantity * unit_price) FROM order_items").fetchone()
    b = build_sample_db().execute("SELECT SUM(quantity * unit_price) FROM order_items").fetchone()
    assert a == b


def test_schema_prompt_lists_columns(conn):
    text = schema_prompt(describe(conn))
    assert "orders(id INTEGER, customer_id INTEGER" in text
