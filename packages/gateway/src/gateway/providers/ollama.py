"""Async EDGE provider over Ollama (on-device small model). Streams and
completes against the local daemon's OpenAI-compatible surface."""

from __future__ import annotations

import math
import os
import time
from typing import AsyncIterator

import httpx

from router.config import TierConfig
from router.providers.base import estimate_tokens
from router.types import CompletionRequest, ProviderReply, Tier


class AsyncOllamaProvider:
    def __init__(self, cfg: TierConfig):
        self.tier = Tier.EDGE
        self.model = cfg.model
        self.cfg = cfg
        self.host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")

    async def complete(self, request: CompletionRequest) -> ProviderReply:
        started = time.time()
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{self.host}/api/chat",
                json={"model": self.model, "stream": False, "logprobs": True,
                      "messages": [{"role": "user", "content": request.prompt}],
                      "options": {"num_predict": request.max_tokens}},
            )
        resp.raise_for_status()
        data = resp.json()
        text = data.get("message", {}).get("content", "")
        conf = self._confidence(data)
        return ProviderReply(
            text=text, model=self.model, tier=Tier.EDGE,
            prompt_tokens=data.get("prompt_eval_count", estimate_tokens(request.prompt)),
            completion_tokens=data.get("eval_count", estimate_tokens(text)),
            cost_usd=0.0, latency_ms=round((time.time() - started) * 1000.0, 1),
            confidence=conf, raw={"backend": "ollama"},
        )

    async def stream(self, request: CompletionRequest) -> AsyncIterator[str]:
        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST", f"{self.host}/api/chat",
                json={"model": self.model, "stream": True,
                      "messages": [{"role": "user", "content": request.prompt}]},
            ) as resp:
                resp.raise_for_status()
                import json as _json
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        piece = _json.loads(line).get("message", {}).get("content", "")
                    except _json.JSONDecodeError:
                        continue
                    if piece:
                        yield piece

    @staticmethod
    def _confidence(data: dict) -> float:
        lps = data.get("message", {}).get("logprobs")
        if lps:
            vals = [lp.get("logprob", 0.0) for lp in lps if "logprob" in lp]
            if vals:
                return round(min(1.0, math.exp(sum(vals) / len(vals))), 3)
        return 0.5
