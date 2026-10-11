"""The analyst loop: question -> SQL (provider) -> guard -> execute -> summary."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any

from datasage.dataset import describe, schema_prompt
from datasage.insights import ChartSpec, chart_spec, narrate
from datasage.providers import Provider
from datasage.sqlguard import QueryResult, QueryTimeoutError, SafeExecutor, UnsafeQueryError
from datasage.upload import UploadedTable, load_csv

MAX_RETRIES = 2


@dataclass(frozen=True)
class Attempt:
    sql: str
    error: str | None


@dataclass(frozen=True)
class Answer:
    question: str
    provider: str
    result: QueryResult
    summary: str
    insights: list[str] = field(default_factory=list)
    chart: ChartSpec | None = None
    attempts: list[Attempt] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "provider": self.provider,
            "sql": self.result.sql,
            "columns": self.result.columns,
            "rows": [list(r) for r in self.result.rows],
            "truncated": self.result.truncated,
            "elapsed_ms": self.result.elapsed_ms,
            "summary": self.summary,
            "insights": self.insights,
            "chart": self.chart.to_dict() if self.chart else None,
            "attempts": [{"sql": a.sql, "error": a.error} for a in self.attempts],
        }


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
        max_retries: int = MAX_RETRIES,
    ) -> None:
        self.conn = conn
        self.provider = provider
        self.max_rows = max_rows
        self.timeout_ms = timeout_ms
        self.max_retries = max_retries
        self.refresh()

    def refresh(self) -> None:
        """Re-read the schema and rebuild the table allowlist (after an upload)."""
        tables = describe(self.conn)
        self.schema = schema_prompt(tables)
        self.tables = [t.name for t in tables]
        self.executor = SafeExecutor(self.conn, self.tables, self.max_rows, self.timeout_ms)

    def add_csv(self, table: str, data: bytes | str) -> UploadedTable:
        uploaded = load_csv(self.conn, table, data)
        self.refresh()
        return uploaded

    def ask(self, question: str) -> Answer:
        question = question.strip()
        if not question or len(question) > 500:
            raise ValueError("question must be 1-500 characters")
        attempts: list[Attempt] = []
        feedback: str | None = None
        for attempt in range(self.max_retries + 1):
            sql = self.provider.generate_sql(question, self.schema, feedback)
            try:
                result = self.executor.execute(sql)
            except QueryTimeoutError:
                raise  # retrying an expensive query just burns more time
            except UnsafeQueryError as exc:
                attempts.append(Attempt(sql, str(exc)))
                if attempt == self.max_retries:
                    raise UnsafeQueryError(
                        f"{exc} (gave up after {len(attempts)} attempts)"
                    ) from exc
                feedback = f"SQL: {sql}\nError: {exc}"
                continue
            attempts.append(Attempt(result.sql, None))
            return Answer(
                question,
                self.provider.name,
                result,
                summarise(result),
                narrate(result),
                chart_spec(result, question),
                attempts,
            )
        raise AssertionError("unreachable")  # pragma: no cover
