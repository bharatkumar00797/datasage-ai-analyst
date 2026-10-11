"""Request and response models (unknown fields are rejected)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AskIn(StrictModel):
    question: str = Field(min_length=1, max_length=500)


class SqlIn(StrictModel):
    sql: str = Field(min_length=1, max_length=4000)


class DatasetIn(StrictModel):
    name: str = Field(min_length=1, max_length=40, pattern=r"^[A-Za-z][A-Za-z0-9_ -]*$")
    csv: str = Field(min_length=1, max_length=1_000_000)


class ColumnOut(BaseModel):
    name: str
    type: str


class TableOut(BaseModel):
    name: str
    row_count: int
    columns: list[ColumnOut]
    uploaded: bool = False


class SchemaOut(BaseModel):
    tables: list[TableOut]


class DatasetOut(BaseModel):
    name: str
    row_count: int
    columns: list[ColumnOut]


class AttemptOut(BaseModel):
    sql: str
    error: str | None


class ChartOut(BaseModel):
    type: str
    title: str
    x: str | None = None
    y: str | None = None


class AnswerOut(BaseModel):
    question: str
    provider: str
    sql: str
    columns: list[str]
    rows: list[list[Any]]
    truncated: bool
    elapsed_ms: float
    summary: str
    insights: list[str]
    chart: ChartOut | None
    attempts: list[AttemptOut]


class SqlOut(BaseModel):
    sql: str
    columns: list[str]
    rows: list[list[Any]]
    truncated: bool
    elapsed_ms: float
    insights: list[str]
    chart: ChartOut | None


class ExamplesOut(BaseModel):
    examples: list[str]


class EvalCaseOut(BaseModel):
    question: str
    passed: bool
    detail: str
    attempts: int


class EvalOut(BaseModel):
    provider: str
    accuracy: float
    passed: int
    total: int
    results: list[EvalCaseOut]


class HealthOut(BaseModel):
    status: str
    version: str


class ConfigOut(BaseModel):
    version: str
    access_mode: str
    auth_required: bool
    provider: str
    raw_sql_allowed: bool
    max_rows: int
    query_timeout_ms: int
    max_upload_bytes: int
    max_uploads: int
    rate_limit_per_minute: int
    ask_limit_per_minute: int
