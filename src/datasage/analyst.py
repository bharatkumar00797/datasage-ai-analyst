"""The analyst loop: question -> SQL (provider) -> guard -> execute -> summary."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from datasage.dataset import describe, schema_prompt
from datasage.providers import Provider
from datasage.sqlguard import QueryResult, SafeExecutor


@dataclass(frozen=True)
class Answer:
    question: str
    provider: str
    result: QueryResult
    summary: str


def summarise(result: QueryResult) -> str:
    """Deterministic plain-English summary of a result set."""
    if not result.rows:
        return "The query returned no rows."
    if len(result.rows) == 1:
        parts = [f"{c} = {v}" for c, v in zip(result.columns, result.rows[0], strict=True)]
        return "Result: " + ", ".join(parts) + "."
    first = result.rows[0]
    text = f"{len(result.rows)} rows. First: " + ", ".join(
        f"{c} = {v}" for c, v in zip(result.columns, first, strict=True)
    )
    return text + (" (truncated at the row limit)." if result.truncated else ".")


class Analyst:
    def __init__(
        self,
        conn: sqlite3.Connection,
        provider: Provider,
        max_rows: int = 500,
        timeout_ms: int = 2000,
    ) -> None:
        tables = describe(conn)
        self.schema = schema_prompt(tables)
        self.provider = provider
        self.executor = SafeExecutor(conn, [t.name for t in tables], max_rows, timeout_ms)

    def ask(self, question: str) -> Answer:
        question = question.strip()
        if not question or len(question) > 500:
            raise ValueError("question must be 1-500 characters")
        sql = self.provider.generate_sql(question, self.schema)
        result = self.executor.execute(sql)
        return Answer(question, self.provider.name, result, summarise(result))
