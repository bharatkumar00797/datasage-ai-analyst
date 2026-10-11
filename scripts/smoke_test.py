#!/usr/bin/env python3
"""End-to-end smoke test against a running server (stdlib only).

Usage: python3 scripts/smoke_test.py [BASE_URL] [--api-key KEY]

Checks health, the dashboard and its security headers, every example question, the read-only
guard on destructive SQL, a CSV upload queried in plain English, and the eval set. Exits
non-zero on the first failure.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any


class Client:
    def __init__(self, base: str, api_key: str | None) -> None:
        self.base = base.rstrip("/")
        self.api_key = api_key

    def request(self, method: str, path: str, body: Any = None) -> tuple[int, Any, Any]:
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if self.api_key:
            req.add_header("X-API-Key", self.api_key)
        try:
            with urllib.request.urlopen(req, timeout=30) as res:
                raw = res.read().decode()
                status, headers = res.status, res.headers
        except urllib.error.HTTPError as err:
            raw, status, headers = err.read().decode(), err.code, err.headers
        ctype = headers.get("content-type", "")
        return status, (json.loads(raw) if "json" in ctype and raw else raw), headers


def check(cond: bool, message: str) -> None:
    if not cond:
        print(f"FAIL {message}")
        sys.exit(1)
    print(f"PASS {message}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("base", nargs="?", default="http://127.0.0.1:8000")
    parser.add_argument("--api-key")
    args = parser.parse_args()
    c = Client(args.base, args.api_key)

    status, body, _ = c.request("GET", "/healthz")
    check(status == 200 and body["status"] == "ok", f"healthz ({body})")
    status, page, headers = c.request("GET", "/")
    csp = headers.get("content-security-policy", "")
    check(status == 200 and "DataSage" in page and "default-src 'self'" in csp, "dashboard + CSP")

    _, examples, _ = c.request("GET", "/api/examples")
    for q in examples["examples"]:
        status, ans, _ = c.request("POST", "/api/ask", {"question": q})
        check(status == 200 and ans["rows"] and ans["insights"], f"ask: {q}")

    for sql in ("DROP TABLE orders", "DELETE FROM customers", "SELECT * FROM sqlite_master"):
        status, out, _ = c.request("POST", "/api/sql", {"sql": sql})
        check(status == 422 and "blocked" in str(out), f"guard blocks: {sql}")

    c.request("DELETE", "/api/datasets")
    csv = "region,target\nNorth,100\nSouth,80\nEast,120\n"
    status, up, _ = c.request("POST", "/api/datasets", {"name": "targets", "csv": csv})
    check(status == 201 and up["row_count"] == 3, "CSV upload")
    status, ans, _ = c.request("POST", "/api/ask", {"question": "show targets"})
    check(status == 200 and len(ans["rows"]) == 3, "ask about the uploaded table")
    c.request("DELETE", "/api/datasets")

    status, ev, _ = c.request("POST", "/api/eval")
    check(
        status == 200 and ev["passed"] == ev["total"], f"eval {ev.get('passed')}/{ev.get('total')}"
    )
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
