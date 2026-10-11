import json

import pytest

from datasage import __version__
from datasage.analyst import Analyst
from datasage.cli import main
from datasage.providers import MockProvider, UnknownQuestionError, extract_sql


@pytest.mark.parametrize(
    ("question", "column"),
    [
        ("What is the total revenue?", "total_revenue"),
        ("Revenue by category", "category"),
        ("Which region sells the most?", "region"),
        ("Show the monthly revenue trend", "month"),
        ("Top 3 customers", "name"),
        ("best selling products", "units_sold"),
        ("average order value", "average_order_value"),
        ("orders per channel", "channel"),
        ("How many customers do we have?", "customers"),
    ],
)
def test_mock_answers(conn, question, column):
    ans = Analyst(conn, MockProvider()).ask(question)
    assert column in ans.result.columns
    assert ans.result.rows
    assert ans.summary


def test_top_n(conn):
    assert len(Analyst(conn, MockProvider()).ask("top 7 customers").result.rows) == 7


def test_unknown_question(conn):
    with pytest.raises(UnknownQuestionError):
        Analyst(conn, MockProvider()).ask("what is the meaning of life")


class EvilProvider:
    name = "evil"

    def generate_sql(self, question: str, schema: str, feedback: str | None = None) -> str:
        return "DROP TABLE orders"


def test_malicious_model_output_is_blocked(conn):
    from datasage.sqlguard import UnsafeQueryError

    with pytest.raises(UnsafeQueryError):
        Analyst(conn, EvilProvider()).ask("anything")
    assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 600


def test_extract_sql():
    assert extract_sql("```sql\nSELECT 1\n```") == "SELECT 1"
    assert extract_sql(" SELECT 2 ") == "SELECT 2"


def test_cli_version(capsys):
    with pytest.raises(SystemExit):
        main(["--version"])
    assert __version__ in capsys.readouterr().out


def test_cli_ask_json(capsys):
    assert main(["ask", "revenue by category", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["provider"] == "mock"
    assert len(data["rows"]) == 3


def test_cli_blocks_writes(capsys):
    assert main(["sql", "DELETE FROM orders"]) == 2
    assert "only SELECT" in capsys.readouterr().err
