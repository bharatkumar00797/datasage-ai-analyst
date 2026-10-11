import json

import pytest

from datasage.analyst import Analyst
from datasage.cli import main
from datasage.evals import EvalCase, accuracy, load_cases, run_eval
from datasage.providers import MockProvider
from datasage.sqlguard import QueryTimeoutError, UnsafeQueryError


class SelfCorrecting:
    """First reply is unsafe; once given the guard error it returns valid SQL."""

    name = "fake"

    def __init__(self) -> None:
        self.feedback: list[str | None] = []

    def generate_sql(self, question: str, schema: str, feedback: str | None = None) -> str:
        self.feedback.append(feedback)
        if feedback is None:
            return "SELECT * FROM sqlite_master"
        return "SELECT COUNT(*) AS n FROM orders"


class Stubborn:
    name = "stubborn"
    calls = 0

    def generate_sql(self, question: str, schema: str, feedback: str | None = None) -> str:
        self.calls += 1
        return "DELETE FROM orders"


def test_guard_error_is_fed_back_and_retried(conn):
    p = SelfCorrecting()
    ans = Analyst(conn, p).ask("count orders")
    assert ans.result.rows == [(600,)]
    assert len(ans.attempts) == 2 and ans.attempts[0].error and ans.attempts[1].error is None
    assert p.feedback[1] is not None and "sqlite_master" in p.feedback[1]
    assert "not allowed" in p.feedback[1]
    assert ans.to_dict()["attempts"][0]["error"]


def test_retry_budget_is_bounded(conn):
    p = Stubborn()
    with pytest.raises(UnsafeQueryError, match="after 3 attempts"):
        Analyst(conn, p, max_retries=2).ask("x")
    assert p.calls == 3
    assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 600


def test_timeout_is_not_retried(conn):
    class Slow:
        name = "slow"
        calls = 0

        def generate_sql(self, question: str, schema: str, feedback: str | None = None) -> str:
            self.calls += 1
            return (
                "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c) "
                "SELECT COUNT(*) FROM c"
            )

    p = Slow()
    with pytest.raises(QueryTimeoutError):
        Analyst(conn, p, timeout_ms=100).ask("x")
    assert p.calls == 1


def test_answer_has_insights_and_chart(conn):
    ans = Analyst(conn, MockProvider()).ask("revenue by region")
    assert ans.chart is not None and ans.chart.type == "bar"
    assert ans.insights and "leads revenue" in ans.insights[0]


@pytest.mark.parametrize(
    ("question", "column"),
    [
        ("new customer signups", "new_customers"),
        ("orders by weekday", "weekday"),
        ("revenue by channel", "channel"),
        ("average items per order", "avg_items_per_order"),
        ("sales by product", "revenue"),
    ],
)
def test_new_intents(conn, question, column):
    assert column in Analyst(conn, MockProvider()).ask(question).result.columns


def test_mock_passes_full_eval_set(conn):
    results = run_eval(Analyst(conn, MockProvider()), conn)
    assert len(results) == len(load_cases()) >= 15
    assert accuracy(results) == 1.0


def test_eval_reports_failures(conn):
    cases = [
        EvalCase("total revenue", "SELECT 1"),
        EvalCase("meaning of life", "SELECT 1"),
    ]
    results = run_eval(Analyst(conn, MockProvider()), conn, cases)
    assert [r.passed for r in results] == [False, False]
    assert results[1].detail.startswith("error")
    assert accuracy([]) == 0.0


def test_cli_eval(capsys):
    assert main(["eval", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["accuracy"] == 1.0


def test_cli_ask_json_has_insights(capsys):
    assert main(["ask", "monthly revenue trend", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["chart"]["type"] == "line" and out["insights"]


def test_cli_csv(tmp_path, capsys):
    f = tmp_path / "s.csv"
    f.write_text("store,visits\nA,1\nB,2\n")
    assert main(["sql", "SELECT SUM(visits) FROM stores", "--csv", f"stores={f}"]) == 0
    assert "3" in capsys.readouterr().out
    assert main(["schema", "--csv", "bad"]) == 2
    assert main(["schema", "--csv", f"x={tmp_path / 'missing.csv'}"]) == 2
