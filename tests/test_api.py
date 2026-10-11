from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from datasage.api import create_app
from datasage.api.security import ApiKeyAuth, RateLimiter
from datasage.api.settings import ApiSettings
from datasage.api.workspaces import WorkspaceStore
from datasage.providers import MockProvider

STATIC = Path(__file__).resolve().parents[1] / "src" / "datasage" / "api" / "static"


def client(**kw: object) -> TestClient:
    return TestClient(create_app(ApiSettings(**kw)))  # type: ignore[arg-type]


class EvilProvider:
    name = "evil"

    def generate_sql(self, question: str, schema: str, feedback: str | None = None) -> str:
        return "DROP TABLE orders"


def test_health_and_security_headers() -> None:
    r = client().get("/healthz")
    assert r.status_code == 200 and r.json()["status"] == "ok"
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-frame-options"] == "DENY"


def test_config_public_demo_forces_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATASAGE_PROVIDER", "openai")
    monkeypatch.setenv("DATASAGE_LLM_API_KEY", "sk-secret-value")
    r = client().get("/api/config")
    body = r.json()
    assert body["access_mode"] == "public-demo" and body["provider"] == "mock"
    assert "sk-secret-value" not in r.text
    assert r.headers["cache-control"] == "no-store"


def test_ask_returns_sql_rows_insights_chart() -> None:
    r = client().post("/api/ask", json={"question": "Revenue by category"})
    assert r.status_code == 200
    body = r.json()
    assert body["sql"].upper().startswith("SELECT")
    assert body["rows"] and body["chart"]["type"] == "bar"
    assert body["insights"] and body["attempts"][-1]["error"] is None


def test_ask_unknown_question_is_422() -> None:
    r = client().post("/api/ask", json={"question": "what is the meaning of life"})
    assert r.status_code == 422


def test_ask_rejects_extra_fields_and_long_question() -> None:
    c = client()
    assert c.post("/api/ask", json={"question": "x", "admin": True}).status_code == 422
    assert c.post("/api/ask", json={"question": "x" * 501}).status_code == 422


def test_malicious_model_is_blocked_with_retries() -> None:
    app = create_app(ApiSettings(dev_mode=True), provider=EvilProvider())
    r = TestClient(app).post("/api/ask", json={"question": "anything"})
    assert r.status_code == 422 and "blocked" in r.json()["detail"]
    assert "3 attempts" in r.json()["detail"]


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM orders",
        "SELECT 1; DROP TABLE orders",
        "SELECT * FROM sqlite_master",
        "PRAGMA table_info(orders)",
    ],
)
def test_raw_sql_guard(sql: str) -> None:
    r = client().post("/api/sql", json={"sql": sql})
    assert r.status_code == 422


def test_raw_sql_ok() -> None:
    r = client().post("/api/sql", json={"sql": "SELECT COUNT(*) AS n FROM orders"})
    assert r.status_code == 200 and r.json()["rows"] == [[600]]
    assert r.json()["chart"]["type"] == "metric"


def test_query_timeout_is_408() -> None:
    c = client(query_timeout_ms=50)
    sql = "WITH RECURSIVE r(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM r) SELECT max(x) FROM r"
    assert c.post("/api/sql", json={"sql": sql}).status_code == 408


def test_upload_is_private_per_caller() -> None:
    app = create_app(ApiSettings(trust_proxy=True))
    c = TestClient(app)
    a = {"X-Forwarded-For": "10.0.0.1"}
    b = {"X-Forwarded-For": "10.0.0.2"}
    up = c.post("/api/datasets", json={"name": "Sales 2026", "csv": "a,b\n1,2\n3,4\n"}, headers=a)
    assert up.status_code == 201 and up.json()["name"] == "sales_2026"
    names_a = [t["name"] for t in c.get("/api/schema", headers=a).json()["tables"]]
    names_b = [t["name"] for t in c.get("/api/schema", headers=b).json()["tables"]]
    assert "sales_2026" in names_a and "sales_2026" not in names_b
    q = {"sql": "SELECT SUM(b) FROM sales_2026"}
    assert c.post("/api/sql", json=q, headers=a).json()["rows"] == [[6]]
    assert c.post("/api/sql", json=q, headers=b).status_code == 422
    ans = c.post("/api/ask", json={"question": "show sales_2026"}, headers=a)
    assert ans.status_code == 200 and len(ans.json()["rows"]) == 2
    assert c.delete("/api/datasets", headers=a).status_code == 204
    names_a = [t["name"] for t in c.get("/api/schema", headers=a).json()["tables"]]
    assert "sales_2026" not in names_a


def test_upload_validation_and_cap() -> None:
    c = client(max_uploads_per_workspace=1)
    assert c.post("/api/datasets", json={"name": "t", "csv": "a\n"}).status_code == 422
    assert c.post("/api/datasets", json={"name": "1bad", "csv": "a\n1\n"}).status_code == 422
    assert c.post("/api/datasets", json={"name": "orders", "csv": "a\n1\n"}).status_code == 422
    assert c.post("/api/datasets", json={"name": "t1", "csv": "a\n1\n"}).status_code == 201
    assert c.post("/api/datasets", json={"name": "t2", "csv": "a\n1\n"}).status_code == 409


def test_body_cap() -> None:
    big = "a\n" + "1\n" * 700_000
    r = client().post("/api/datasets", json={"name": "big", "csv": big})
    assert r.status_code == 413


def test_examples_and_eval() -> None:
    c = client()
    ex = c.get("/api/examples").json()["examples"]
    assert len(ex) >= 5
    for q in ex:
        assert c.post("/api/ask", json={"question": q}).status_code == 200, q
    ev = c.post("/api/eval").json()
    assert ev["provider"] == "mock" and ev["passed"] == ev["total"] == 15


def test_api_key_mode() -> None:
    c = client(api_keys=("k1",))
    assert c.get("/api/schema").status_code == 401
    assert c.get("/api/schema", headers={"X-API-Key": "nope"}).status_code == 401
    assert c.get("/api/schema", headers={"X-API-Key": "k1"}).status_code == 200
    assert c.get("/api/schema", headers={"Authorization": "Bearer k1"}).status_code == 200
    assert c.get("/api/config").json()["auth_required"] is True


def test_rate_limits() -> None:
    c = client(ask_limit_per_minute=2)
    body = {"question": "How many orders do we have?"}
    assert c.post("/api/ask", json=body).status_code == 200
    assert c.post("/api/ask", json=body).status_code == 200
    r = c.post("/api/ask", json=body)
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1


def test_right_most_forwarded_hop_only_when_trusted() -> None:
    c = client(trust_proxy=True, rate_limit_per_minute=1)
    assert c.get("/api/examples", headers={"X-Forwarded-For": "1.1.1.1, 9.9.9.9"}).is_success
    # A forged left-most hop does not give the client a fresh identity.
    r = c.get("/api/examples", headers={"X-Forwarded-For": "2.2.2.2, 9.9.9.9"})
    assert r.status_code == 429


def test_dashboard_served_and_has_no_html_sinks() -> None:
    c = client()
    page = c.get("/")
    assert page.status_code == 200 and "DataSage" in page.text
    assert c.get("/static/app.js").status_code == 200
    js = (STATIC / "app.js").read_text()
    assert not re.search(r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|eval\(", js)
    assert "<script>" not in page.text  # only external scripts (strict CSP)


def test_api_key_auth_and_limiter_units() -> None:
    auth = ApiKeyAuth(("a", "b"))
    assert auth.verify("b") and auth.verify("c") is None and auth.verify(None) is None
    now = [0.0]
    lim = RateLimiter(1, 60, clock=lambda: now[0])
    assert lim.check("x") is None and lim.check("x") is not None
    now[0] = 61
    assert lim.check("x") is None


def test_workspace_store_evicts_lru() -> None:
    store = WorkspaceStore(MockProvider(), 100, 1000, max_workspaces=2)
    first = store.get("a")
    store.get("b")
    store.get("a")
    store.get("c")
    assert len(store) == 2 and store.get("a") is first


def test_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATASAGE_API_KEYS", "x, y")
    monkeypatch.setenv("DATASAGE_TRUST_PROXY", "yes")
    s = ApiSettings.from_env()
    assert s.api_keys == ("x", "y") and s.trust_proxy and s.access_mode == "api-key"
    monkeypatch.setenv("DATASAGE_TRUST_PROXY", "maybe")
    with pytest.raises(ValueError):
        ApiSettings.from_env()
