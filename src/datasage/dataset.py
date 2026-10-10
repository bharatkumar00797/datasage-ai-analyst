"""Deterministic sample retail dataset loaded into an in-memory SQLite database."""

from __future__ import annotations

import random
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta

REGIONS = ("North", "South", "East", "West")
CATEGORIES = {
    "Electronics": (("Laptop", 899.0), ("Headphones", 129.0), ("Monitor", 249.0)),
    "Home": (("Desk Lamp", 39.0), ("Office Chair", 189.0), ("Coffee Maker", 79.0)),
    "Books": (("Data Science Handbook", 45.0), ("SQL Cookbook", 35.0), ("Python Guide", 29.0)),
}
CHANNELS = ("web", "mobile", "store")

SCHEMA = """
CREATE TABLE customers (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, region TEXT NOT NULL, signup_date TEXT NOT NULL
);
CREATE TABLE products (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, category TEXT NOT NULL, price REAL NOT NULL
);
CREATE TABLE orders (
  id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL REFERENCES customers(id),
  order_date TEXT NOT NULL, channel TEXT NOT NULL
);
CREATE TABLE order_items (
  id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(id),
  product_id INTEGER NOT NULL REFERENCES products(id), quantity INTEGER NOT NULL,
  unit_price REAL NOT NULL
);
"""


@dataclass(frozen=True)
class Column:
    name: str
    type: str


@dataclass(frozen=True)
class Table:
    name: str
    columns: tuple[Column, ...]
    row_count: int


def build_sample_db(
    seed: int = 42, n_customers: int = 120, n_orders: int = 600
) -> sqlite3.Connection:
    """Create the sample retail database. Same seed -> byte-identical data."""
    rng = random.Random(seed)
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.executescript(SCHEMA)
    start = date(2025, 1, 1)
    conn.executemany(
        "INSERT INTO customers VALUES (?, ?, ?, ?)",
        [
            (
                i,
                f"Customer {i:03d}",
                rng.choice(REGIONS),
                str(start + timedelta(rng.randrange(365))),
            )
            for i in range(1, n_customers + 1)
        ],
    )
    products: list[tuple[int, str, str, float]] = []
    for category, items in CATEGORIES.items():
        for name, price in items:
            products.append((len(products) + 1, name, category, price))
    conn.executemany("INSERT INTO products VALUES (?, ?, ?, ?)", products)
    item_id = 0
    for order_id in range(1, n_orders + 1):
        day = start + timedelta(rng.randrange(365))
        conn.execute(
            "INSERT INTO orders VALUES (?, ?, ?, ?)",
            (order_id, rng.randint(1, n_customers), str(day), rng.choice(CHANNELS)),
        )
        for product in rng.sample(products, rng.randint(1, 3)):
            item_id += 1
            conn.execute(
                "INSERT INTO order_items VALUES (?, ?, ?, ?, ?)",
                (item_id, order_id, product[0], rng.randint(1, 4), product[3]),
            )
    conn.commit()
    conn.execute("PRAGMA query_only = ON")
    return conn


def describe(conn: sqlite3.Connection) -> list[Table]:
    """Return the user tables with columns and row counts (used to prompt the LLM)."""
    names = [
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        )
    ]
    tables = []
    for name in names:
        cols = tuple(Column(r[1], r[2]) for r in conn.execute(f'PRAGMA table_info("{name}")'))
        (count,) = conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()
        tables.append(Table(name, cols, int(count)))
    return tables


def schema_prompt(tables: list[Table]) -> str:
    return "\n".join(
        f"{t.name}({', '.join(f'{c.name} {c.type}' for c in t.columns)})  -- {t.row_count} rows"
        for t in tables
    )
