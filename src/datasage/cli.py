"""Command-line interface: `datasage <command>`."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence

from datasage import __version__
from datasage.analyst import Analyst
from datasage.dataset import build_sample_db, describe
from datasage.evals import accuracy, run_eval
from datasage.providers import UnknownQuestionError, provider_from_env
from datasage.sqlguard import SafeExecutor, UnsafeQueryError
from datasage.upload import UploadError


def _table(columns: list[str], rows: list[tuple[object, ...]]) -> str:
    cells = [columns, *[[str(v) for v in r] for r in rows]]
    widths = [max(len(row[i]) for row in cells) for i in range(len(columns))]
    lines = [" | ".join(v.ljust(w) for v, w in zip(row, widths, strict=True)) for row in cells]
    lines.insert(1, "-+-".join("-" * w for w in widths))
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="datasage", description="AI data analyst agent")
    parser.add_argument("--version", action="version", version=f"datasage {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    ask = sub.add_parser("ask", help="ask a question about the sample dataset")
    ask.add_argument("question")
    ask.add_argument("--json", action="store_true")
    sql = sub.add_parser("sql", help="run raw SQL through the read-only guard")
    sql.add_argument("query")
    schema = sub.add_parser("schema", help="show the dataset schema")
    for p in (ask, sql, schema):
        p.add_argument(
            "--csv",
            action="append",
            default=[],
            metavar="NAME=FILE",
            help="load a CSV file as an extra read-only table (repeatable)",
        )
    ev = sub.add_parser("eval", help="run the execution-accuracy eval set")
    ev.add_argument("--json", action="store_true")
    ev.add_argument("--min-accuracy", type=float, default=1.0)
    args = parser.parse_args(argv)

    conn = build_sample_db()
    max_rows = int(os.environ.get("DATASAGE_MAX_ROWS", "500"))
    timeout_ms = int(os.environ.get("DATASAGE_QUERY_TIMEOUT_MS", "2000"))
    try:
        analyst = Analyst(conn, provider_from_env(), max_rows, timeout_ms)
        for spec in getattr(args, "csv", []):
            name, sep, path = spec.partition("=")
            if not sep or not path:
                raise ValueError("--csv expects NAME=FILE")
            with open(path, "rb") as fh:
                data = fh.read(2_000_001)
            up = analyst.add_csv(name, data)
            print(f"loaded {up.name} ({up.row_count} rows)", file=sys.stderr)
        if args.command == "eval":
            results = run_eval(analyst, conn)
            acc = accuracy(results)
            if args.json:
                print(json.dumps({"accuracy": acc, "results": [r.__dict__ for r in results]}))
            else:
                for r in results:
                    print(f"[{'PASS' if r.passed else 'FAIL'}] {r.question} ({r.detail})")
                print(f"\naccuracy: {acc:.1%} ({sum(r.passed for r in results)}/{len(results)})")
            return 0 if acc >= args.min_accuracy else 1
        if args.command == "schema":
            for t in describe(conn):
                cols = ", ".join(f"{c.name} {c.type}" for c in t.columns)
                print(f"{t.name} ({t.row_count} rows): {cols}")
        elif args.command == "sql":
            res = SafeExecutor(conn, analyst.tables, max_rows, timeout_ms).execute(args.query)
            print(_table(res.columns, res.rows))
        else:
            ans = analyst.ask(args.question)
            if args.json:
                print(json.dumps(ans.to_dict(), default=str))
            else:
                for a in ans.attempts:
                    if a.error:
                        print(f"retry: rejected SQL ({a.error})", file=sys.stderr)
                print(f"SQL: {ans.result.sql}\n")
                print(_table(ans.result.columns, ans.result.rows))
                print(f"\n{ans.summary}")
                for line in ans.insights:
                    print(f"- {line}")
                if ans.chart:
                    print(f"chart: {ans.chart.type} x={ans.chart.x} y={ans.chart.y}")
    except (UnsafeQueryError, UnknownQuestionError, UploadError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
