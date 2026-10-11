"""Load a user-supplied CSV as a new allowlisted, read-only table.

The CSV is untrusted: size, row and column counts are capped, identifiers are sanitised
to ``[a-z_][a-z0-9_]*``, values are bound as parameters (never interpolated), and the
table name must not clash with an existing table.
"""

from __future__ import annotations

import csv
import io
import re
import sqlite3
from dataclasses import dataclass

MAX_BYTES = 1_000_000
MAX_ROWS = 20_000
MAX_COLUMNS = 50
_IDENT = re.compile(r"[^a-z0-9_]+")
_INT = re.compile(r"^[+-]?\d{1,18}$")
_FLOAT = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")


class UploadError(ValueError):
    """The CSV was rejected."""


@dataclass(frozen=True)
class UploadedTable:
    name: str
    columns: list[tuple[str, str]]
    row_count: int


def sanitize_identifier(raw: str, fallback: str) -> str:
    ident = _IDENT.sub("_", raw.strip().lower()).strip("_")[:40]
    if not ident:
        ident = fallback
    if ident[0].isdigit():
        ident = f"c_{ident}"
    return ident


def _infer(values: list[str]) -> str:
    present = [v for v in values if v != ""]
    if present and all(_INT.match(v) for v in present):
        return "INTEGER"
    if present and all(_FLOAT.match(v) for v in present):
        return "REAL"
    return "TEXT"


def _convert(value: str, kind: str) -> object:
    if value == "":
        return None
    if kind == "INTEGER":
        return int(value)
    if kind == "REAL":
        return float(value)
    return value


def load_csv(
    conn: sqlite3.Connection,
    table: str,
    data: bytes | str,
    *,
    max_bytes: int = MAX_BYTES,
    max_rows: int = MAX_ROWS,
    max_columns: int = MAX_COLUMNS,
) -> UploadedTable:
    raw = data.encode() if isinstance(data, str) else data
    if len(raw) > max_bytes:
        raise UploadError(f"CSV is larger than {max_bytes} bytes")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise UploadError("CSV must be UTF-8 encoded") from exc
    if "\x00" in text:
        raise UploadError("CSV contains NUL bytes")
    try:
        reader = list(csv.reader(io.StringIO(text)))
    except csv.Error as exc:
        raise UploadError(f"malformed CSV: {exc}") from exc
    if len(reader) < 2:
        raise UploadError("CSV needs a header row and at least one data row")
    header, body = reader[0], reader[1:]
    if len(header) > max_columns:
        raise UploadError(f"CSV has more than {max_columns} columns")
    if len(body) > max_rows:
        raise UploadError(f"CSV has more than {max_rows} rows")
    if any(len(r) != len(header) for r in body):
        raise UploadError("every row must have the same number of fields as the header")

    name = sanitize_identifier(table, "upload")
    if name.startswith("sqlite_"):
        raise UploadError("table name is reserved")
    existing = {
        r[0].lower() for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    if name in existing:
        raise UploadError(f"table '{name}' already exists")
    cols: list[str] = []
    for i, h in enumerate(header):
        col = sanitize_identifier(h, f"col_{i + 1}")
        while col in cols:
            col += "_"
        cols.append(col)
    kinds = [_infer([r[i].strip() for r in body]) for i in range(len(cols))]
    rows = [tuple(_convert(r[i].strip(), kinds[i]) for i in range(len(cols))) for r in body]

    ddl = ", ".join(f'"{c}" {k}' for c, k in zip(cols, kinds, strict=True))
    placeholders = ", ".join("?" for _ in cols)
    conn.execute("PRAGMA query_only = OFF")
    try:
        with conn:
            conn.execute(f'CREATE TABLE "{name}" ({ddl})')
            conn.executemany(f'INSERT INTO "{name}" VALUES ({placeholders})', rows)
    finally:
        conn.execute("PRAGMA query_only = ON")
    return UploadedTable(name, list(zip(cols, kinds, strict=True)), len(rows))
