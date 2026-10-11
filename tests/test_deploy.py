from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]


def test_env_example_documents_every_setting() -> None:
    documented = set(re.findall(r"^(DATASAGE_[A-Z_]+)=", (ROOT / ".env.example").read_text(), re.M))
    src = "\n".join(p.read_text() for p in (ROOT / "src").rglob("*.py"))
    used = set(re.findall(r"\"(DATASAGE_[A-Z_]+)\"", src))
    assert used == documented


def test_fly_port_and_health() -> None:
    fly = tomllib.loads((ROOT / "fly.toml").read_text())
    assert int(fly["env"]["PORT"]) == fly["http_service"]["internal_port"]
    assert fly["http_service"]["checks"][0]["path"] == "/healthz"


def test_railway_and_render_health() -> None:
    assert (
        json.loads((ROOT / "railway.json").read_text())["deploy"]["healthcheckPath"] == "/healthz"
    )
    assert "healthCheckPath: /healthz" in (ROOT / "render.yaml").read_text()


def test_dockerfile_non_root_and_port() -> None:
    df = (ROOT / "Dockerfile").read_text()
    assert "USER datasage" in df and "${PORT:-8000}" in df and "HEALTHCHECK" in df


def test_vercel_bundles_package_and_entry_works(monkeypatch: object) -> None:
    cfg = json.loads((ROOT / "vercel.json").read_text())
    assert cfg["functions"]["api/index.py"]["includeFiles"] == "src/datasage/**"
    import importlib.util

    spec = importlib.util.spec_from_file_location("vercel_entry", ROOT / "api" / "index.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    c = TestClient(mod.app)
    assert c.get("/api/config").json()["access_mode"] == "public-demo"
    assert c.post("/api/ask", json={"question": "Revenue by region"}).status_code == 200
