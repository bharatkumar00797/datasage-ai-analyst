"""FastAPI application: ask, raw SQL, schema, CSV datasets, evals and the static dashboard."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi import status as http
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from datasage import __version__
from datasage.analyst import Analyst
from datasage.api.middleware import BodyLimitMiddleware, SecurityHeadersMiddleware
from datasage.api.schemas import (
    AnswerOut,
    AskIn,
    ConfigOut,
    DatasetIn,
    DatasetOut,
    EvalOut,
    ExamplesOut,
    HealthOut,
    SchemaOut,
    SqlIn,
    SqlOut,
)
from datasage.api.security import ApiKeyAuth, RateLimiter
from datasage.api.settings import ApiSettings
from datasage.api.workspaces import WorkspaceStore
from datasage.dataset import build_sample_db, describe
from datasage.evals import accuracy, run_eval
from datasage.insights import chart_spec, narrate
from datasage.providers import MockProvider, Provider, UnknownQuestionError, provider_from_env
from datasage.sqlguard import QueryTimeoutError, UnsafeQueryError
from datasage.upload import MAX_BYTES, UploadError

STATIC_DIR = Path(__file__).parent / "static"
# A 1 MB CSV is sent JSON-encoded, so leave headroom for escaping.
MAX_BODY_BYTES = 1_200_000
EXAMPLES = [
    "What is the total revenue?",
    "Revenue by category",
    "Show the monthly revenue trend",
    "Top 5 customers by revenue",
    "Which region generates the most revenue?",
    "Revenue by channel",
    "Best selling products",
    "New customer signups by month",
    "Orders by weekday",
    "Average items per order",
]


@dataclass(frozen=True)
class Caller:
    """``owner`` selects the private workspace and ``client`` keys rate limits."""

    owner: str
    client: str
    trusted: bool


def client_ip(request: Request, trust_proxy: bool) -> str:
    if trust_proxy:
        # The right-most hop is appended by the trusted edge proxy; anything to its left is
        # client-supplied and can be forged.
        hops = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",")]
        hops = [h for h in hops if h]
        if hops:
            return hops[-1][:64]
    return request.client.host if request.client else "unknown"


def presented_key(request: Request) -> str | None:
    key = request.headers.get("x-api-key")
    if key and key.strip():
        return key.strip()
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() == "bearer" and token.strip():
        return token.strip()
    return None


def _retry_after(seconds: float) -> dict[str, str]:
    return {"Retry-After": str(max(1, math.ceil(seconds)))}


def _limit(limiter: RateLimiter, identity: str) -> None:
    retry = limiter.check(identity)
    if retry is not None:
        raise HTTPException(
            http.HTTP_429_TOO_MANY_REQUESTS, "Rate limit exceeded", headers=_retry_after(retry)
        )


@dataclass(frozen=True)
class AccessGuard:
    """Authenticates a request and applies the general per-caller rate limit."""

    settings: ApiSettings
    auth: ApiKeyAuth
    limiter: RateLimiter

    def identify(self, request: Request) -> Caller | None:
        if self.auth.enabled:
            fp = self.auth.verify(presented_key(request))
            return Caller(f"key:{fp}", f"key:{fp}", True) if fp else None
        ip = client_ip(request, self.settings.trust_proxy)
        if self.settings.dev_mode:
            return Caller("dev", f"ip:{ip}", True)
        anon = "anon:" + hashlib.sha256(ip.encode()).hexdigest()[:12]
        return Caller(anon, f"ip:{ip}", False)

    def __call__(self, request: Request) -> Caller:
        who = self.identify(request)
        if who is None:
            raise HTTPException(
                http.HTTP_401_UNAUTHORIZED,
                "Missing or invalid API key",
                headers={"WWW-Authenticate": "Bearer"},
            )
        _limit(self.limiter, who.client)
        return who


def get_caller(request: Request) -> Caller:
    access: AccessGuard = request.app.state.access
    return access(request)


CallerDep = Annotated[Caller, Depends(get_caller)]


def _rows(rows: list[tuple[Any, ...]]) -> list[list[Any]]:
    return [list(r) for r in rows]


def create_app(settings: ApiSettings | None = None, provider: Provider | None = None) -> FastAPI:
    settings = settings or ApiSettings.from_env()
    # Anonymous public-demo visitors never reach a paid model, whatever the env says.
    if settings.public_demo:
        provider = MockProvider()
    provider = provider or provider_from_env()
    store = WorkspaceStore(
        provider, settings.max_rows, settings.query_timeout_ms, settings.max_workspaces
    )
    ask_limiter = RateLimiter(settings.ask_limit_per_minute)
    upload_limiter = RateLimiter(settings.upload_limit_per_minute)

    app = FastAPI(
        title="DataSage",
        version=__version__,
        description="AI data analyst agent: plain-English questions to guarded read-only SQL.",
    )
    app.state.settings = settings
    app.state.store = store
    app.state.access = AccessGuard(
        settings, ApiKeyAuth(settings.api_keys), RateLimiter(settings.rate_limit_per_minute)
    )

    @app.get("/healthz", response_model=HealthOut, tags=["meta"])
    def healthz() -> HealthOut:
        return HealthOut(status="ok", version=__version__)

    @app.get("/api/config", response_model=ConfigOut, tags=["meta"])
    def config() -> ConfigOut:
        # Public on purpose: the dashboard needs it before the user has entered a key.
        # It never contains provider credentials or URLs.
        return ConfigOut(
            version=__version__,
            access_mode=settings.access_mode,
            auth_required=settings.auth_enabled,
            provider=provider.name,
            raw_sql_allowed=True,
            max_rows=settings.max_rows,
            query_timeout_ms=settings.query_timeout_ms,
            max_upload_bytes=MAX_BYTES,
            max_uploads=settings.max_uploads_per_workspace,
            rate_limit_per_minute=settings.rate_limit_per_minute,
            ask_limit_per_minute=settings.ask_limit_per_minute,
        )

    @app.get("/api/examples", response_model=ExamplesOut, tags=["analyst"])
    def examples(caller: CallerDep) -> ExamplesOut:
        return ExamplesOut(examples=EXAMPLES)

    @app.get("/api/schema", response_model=SchemaOut, tags=["analyst"])
    def schema(caller: CallerDep) -> SchemaOut:
        ws = store.get(caller.owner)
        with ws.lock:
            tables = describe(ws.analyst.conn)
        return SchemaOut.model_validate(
            {
                "tables": [
                    {
                        "name": t.name,
                        "row_count": t.row_count,
                        "columns": [{"name": c.name, "type": c.type} for c in t.columns],
                        "uploaded": t.name in ws.uploads,
                    }
                    for t in tables
                ]
            }
        )

    @app.post("/api/ask", response_model=AnswerOut, tags=["analyst"])
    def ask(body: AskIn, caller: CallerDep) -> dict[str, Any]:
        _limit(ask_limiter, caller.client)
        ws = store.get(caller.owner)
        try:
            with ws.lock:
                answer = ws.analyst.ask(body.question)
        except QueryTimeoutError as exc:
            raise HTTPException(408, str(exc)) from exc
        except UnsafeQueryError as exc:
            raise HTTPException(422, f"blocked: {exc}") from exc
        except UnknownQuestionError as exc:
            raise HTTPException(422, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except httpx.HTTPError as exc:  # provider transport failures
            raise HTTPException(http.HTTP_502_BAD_GATEWAY, "LLM provider error") from exc
        return answer.to_dict()

    @app.post("/api/sql", response_model=SqlOut, tags=["analyst"])
    def run_sql(body: SqlIn, caller: CallerDep) -> SqlOut:
        _limit(ask_limiter, caller.client)
        ws = store.get(caller.owner)
        try:
            with ws.lock:
                res = ws.analyst.executor.execute(body.sql)
        except QueryTimeoutError as exc:
            raise HTTPException(408, str(exc)) from exc
        except UnsafeQueryError as exc:
            raise HTTPException(422, f"blocked: {exc}") from exc
        chart = chart_spec(res, "Query result")
        return SqlOut.model_validate(
            {
                "sql": res.sql,
                "columns": res.columns,
                "rows": _rows(res.rows),
                "truncated": res.truncated,
                "elapsed_ms": res.elapsed_ms,
                "insights": narrate(res),
                "chart": chart.to_dict(),
            }
        )

    @app.post(
        "/api/datasets",
        response_model=DatasetOut,
        status_code=http.HTTP_201_CREATED,
        tags=["datasets"],
    )
    def upload(body: DatasetIn, caller: CallerDep) -> DatasetOut:
        _limit(upload_limiter, caller.client)
        ws = store.get(caller.owner)
        with ws.lock:
            if len(ws.uploads) >= settings.max_uploads_per_workspace:
                raise HTTPException(
                    http.HTTP_409_CONFLICT,
                    f"upload limit reached ({settings.max_uploads_per_workspace} tables); "
                    "reset the workspace first",
                )
            try:
                up = ws.analyst.add_csv(body.name, body.csv)
            except UploadError as exc:
                raise HTTPException(422, str(exc)) from exc
            ws.uploads.append(up.name)
        return DatasetOut.model_validate(
            {
                "name": up.name,
                "row_count": up.row_count,
                "columns": [{"name": n, "type": t} for n, t in up.columns],
            }
        )

    @app.delete("/api/datasets", status_code=http.HTTP_204_NO_CONTENT, tags=["datasets"])
    def reset(caller: CallerDep) -> None:
        store.reset(caller.owner)

    @app.post("/api/eval", response_model=EvalOut, tags=["analyst"])
    def evaluate(caller: CallerDep) -> EvalOut:
        _limit(ask_limiter, caller.client)
        conn = build_sample_db()  # a pristine copy, independent of the caller's uploads
        try:
            analyst = Analyst(conn, provider, settings.max_rows, settings.query_timeout_ms)
            results = run_eval(analyst, conn)
        finally:
            conn.close()
        return EvalOut.model_validate(
            {
                "provider": provider.name,
                "accuracy": accuracy(results),
                "passed": sum(r.passed for r in results),
                "total": len(results),
                "results": [r.__dict__ for r in results],
            }
        )

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    app.add_middleware(SecurityHeadersMiddleware)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(settings.cors_origins),
            allow_methods=["GET", "POST", "DELETE"],
            allow_headers=["Content-Type", "X-API-Key", "Authorization"],
        )
    app.add_middleware(BodyLimitMiddleware, max_bytes=MAX_BODY_BYTES)
    return app
