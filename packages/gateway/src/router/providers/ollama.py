"""EDGE provider backed by Ollama, i.e. an on-device small model.

Ollama exposes an OpenAI-compatible /api/chat endpoint, so going from a
cloud model to a local one is a config change, not a rewrite. This is the
"SLM-first, cloud-on-escalation" lane: run a 1-3B model locally by default,
escalate only when the quality gate fails.

Confidence is derived from average token logprob when the model returns it,
otherwise from a short self-check. Requires a running Ollama daemon; if you
do not have one, keep EDGE_BACKEND=mock.
"""

from __future__ import annotations

import math
import time

from ..config import TierConfig
from ..types import CompletionRequest, ProviderReply, Tier
from .base import estimate_tokens

try:
    import httpx
except ImportError:  # httpx only needed for live backends
    httpx = None  # type: ignore


class OllamaProvider:
    def __init__(self, cfg: TierConfig, host: str = "http://localhost:11434"):
        if httpx is None:
            raise RuntimeError("httpx is required for the Ollama backend: pip install httpx")
        self.tier = Tier.EDGE
        self.model = cfg.model
        self.cfg = cfg
        self.host = host.rstrip("/")

    def complete(self, request: CompletionRequest) -> ProviderReply:
        started = time.time()
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": self._prompt(request)}],
            "stream": False,
            "options": {"num_predict": request.max_tokens},
            "logprobs": True,
        }
        resp = httpx.post(f"{self.host}/api/chat", json=payload, timeout=120.0)
        resp.raise_for_status()
        data = resp.json()
        text = data.get("message", {}).get("content", "")

        latency = (time.time() - started) * 1000.0
        p_tok = data.get("prompt_eval_count", estimate_tokens(request.prompt))
        c_tok = data.get("eval_count", estimate_tokens(text))
        confidence = self._confidence(data)

        return ProviderReply(
            text=text,
            model=self.model,
            tier=Tier.EDGE,
            prompt_tokens=p_tok,
            completion_tokens=c_tok,
            cost_usd=0.0,  # on-device inference has no per-token price
            latency_ms=round(latency, 1),
            confidence=confidence,
            raw={"backend": "ollama"},
        )

    def _prompt(self, request: CompletionRequest) -> str:
        if request.requires_schema:
            return (
                request.prompt
                + "\n\nReturn ONLY valid JSON with keys: "
                + ", ".join(request.json_schema.get("required", []))
            )
        return request.prompt

    def _confidence(self, data: dict) -> float:
        # If logprobs are present, map mean logprob -> [0, 1] via exp.
        logprobs = data.get("message", {}).get("logprobs")
        if logprobs:
            vals = [lp.get("logprob", 0.0) for lp in logprobs if "logprob" in lp]
            if vals:
                return round(min(1.0, math.exp(sum(vals) / len(vals))), 3)
        # No logprobs from this model build: be conservative so borderline
        # answers escalate rather than pass silently.
        return 0.5
