# DataSage - AI Data Analyst Agent

An AI data analyst agent: ask a business question in plain English and DataSage
turns it into **guarded, read-only SQL**, runs it against your dataset and explains the
result. It runs fully offline with a deterministic mock LLM provider by default; plug in
any OpenAI-compatible API (OpenAI, Groq, Ollama) when you want a real model.

> Work in progress - full documentation lands with v1.0.0.

```bash
pip install -e ".[dev]"
datasage --version
```

License: MIT

## What it does today

- **Guarded text-to-SQL** - model output is untrusted; a lexical validator plus the SQLite
  authorizer allow only `SELECT` on allowlisted tables, with a row cap and a timeout.
- **Self-correction** - if the guard rejects the generated SQL, the error is sent back to the
  model and it gets up to two more attempts (timeouts are never retried).
- **Insight narration** - leader / laggard, share of total, period-over-period change and peak,
  all computed from the returned rows (no model-generated numbers).
- **Chart specs** - `line` for time series, `bar` for categories, `metric` for single values.
- **CSV upload** - `--csv NAME=FILE` loads a CSV as a new read-only table (size, row and
  column caps, sanitised identifiers, parameterised inserts).
- **Eval set** - `datasage eval` checks execution accuracy against hand-written gold SQL.

```bash
datasage ask "monthly revenue trend"
datasage ask "how many rows in stores" --csv stores=stores.csv --json
datasage eval
```
