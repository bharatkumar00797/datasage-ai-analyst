# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.0.0] - 2026-10-11

### Added
- Guarded text-to-SQL pipeline: lexical read-only validator plus SQLite authorizer with table
  allowlist, `query_only` connection, row cap with truncated flag and query timeout.
- Deterministic retail sample dataset (customers, products, orders, order_items).
- Providers: offline deterministic mock (15 intents + uploaded-table questions) and
  OpenAI-compatible client (OpenAI, Groq, Ollama).
- Self-correcting retry: guard errors are fed back to the model (up to 2 retries).
- Deterministic insight narration and chart specs (line, bar, metric, table).
- CSV upload as validated, size-capped, read-only tables.
- Execution-accuracy eval set (15 cases) and `datasage eval`.
- CLI: `ask`, `sql`, `schema`, `eval`, `serve`, `--csv NAME=FILE`.
- FastAPI service with per-caller workspaces, API-key / dev / public-demo access modes,
  sliding-window rate limits, body cap, strict CSP and security headers.
- Static dashboard: questions, SQL view, SVG chart, insights, results, raw SQL, upload,
  schema and eval.
- Multi-stage non-root Dockerfile, hardened docker-compose, Render, Fly.io, Railway and Vercel
  configs, stdlib smoke test and a Docker smoke job in CI.

[Unreleased]: https://github.com/bharatkumar00797/datasage-ai-analyst/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/bharatkumar00797/datasage-ai-analyst/releases/tag/v1.0.0
