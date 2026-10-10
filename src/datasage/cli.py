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
from datasage.providers import UnknownQuestionError, provider_from_env
from datasage.sqlguard import SafeExecutor, UnsafeQueryError


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
    sub.add_parser("schema", help="show the dataset schema")
    args = parser.parse_args(argv)

    conn = build_sample_db()
    max_rows = int(os.environ.get("DATASAGE_MAX_ROWS", "500"))
    timeout_ms = int(os.environ.get("DATASAGE_QUERY_TIMEOUT_MS", "2000"))
    try:
        if args.command == "schema":
            for t in describe(conn):
                cols = ", ".join(f"{c.name} {c.type}" for c in t.columns)
                print(f"{t.name} ({t.row_count} rows): {cols}")
        elif args.command == "sql":
            tables = [t.name for t in describe(conn)]
            res = SafeExecutor(conn, tables, max_rows, timeout_ms).execute(args.query)
            print(_table(res.columns, res.rows))
        else:
            ans = Analyst(conn, provider_from_env(), max_rows, timeout_ms).ask(args.question)
            if args.json:
                payload = {
                    "question": ans.question,
                    "provider": ans.provider,
                    "sql": ans.result.sql,
                    "columns": ans.result.columns,
                    "rows": ans.result.rows,
                    "truncated": ans.result.truncated,
                    "summary": ans.summary,
                }
                print(json.dumps(payload, default=str))
            else:
                print(f"SQL: {ans.result.sql}\n")
                print(_table(ans.result.columns, ans.result.rows))
                print(f"\n{ans.summary}")
    except (UnsafeQueryError, UnknownQuestionError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
