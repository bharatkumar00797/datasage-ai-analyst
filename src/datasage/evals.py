"""Execution-accuracy evaluation: run each question through the analyst and compare the
result set with the result of a hand-written gold query on the same database."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from importlib import resources
from typing import Any

from datasage.analyst import Analyst
from datasage.providers import UnknownQuestionError
from datasage.sqlguard import UnsafeQueryError


@dataclass(frozen=True)
class EvalCase:
    question: str
    gold_sql: str
    compare: str = "rows"  # "rows" (all values) or "last_column" (measure only)


@dataclass(frozen=True)
class EvalResult:
    question: str
    passed: bool
    detail: str
    attempts: int


def load_cases() -> list[EvalCase]:
    raw = resources.files("datasage").joinpath("data/eval_set.json").read_text("utf-8")
    return [EvalCase(**c) for c in json.loads(raw)]


def _normalise(rows: list[tuple[Any, ...]], mode: str) -> list[tuple[Any, ...]]:
    def norm(v: Any) -> Any:
        return round(float(v), 2) if isinstance(v, int | float) else v

    if mode == "last_column":
        return [(norm(r[-1]),) for r in rows]
    return [tuple(norm(v) for v in r) for r in rows]


def run_eval(
    analyst: Analyst, conn: sqlite3.Connection, cases: list[EvalCase] | None = None
) -> list[EvalResult]:
    out: list[EvalResult] = []
    for case in cases if cases is not None else load_cases():
        expected = _normalise(conn.execute(case.gold_sql).fetchall(), case.compare)
        try:
            ans = analyst.ask(case.question)
        except (UnsafeQueryError, UnknownQuestionError, ValueError) as exc:
            out.append(EvalResult(case.question, False, f"error: {exc}", 0))
            continue
        got = _normalise(ans.result.rows, case.compare)
        ok = got == expected
        detail = "match" if ok else f"expected {expected[:3]}..., got {got[:3]}..."
        out.append(EvalResult(case.question, ok, detail, len(ans.attempts)))
    return out


def accuracy(results: list[EvalResult]) -> float:
    return sum(r.passed for r in results) / len(results) if results else 0.0
