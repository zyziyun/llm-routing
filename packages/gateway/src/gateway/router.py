"""Async production router. Same core as the synchronous router package (classify -> route ->
quality gate -> escalate), plus the reliability layer that a demo lacks:
per-provider circuit breakers, per-attempt timeouts, and escalation on
provider failure as well as on low quality.

Two escalation causes, kept distinct on purpose:
  - reliability: provider is open/timing out/erroring -> skip to next tier.
  - intelligence: provider answered but the quality gate rejected it.
"""

from __future__ import annotations

import asyncio
import logging

from router.classifier import HeuristicClassifier
from router.gate import QualityGate
from router.types import (
    LADDER,
    Attempt,
    CompletionRequest,
    Difficulty,
    ProviderReply,
    RouteResult,
    Tier,
)

from .breaker import CircuitBreaker
from .logging_setup import log
from .metrics import CACHE_HITS, COST, ESCALATIONS, LATENCY, REQUESTS
from .providers.registry import build_async_registry
from .settings import settings
from .store import Store

logger = logging.getLogger("gateway.router")

_START = {Difficulty.EASY: Tier.EDGE, Difficulty.MEDIUM: Tier.CHEAP, Difficulty.HARD: Tier.FRONTIER}


class AsyncRouter:
    def __init__(self, store: Store):
        self.store = store
        self.classifier = HeuristicClassifier()
        self.gate = QualityGate()
        self.providers = build_async_registry()
        self.breakers = {t: CircuitBreaker(store, t.value) for t in LADDER}

    async def _cache_get(self, prompt: str) -> ProviderReply | None:
        raw = await self.store.get(f"cache:{hash(prompt.strip().lower())}")
        if not raw:
            return None
        import json
        d = json.loads(raw)
        return ProviderReply(text=d["text"], model=d["model"], tier=Tier.CACHE,
                             prompt_tokens=0, completion_tokens=0, cost_usd=0.0,
                             latency_ms=1.0, confidence=d.get("confidence", 1.0))

    async def _cache_put(self, prompt: str, reply: ProviderReply) -> None:
        import json
        await self.store.set(
            f"cache:{hash(prompt.strip().lower())}",
            json.dumps({"text": reply.text, "model": reply.model, "confidence": reply.confidence}),
            ttl=settings.cache_ttl_s,
        )

    async def route(self, request: CompletionRequest) -> RouteResult:
        cached = await self._cache_get(request.prompt)
        if cached is not None:
            CACHE_HITS.inc()
            REQUESTS.labels(tier="cache", outcome="hit").inc()
            return RouteResult(request=request, final=cached, attempts=[],
                               difficulty=Difficulty.EASY, cache_hit=True,
                               total_cost_usd=0.0, total_latency_ms=1.0)

        difficulty = self.classifier.classify(request)
        request.metadata["difficulty"] = difficulty.value
        start_idx = LADDER.index(_START[difficulty])

        attempts: list[Attempt] = []
        total_cost = total_latency = 0.0
        final: ProviderReply | None = None

        for tier in LADDER[start_idx:]:
            breaker = self.breakers[tier]
            if not await breaker.allow():
                log(logger, logging.WARNING, "breaker_open_skip", tier=tier.value)
                continue  # reliability escalation
            try:
                reply = await asyncio.wait_for(
                    self.providers[tier].complete(request),
                    timeout=settings.per_attempt_timeout_s,
                )
                await breaker.on_success()
            except (asyncio.TimeoutError, Exception) as e:  # noqa: BLE001
                await breaker.on_failure()
                log(logger, logging.ERROR, "provider_failed", tier=tier.value, error=str(e))
                continue  # reliability escalation to next tier

            verdict = self.gate.assess(request, reply)
            attempts.append(Attempt(tier=tier, reply=reply, verdict=verdict))
            total_cost += reply.cost_usd
            total_latency += reply.latency_ms
            LATENCY.labels(tier=tier.value).observe(reply.latency_ms / 1000.0)
            COST.labels(tier=tier.value).inc(reply.cost_usd)
            final = reply
            if verdict.acceptable:
                await self._cache_put(request.prompt, reply)
                REQUESTS.labels(tier=tier.value, outcome="accepted").inc()
                break
            REQUESTS.labels(tier=tier.value, outcome="escalated").inc()

        if final is None:
            # Every tier was open or failed. Surface a clear error upstream.
            raise RuntimeError("all providers unavailable")

        if len(attempts) > 1:
            ESCALATIONS.inc()

        return RouteResult(request=request, final=final, attempts=attempts,
                           difficulty=difficulty, cache_hit=False,
                           total_cost_usd=round(total_cost, 6),
                           total_latency_ms=round(total_latency, 1))
