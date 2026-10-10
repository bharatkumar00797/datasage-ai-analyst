"""Read-only SQL guardrails.

Defence in depth:
1. Lexical validation: one statement, must be SELECT/WITH, no write/admin keywords,
   comments stripped, string literals ignored when scanning keywords.
2. SQLite authorizer: at execution time only SELECT/READ/FUNCTION actions on
   allowlisted tables are permitted - anything else is denied by the engine itself.
3. Row cap (LIMIT wrapper) and a wall-clock timeout via the progress handler.
4. The connection is opened with ``PRAGMA query_only``.
"""

from __future__ import annotations

import re
import sqlite3
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

FORBIDDEN = frozenset(
    {
        "INSERT", "UPDATE", "DELETE", "REPLACE", "UPSERT", "MERGE", "CREATE", "DROP", "ALTER",
        "ATTACH", "DETACH", "PRAGMA", "VACUUM", "REINDEX", "ANALYZE", "BEGIN", "COMMIT",
        "ROLLBACK", "SAVEPOINT", "RELEASE", "TRUNCATE", "GRANT", "REVOKE", "LOAD_EXTENSION",
    }
)  # fmt: skip
FORBIDDEN_FUNCTIONS = frozenset({"load_extension", "readfile", "writefile", "edit", "randomblob"})
MAX_SQL_LENGTH = 4000
_SQLITE_RECURSIVE: int = getattr(sqlite3, "SQLITE_RECURSIVE", 33)

_STRING = re.compile(r"'(?:[^']|'')*'")
_LINE_COMMENT = re.compile(r"--[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class UnsafeQueryError(ValueError):
    """Raised when SQL fails validation or is blocked at execution time."""


class QueryTimeoutError(UnsafeQueryError):
    """Raised when a query exceeds the time budget."""


@dataclass(frozen=True)
class QueryResult:
    sql: str
    columns: list[str]
    rows: list[tuple[Any, ...]]
    truncated: bool
    elapsed_ms: float = field(compare=False)


def strip_comments(sql: str) -> str:
    return _LINE_COMMENT.sub(" ", _BLOCK_COMMENT.sub(" ", sql))


def validate_sql(sql: str) -> str:
    """Return a normalised single SELECT statement or raise UnsafeQueryError."""
    if len(sql) > MAX_SQL_LENGTH:
        raise UnsafeQueryError("query is too long")
    cleaned = strip_comments(sql).strip().rstrip(";").strip()
    if not cleaned:
        raise UnsafeQueryError("empty query")
    no_strings = _STRING.sub("''", cleaned)
    if ";" in no_strings:
        raise UnsafeQueryError("only a single statement is allowed")
    words = [w.upper() for w in _WORD.findall(no_strings)]
    if not words or words[0] not in {"SELECT", "WITH"}:
        raise UnsafeQueryError("only SELECT queries are allowed")
    bad = sorted(set(words) & FORBIDDEN)
    if bad:
        raise UnsafeQueryError(f"forbidden keyword: {bad[0]}")
    funcs = {w.lower() for w in words} & FORBIDDEN_FUNCTIONS
    if funcs:
        raise UnsafeQueryError(f"forbidden function: {sorted(funcs)[0]}")
    return cleaned


class SafeExecutor:
    """Executes validated SELECTs against allowlisted tables with row/time limits."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        allowed_tables: Iterable[str],
        max_rows: int = 500,
        timeout_ms: int = 2000,
    ) -> None:
        self.conn = conn
        self.allowed = {t.lower() for t in allowed_tables}
        self.max_rows = max_rows
        self.timeout_ms = timeout_ms
        conn.execute("PRAGMA query_only = ON")

    def _authorizer(
        self, action: int, arg1: str | None, arg2: str | None, db: str | None, trigger: str | None
    ) -> int:
        if action in (sqlite3.SQLITE_SELECT, _SQLITE_RECURSIVE):
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_READ:
            if not db:  # CTE / subquery column, not a stored table
                return sqlite3.SQLITE_OK
            if arg1 is not None and arg1.lower() in self.allowed and db == "main":
                return sqlite3.SQLITE_OK
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_FUNCTION:
            if arg2 is not None and arg2.lower() in FORBIDDEN_FUNCTIONS:
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY

    def execute(self, sql: str) -> QueryResult:
        cleaned = validate_sql(sql)
        wrapped = f"SELECT * FROM ({cleaned}) LIMIT {self.max_rows + 1}"
        deadline = time.monotonic() + self.timeout_ms / 1000
        timed_out = False

        def progress() -> int:
            nonlocal timed_out
            if time.monotonic() > deadline:
                timed_out = True
                return 1
            return 0

        start = time.perf_counter()
        self.conn.set_authorizer(self._authorizer)
        self.conn.set_progress_handler(progress, 1000)
        try:
            cur = self.conn.execute(wrapped)
            rows = cur.fetchall()
            columns = [d[0] for d in cur.description or ()]
        except sqlite3.DatabaseError as exc:
            if timed_out:
                raise QueryTimeoutError(f"query exceeded {self.timeout_ms} ms") from exc
            if "not authorized" in str(exc) or "prohibited" in str(exc):
                raise UnsafeQueryError("query touches a table or action that is not allowed") from exc
            raise UnsafeQueryError(f"query failed: {exc}") from exc
        finally:
            self.conn.set_authorizer(None)
            self.conn.set_progress_handler(None, 0)
        truncated = len(rows) > self.max_rows
        return QueryResult(
            sql=cleaned,
            columns=columns,
            rows=rows[: self.max_rows],
            truncated=truncated,
            elapsed_ms=round((time.perf_counter() - start) * 1000, 2),
        )
