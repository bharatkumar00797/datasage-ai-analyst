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
