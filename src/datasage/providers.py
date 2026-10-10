"""LLM providers that translate a question + schema into SQL.

``MockProvider`` is the offline, deterministic default: a small intent matcher that maps
common analytics questions on the sample dataset to vetted SQL. ``OpenAICompatibleProvider``
talks to any OpenAI-style chat API (OpenAI, Groq, Ollama). Whatever SQL a provider returns
is untrusted and always goes through the SQL guard before execution.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Protocol

import httpx

REVENUE = "SUM(oi.quantity * oi.unit_price)"


class Provider(Protocol):
    name: str

    def generate_sql(self, question: str, schema: str) -> str: ...


@dataclass(frozen=True)
class Intent:
    name: str
    patterns: tuple[str, ...]
    sql: str


INTENTS: tuple[Intent, ...] = (
    Intent(
        "revenue_by_month",
        (r"\b(month|monthly|trend|over time)\b",),
        f"SELECT substr(o.order_date, 1, 7) AS month, ROUND({REVENUE}, 2) AS revenue "
        "FROM orders o JOIN order_items oi ON oi.order_id = o.id GROUP BY month ORDER BY month",
    ),
    Intent(
        "revenue_by_category",
        (r"\bcategor",),
        f"SELECT p.category, ROUND({REVENUE}, 2) AS revenue FROM order_items oi "
        "JOIN products p ON p.id = oi.product_id GROUP BY p.category ORDER BY revenue DESC",
    ),
    Intent(
        "revenue_by_region",
        (r"\bregion",),
        f"SELECT c.region, ROUND({REVENUE}, 2) AS revenue FROM orders o "
        "JOIN customers c ON c.id = o.customer_id JOIN order_items oi ON oi.order_id = o.id "
        "GROUP BY c.region ORDER BY revenue DESC",
    ),
    Intent(
        "orders_by_channel",
        (r"\bchannel",),
        "SELECT channel, COUNT(*) AS orders FROM orders GROUP BY channel ORDER BY orders DESC",
    ),
    Intent(
        "top_customers",
        (r"\b(top|best|biggest)\b.*\bcustomer",),
        f"SELECT c.name, c.region, ROUND({REVENUE}, 2) AS revenue FROM orders o "
        "JOIN customers c ON c.id = o.customer_id JOIN order_items oi ON oi.order_id = o.id "
        "GROUP BY c.id ORDER BY revenue DESC LIMIT {n}",
    ),
    Intent(
        "top_products",
        (r"\b(top|best|most)\b.*\bproduct", r"\bbest[- ]?sell"),
        "SELECT p.name, p.category, SUM(oi.quantity) AS units_sold, "
        f"ROUND({REVENUE}, 2) AS revenue FROM order_items oi "
        "JOIN products p ON p.id = oi.product_id GROUP BY p.id ORDER BY units_sold DESC LIMIT {n}",
    ),
    Intent(
        "average_order_value",
        (r"\baverage order\b", r"\baov\b"),
        "SELECT ROUND(AVG(total), 2) AS average_order_value FROM (SELECT o.id, "
        f"{REVENUE} AS total FROM orders o JOIN order_items oi ON oi.order_id = o.id "
        "GROUP BY o.id)",
    ),
    Intent(
        "total_revenue",
        (r"\b(total|overall)\b.*\b(revenue|sales)\b", r"\bhow much\b.*\b(revenue|sales|sold)\b"),
        f"SELECT ROUND({REVENUE}, 2) AS total_revenue, COUNT(DISTINCT oi.order_id) AS orders "
        "FROM order_items oi",
    ),
    Intent(
        "customer_count",
        (r"\bhow many customers\b", r"\bnumber of customers\b"),
        "SELECT COUNT(*) AS customers FROM customers",
    ),
    Intent(
        "order_count",
        (r"\bhow many orders\b", r"\bnumber of orders\b"),
        "SELECT COUNT(*) AS orders FROM orders",
    ),
)

_TOP_N = re.compile(r"\btop\s+(\d{1,3})\b")


class UnknownQuestionError(ValueError):
    """The mock provider has no intent for this question."""


class MockProvider:
    """Deterministic offline provider: keyword intents -> vetted SQL templates."""

    name = "mock"

    def match(self, question: str) -> Intent | None:
        q = question.lower()
        for intent in INTENTS:
            if any(re.search(p, q) for p in intent.patterns):
                return intent
        return None

    def generate_sql(self, question: str, schema: str) -> str:
        intent = self.match(question)
        if intent is None:
            raise UnknownQuestionError(
                "the offline mock provider does not understand this question; try e.g. "
                "'revenue by category', 'top 5 customers' or 'monthly revenue trend'"
            )
        m = _TOP_N.search(question.lower())
        n = min(int(m.group(1)), 100) if m else 5
        return intent.sql.replace("{n}", str(n))


SYSTEM_PROMPT = (
    "You are a careful data analyst. Translate the user's question into ONE read-only SQLite "
    "SELECT statement using only the tables and columns in the schema. Reply with SQL only, "
    "no explanations, no markdown."
)
_FENCE = re.compile(r"```(?:sql)?\s*(.*?)```", re.S | re.I)


def extract_sql(text: str) -> str:
    m = _FENCE.search(text)
    return (m.group(1) if m else text).strip()


class OpenAICompatibleProvider:
    """Any OpenAI-style /chat/completions endpoint (OpenAI, Groq, Ollama, ...)."""

    name = "openai"

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def generate_sql(self, question: str, schema: str) -> str:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Schema:\n{schema}\n\nQuestion: {question}"},
            ],
        }
        resp = httpx.post(
            f"{self.base_url}/chat/completions", json=payload, headers=headers, timeout=self.timeout
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        return extract_sql(str(content))


def provider_from_env() -> Provider:
    if os.environ.get("DATASAGE_PROVIDER", "mock").lower() == "openai":
        return OpenAICompatibleProvider(
            os.environ.get("DATASAGE_LLM_BASE_URL", "https://api.openai.com/v1"),
            os.environ.get("DATASAGE_LLM_API_KEY", ""),
            os.environ.get("DATASAGE_LLM_MODEL", "gpt-4o-mini"),
        )
    return MockProvider()
