"""Async mock provider. Reuses the router core's deterministic difficulty model so
the gateway behaves identically offline, but with async I/O and simulated
latency via asyncio.sleep, so concurrency is real."""

from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator

from router.config import CONFIG, TierConfig
from router.providers.base import estimate_tokens
from router.providers.mock import _DIFF_PENALTY, _SCHEMA_PENALTY, _unit_hash
from router.types import CompletionRequest, Difficulty, ProviderReply, Tier


class AsyncMockProvider:
    def __init__(self, tier: Tier, cfg: TierConfig):
        self.tier = tier
        self.model = cfg.model
        self.cfg = cfg

    def _decide(self, request: CompletionRequest):
        difficulty = Difficulty(request.metadata.get("difficulty", Difficulty.MEDIUM))
        penalty = _DIFF_PENALTY[difficulty]
        jitter = (_unit_hash(request.prompt + self.tier.value) - 0.5) * 0.08
        constrained = request.requires_schema and request.metadata.get(
            "constrained", CONFIG.constrained_decoding
        )
        schema_hit = 0.0 if constrained else (
            _SCHEMA_PENALTY if (request.requires_schema and self.tier != Tier.FRONTIER) else 0.0
        )
        effective = max(0.0, min(1.0, self.cfg.competence - penalty - schema_hit + jitter))
        return difficulty, round(effective, 3), (effective >= 0.6) or bool(constrained)

    def _text(self, request: CompletionRequest, succeeds: bool) -> str:
        if request.requires_schema:
            required = (request.json_schema or {}).get("required", [])
            types = (request.json_schema or {}).get("types", {})
            if not succeeds:
                return "Sure! Here is the JSON:\n{ " + ", ".join(required[:1]) + ": }"
            obj = {k: {"string": "value", "number": 1, "boolean": True,
                       "array": [], "object": {}}.get(types.get(k, "string"), "value")
                   for k in required}
            return json.dumps(obj)
        tag = self.tier.value
        return (f"[{tag}] {request.prompt.strip()[:80]} -> answer" if succeeds
                else f"[{tag}] partial/low-confidence answer")

    async def complete(self, request: CompletionRequest) -> ProviderReply:
        _, confidence, succeeds = self._decide(request)
        text = self._text(request, succeeds)
        p_tok, c_tok = estimate_tokens(request.prompt), estimate_tokens(text)
        latency_ms = self.cfg.base_latency_ms + c_tok * 0.6
        await asyncio.sleep(latency_ms / 1000.0)  # real await, real concurrency
        cost = (p_tok + c_tok) / 1000.0 * self.cfg.price_per_1k
        return ProviderReply(
            text=text, model=self.model, tier=self.tier,
            prompt_tokens=p_tok, completion_tokens=c_tok,
            cost_usd=round(cost, 6), latency_ms=round(latency_ms, 1),
            confidence=confidence, raw={"mock": True},
        )

    async def stream(self, request: CompletionRequest) -> AsyncIterator[str]:
        reply = await self.complete(request)
        for word in reply.text.split(" "):
            await asyncio.sleep(0.005)
            yield word + " "
