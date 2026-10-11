from datasage.insights import chart_spec, detect_shape, narrate
from datasage.sqlguard import QueryResult


def res(columns, rows, truncated=False):
    return QueryResult("SELECT 1", columns, rows, truncated, 0.0)


def test_category_narration_uses_real_numbers():
    r = res(["region", "revenue"], [("North", 300.0), ("South", 100.0)])
    lines = narrate(r)
    assert lines[0] == "North leads revenue with 300."
    assert "75.0%" in lines[1]
    assert "South is lowest at 100." in lines
    assert "3.0x" in lines[-1]


def test_time_series_narration():
    r = res(["month", "revenue"], [("2025-01", 100), ("2025-02", 50), ("2025-03", 150)])
    lines = narrate(r)
    assert "+50.0%" in lines[0]
    assert "Peak was 2025-03" in lines[1]
    assert "2025-02 -> 2025-03" in lines[2] and "rise" in lines[2]


def test_single_row_and_empty():
    assert narrate(res(["a", "b"], [(1, 2.5)])) == ["a is 1.", "b is 2.50."]
    assert narrate(res(["a"], [])) == ["No data matched the question."]
    assert "no numeric" in narrate(res(["name"], [("x",), ("y",)]))[0]


def test_truncated_flagged():
    r = res(["k", "v"], [("a", 1), ("b", 2)], truncated=True)
    assert any("truncated" in s for s in narrate(r))


def test_chart_types():
    assert chart_spec(res(["month", "v"], [("2025-01", 1), ("2025-02", 2)])).type == "line"
    bar = chart_spec(res(["k", "v"], [("a", 1), ("b", 2)]), "t")
    assert (bar.type, bar.x, bar.y, bar.title) == ("bar", "k", "v", "t")
    assert chart_spec(res(["v"], [(3,)])).type == "metric"
    assert chart_spec(res(["k"], [("a",)])).type == "table"
    many = res(["k", "v"], [(f"c{i}", i) for i in range(40)])
    assert chart_spec(many).type == "table"
    assert chart_spec(res(["k", "v"], [("a", 1)])).to_dict()["type"] == "metric"


def test_bool_is_not_a_measure():
    assert detect_shape(res(["k", "flag"], [("a", True), ("b", False)])).measure is None
