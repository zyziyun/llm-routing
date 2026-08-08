"""CHEAP / FRONTIER provider backed by any OpenAI-compatible Chat API.

Works with OpenAI directly, and with anything that speaks the same schema
(OpenRouter, Together, vLLM, LiteLLM proxy) by pointing OPENAI_BASE_URL at
it. Confidence is a self-reported 0..1 the model is asked to emit, which is
a pragmatic stand-in when logprobs are unavailable on hosted endpoints.
"""

from __future__ import annotations

import json
import os
import time

from ..config import TierConfig
from ..types import CompletionRequest, ProviderReply, Tier
from .base import estimate_tokens

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore


class OpenAILikeProvider:
    def __init__(self, tier: Tier, cfg: TierConfig):
        if httpx is None:
            raise RuntimeError("httpx is required for the OpenAI backend: pip install httpx")
        self.tier = tier
        self.model = cfg.model
        self.cfg = cfg
        self.base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        self.api_key = os.environ.get("OPENAI_API_KEY", "")

    def complete(self, request: CompletionRequest) -> ProviderReply:
        started = time.time()
        system = (
            "You are a precise assistant. After your answer, on the last line "
            "output CONFIDENCE=<0..1> with your own calibrated confidence."
        )
        if request.requires_schema:
            system += " Return the answer as valid JSON only, before the CONFIDENCE line."

        resp = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": request.prompt},
                ],
                "max_tokens": request.max_tokens,
                "temperature": 0.2,
            },
            timeout=120.0,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        text, confidence = self._split_confidence(content)
        usage = data.get("usage", {})
        p_tok = usage.get("prompt_tokens", estimate_tokens(request.prompt))
        c_tok = usage.get("completion_tokens", estimate_tokens(text))
        cost = (p_tok + c_tok) / 1000.0 * self.cfg.price_per_1k

        return ProviderReply(
            text=text,
            model=self.model,
            tier=self.tier,
            prompt_tokens=p_tok,
            completion_tokens=c_tok,
            cost_usd=round(cost, 6),
            latency_ms=round((time.time() - started) * 1000.0, 1),
            confidence=confidence,
            raw={"backend": "openai_like"},
        )

    @staticmethod
    def _split_confidence(content: str) -> tuple[str, float]:
        conf = 0.7
        lines = content.strip().splitlines()
        if lines and lines[-1].upper().startswith("CONFIDENCE="):
            try:
                conf = float(lines[-1].split("=", 1)[1].strip())
            except ValueError:
                pass
            content = "\n".join(lines[:-1]).strip()
        return content, max(0.0, min(1.0, conf))
