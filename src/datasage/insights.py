"""Deterministic insight narration and chart specs derived from a result set.

Numbers in the narration are computed here from the actual rows, never by the LLM, so
the story cannot contain hallucinated figures.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from datasage.sqlguard import QueryResult

_PERIOD = re.compile(r"^\d{4}-\d{2}(-\d{2})?$")
MAX_BAR_CATEGORIES = 25


def _is_number(v: object) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool)


def _fmt(v: float) -> str:
    return f"{v:,.0f}" if float(v).is_integer() else f"{v:,.2f}"


@dataclass(frozen=True)
class Shape:
    """Which column is the label (dimension) and which is the measure, if any."""

    label: int | None
    measure: int | None
    temporal: bool


def detect_shape(result: QueryResult) -> Shape:
    if not result.rows or not result.columns:
        return Shape(None, None, False)
    first = result.rows[0]
    numeric = [i for i, v in enumerate(first) if all(_is_number(r[i]) for r in result.rows)]
    labels = [i for i in range(len(first)) if i not in numeric]
    measure = numeric[-1] if numeric else None
    label = labels[0] if labels else None
    temporal = label is not None and all(
        isinstance(r[label], str) and _PERIOD.match(r[label]) for r in result.rows
    )
    return Shape(label, measure, temporal)


def narrate(result: QueryResult) -> list[str]:
    """Return short, fact-checked insight sentences for the result."""
    shape = detect_shape(result)
    rows = result.rows
    if not rows:
        return ["No data matched the question."]
    if shape.measure is None:
        return [f"{len(rows)} rows returned; no numeric measure to analyse."]
    col = result.columns[shape.measure]
    values = [float(r[shape.measure]) for r in rows]
    if len(rows) == 1 or shape.label is None:
        if len(rows) == 1:
            return [
                f"{c} is {_fmt(float(v))}."
                for c, v in zip(result.columns, rows[0], strict=True)
                if _is_number(v)
            ]
        return [f"{col} ranges from {_fmt(min(values))} to {_fmt(max(values))}."]
    labels = [str(r[shape.label]) for r in rows]
    total = sum(values)
    out: list[str] = []
    if shape.temporal:
        out.append(
            f"{col} went from {_fmt(values[0])} in {labels[0]} to {_fmt(values[-1])} in "
            f"{labels[-1]} ({_pct(values[0], values[-1])})."
        )
        peak = max(range(len(values)), key=values.__getitem__)
        low = min(range(len(values)), key=values.__getitem__)
        out.append(f"Peak was {labels[peak]} ({_fmt(values[peak])}); low was {labels[low]}.")
        if len(values) > 2:
            deltas = [(values[i] - values[i - 1], i) for i in range(1, len(values))]
            d, i = max(deltas, key=lambda t: abs(t[0]))
            direction = "rise" if d > 0 else "drop"
            out.append(
                f"Biggest period-over-period {direction}: {labels[i - 1]} -> {labels[i]} "
                f"({_pct(values[i - 1], values[i])})."
            )
        return out
    top = max(range(len(values)), key=values.__getitem__)
    bottom = min(range(len(values)), key=values.__getitem__)
    out.append(f"{labels[top]} leads {col} with {_fmt(values[top])}.")
    if total > 0 and all(v >= 0 for v in values):
        out.append(f"{labels[top]} accounts for {values[top] / total:.1%} of the total shown.")
    if bottom != top:
        out.append(f"{labels[bottom]} is lowest at {_fmt(values[bottom])}.")
    if values[bottom] > 0 and bottom != top:
        out.append(f"The top value is {values[top] / values[bottom]:.1f}x the lowest.")
    if result.truncated:
        out.append("Results were truncated at the row limit, so totals are partial.")
    return out


def _pct(old: float, new: float) -> str:
    if old == 0:
        return "n/a"
    return f"{(new - old) / abs(old):+.1%}"


@dataclass(frozen=True)
class ChartSpec:
    """Renderer-agnostic chart description (the dashboard draws it as SVG)."""

    type: str  # "line" | "bar" | "metric" | "table"
    title: str
    x: str | None = None
    y: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def chart_spec(result: QueryResult, title: str = "") -> ChartSpec:
    shape = detect_shape(result)
    title = title or "Result"
    if shape.measure is None or not result.rows:
        return ChartSpec("table", title)
    y = result.columns[shape.measure]
    if len(result.rows) == 1:
        return ChartSpec("metric", title, None, y)
    if shape.label is None:
        return ChartSpec("table", title)
    x = result.columns[shape.label]
    if shape.temporal:
        return ChartSpec("line", title, x, y)
    if len(result.rows) <= MAX_BAR_CATEGORIES:
        return ChartSpec("bar", title, x, y)
    return ChartSpec("table", title)
