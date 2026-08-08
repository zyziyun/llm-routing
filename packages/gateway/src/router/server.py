"""FastAPI gateway. Exposes the router over HTTP so it deploys like any
backend service.

    PYTHONPATH=src uvicorn router.server:app --reload

Endpoints:
    POST /route    body: {"prompt": "...", "json_schema": {...}?}
    GET  /healthz
    GET  /stats    process-lifetime routing counters
"""

from __future__ import annotations

from collections import Counter
from typing import Any

try:
    from fastapi import FastAPI
    from pydantic import BaseModel
except ImportError as e:  # pragma: no cover
    raise RuntimeError("pip install fastapi uvicorn pydantic to run the server") from e

from .router import Router
from .types import CompletionRequest

app = FastAPI(title="llm-router", version="0.1.0")
_router = Router()
_stats: Counter = Counter()


class RouteBody(BaseModel):
    prompt: str
    json_schema: dict[str, Any] | None = None
    max_tokens: int = 512


@app.post("/route")
def route(body: RouteBody) -> dict[str, Any]:
    result = _router.route(
        CompletionRequest(
            prompt=body.prompt, json_schema=body.json_schema, max_tokens=body.max_tokens
        )
    )
    _stats["requests"] += 1
    _stats[f"tier:{result.tier_answered.value}"] += 1
    if result.escalations:
        _stats["escalated"] += 1
    return {
        "answer": result.final.text,
        "model": result.final.model,
        "tier": result.tier_answered.value,
        "difficulty": result.difficulty.value,
        "cache_hit": result.cache_hit,
        "escalations": result.escalations,
        "cost_usd": result.total_cost_usd,
        "latency_ms": result.total_latency_ms,
        "trail": [
            {
                "tier": a.tier.value,
                "confidence": a.reply.confidence,
                "acceptable": a.verdict.acceptable,
                "reasons": a.verdict.reasons,
            }
            for a in result.attempts
        ],
    }


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/stats")
def stats() -> dict[str, int]:
    return dict(_stats)
