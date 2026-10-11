# Contributing to DataSage

Thanks for your interest in improving DataSage. Bug reports, new mock intents, eval cases,
documentation fixes and pull requests are all welcome.

## Development setup

Requirements: Python 3.11 to 3.13, `git`. Docker is optional (only for the container checks).

```bash
git clone https://github.com/bharatkumar00797/datasage-ai-analyst.git
cd datasage-ai-analyst
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

Everything runs offline with the default `mock` provider, so you don't need an API key. To
try a real model, copy `.env.example` to `.env` and set `DATASAGE_PROVIDER=openai` plus
`DATASAGE_LLM_BASE_URL` / `DATASAGE_LLM_API_KEY` / `DATASAGE_LLM_MODEL`. Never commit `.env`
or any key.

## Checks

CI runs these on Python 3.11, 3.12 and 3.13:

```bash
ruff check .
ruff format --check .
mypy
pytest
```

Optional end-to-end checks:

```bash
datasage eval --min-accuracy 1.0
datasage serve --dev                                 # http://127.0.0.1:8000
python scripts/smoke_test.py http://127.0.0.1:8000
docker compose up --build --wait
```

## Guidelines

- The mock provider stays the default: every feature must work without network or keys.
- Model output is untrusted. Never execute SQL without going through `sqlguard`.
- Insight numbers are always computed from the rows, never taken from model text.
- New code is fully typed (`mypy --strict`) and comes with tests. Guard changes need a test for
  the attack they stop *and* a test that legitimate queries still pass.
- A new mock intent comes with a case in `src/datasage/data/eval_set.json`.

## Commit style

[Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `docs:`,
`test:`, `ci:`, `chore:`. Keep commits small, use the imperative mood, and add user-visible
changes to `CHANGELOG.md` under **Unreleased**.

## Security issues

Please don't open public issues for vulnerabilities. See [SECURITY.md](SECURITY.md).
