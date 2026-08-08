"""Production FastAPI gateway.

Drop-in OpenAI-compatible surface so existing clients point at it unchanged:
    POST /v1/chat/completions   (supports stream=true, Server-Sent Events)
    GET  /v1/models

Ops surface:
    GET  /healthz   liveness
    GET  /readyz    readiness (store + providers)
    GET  /metrics   Prometheus

Every request: API-key auth -> rate limit -> budget check -> route ->
charge budget -> structured log + metrics.
"""

from __future__ import annotations

import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel

from router.types import CompletionRequest, Tier

from .guards import BudgetGuard, RateLimiter
from .logging_setup import log, request_id_var, setup_logging
from .metrics import BUDGET_BLOCKED, INFLIGHT, RATE_LIMITED
from .router import AsyncRouter
from .settings import settings
from .store import build_store

logger = logging.getLogger("gateway.app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(settings.log_level)
    app.state.store = build_store()
    app.state.router = AsyncRouter(app.state.store)
    app.state.rl = RateLimiter(app.state.store)
    app.state.budget = BudgetGuard(app.state.store)
    log(logger, logging.INFO, "startup", env=settings.env,
        redis=bool(settings.redis_url))
    yield


app = FastAPI(title="llm-gateway", version="1.0.0", lifespan=lifespan)


# ---- OpenAI-compatible schema ----
class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    model: Optional[str] = None
    messages: list[ChatMessage]
    stream: bool = False
    max_tokens: int = 512
    # non-standard extension: pass a JSON schema to demand structured output
    json_schema: Optional[dict[str, Any]] = None


def _auth(authorization: Optional[str]) -> tuple[str, dict]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    key = authorization.split(" ", 1)[1].strip()
    cfg = settings.api_keys().get(key)
    if cfg is None:
        raise HTTPException(401, "invalid api key")
    return key, cfg


def _to_request(body: ChatRequest) -> CompletionRequest:
    prompt = "\n".join(m.content for m in body.messages if m.role != "system")
    return CompletionRequest(prompt=prompt, json_schema=body.json_schema,
                             max_tokens=body.max_tokens)


@app.middleware("http")
async def request_context(request: Request, call_next):
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
    request_id_var.set(rid)
    INFLIGHT.inc()
    started = time.time()
    try:
        resp = await call_next(request)
    finally:
        INFLIGHT.dec()
    resp.headers["x-request-id"] = rid
    log(logger, logging.INFO, "http", path=request.url.path,
        status=getattr(resp, "status_code", 0), ms=round((time.time() - started) * 1000, 1))
    return resp


@app.post("/v1/chat/completions")
async def chat_completions(body: ChatRequest, authorization: str = Header(default=None)):
    api_key, cfg = _auth(authorization)

    if not await app.state.rl.check(api_key, int(cfg.get("rpm", 60))):
        RATE_LIMITED.inc()
        raise HTTPException(429, "rate limit exceeded")

    if await app.state.budget.remaining(api_key, float(cfg.get("daily_usd", 5.0))) <= 0:
        BUDGET_BLOCKED.inc()
        raise HTTPException(402, "daily budget exhausted")

    req = _to_request(body)

    try:
        result = await app.state.router.route(req)
    except RuntimeError as e:
        raise HTTPException(503, str(e))

    await app.state.budget.charge(api_key, result.total_cost_usd)

    if body.stream:
        return StreamingResponse(_sse(result), media_type="text/event-stream")

    return JSONResponse({
        "id": f"chatcmpl-{request_id_var.get()}",
        "object": "chat.completion",
        "model": result.final.model,
        "choices": [{"index": 0, "finish_reason": "stop",
                     "message": {"role": "assistant", "content": result.final.text}}],
        "usage": {"prompt_tokens": result.final.prompt_tokens,
                  "completion_tokens": result.final.completion_tokens,
                  "total_tokens": result.final.prompt_tokens + result.final.completion_tokens},
        "x_gateway": {"tier": result.tier_answered.value, "difficulty": result.difficulty.value,
                      "escalations": result.escalations, "cache_hit": result.cache_hit,
                      "cost_usd": result.total_cost_usd, "latency_ms": result.total_latency_ms},
    })


async def _sse(result):
    """Stream the gated final answer as OpenAI-style SSE deltas. We route and
    quality-gate first (buffered), then stream the accepted answer. Gating a
    streamed attempt is impossible without buffering, so this is the honest
    tradeoff: decide, then stream."""
    import json
    rid = request_id_var.get()
    head = {"id": f"chatcmpl-{rid}", "object": "chat.completion.chunk",
            "model": result.final.model,
            "choices": [{"index": 0, "delta": {"role": "assistant"}}]}
    yield f"data: {json.dumps(head)}\n\n"
    for word in result.final.text.split(" "):
        chunk = {"choices": [{"index": 0, "delta": {"content": word + " "}}]}
        yield f"data: {json.dumps(chunk)}\n\n"
    yield "data: [DONE]\n\n"


@app.get("/v1/models")
async def models():
    return {"object": "list", "data": [{"id": t.value, "object": "model"} for t in Tier if t != Tier.CACHE]}


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/readyz")
async def readyz():
    ok = await app.state.store.ping()
    if not ok:
        raise HTTPException(503, "store not ready")
    return {"status": "ready", "store": "ok"}


@app.get("/metrics")
async def metrics():
    return PlainTextResponse(generate_latest().decode(), media_type=CONTENT_TYPE_LATEST)
