"""Serverless entrypoint (Vercel): exposes the DataSage FastAPI app as ``app``.

Every endpoint is a short synchronous request, so the service runs unchanged on serverless
hosts. Unless API keys are configured the deployment is a public demo: the sample dataset with
the offline mock provider. Uploaded CSV tables live in memory per function instance, so on
serverless they may disappear between requests; use a container host for persistent sessions.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if SRC.is_dir() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from datasage.api import create_app  # noqa: E402  (path setup must run first)

app = create_app()
