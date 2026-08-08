"""Async CHEAP/FRONTIER provider over any OpenAI-compatible Chat API, with
real streaming. Uses a shared httpx.AsyncClient with connection pooling.
Works with OpenAI, OpenRouter, vLLM, or a LiteLLM proxy via OPENAI_BASE_URL.
"""

from __future__ import annotations

import json
import os
import time
from typing import AsyncIterator

import httpx

from router.config import CONFIG, TierConfig
from router.providers.base import estimate_tokens
from router.types import CompletionRequest, ProviderReply, Tier
from router.providers.openai_like import _json_schema

_client: httpx.AsyncClient | None = None


def _shared_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(120.0),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )
    return _client


class AsyncOpenAIProvider:
    def __init__(self, tier: Tier, cfg: TierConfig):
        self.tier = tier
        self.model = cfg.model
        self.cfg = cfg
        self.base_url = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
        self.api_key = os.environ.get("OPENAI_API_KEY", "")

    def _messages(self, request: CompletionRequest) -> list[dict]:
        system = ("You are precise. End with a line CONFIDENCE=<0..1>. "
                  + ("Return valid JSON only before that line." if request.requires_schema else ""))
        return [{"role": "system", "content": system},
                {"role": "user", "content": request.prompt}]

    async def complete(self, request: CompletionRequest) -> ProviderReply:
        started = time.time()
        body = {"model": self.model, "messages": self._messages(request),
                "max_tokens": request.max_tokens, "temperature": 0.2}
        if request.requires_schema and CONFIG.constrained_decoding:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "reply", "schema": _json_schema(request.json_schema)},
            }
        resp = await _shared_client().post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=body,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        text, confidence = self._split_conf(content)
        usage = data.get("usage", {})
        p_tok = usage.get("prompt_tokens", estimate_tokens(request.prompt))
        c_tok = usage.get("completion_tokens", estimate_tokens(text))
        return ProviderReply(
            text=text, model=self.model, tier=self.tier,
            prompt_tokens=p_tok, completion_tokens=c_tok,
            cost_usd=round((p_tok + c_tok) / 1000.0 * self.cfg.price_per_1k, 6),
            latency_ms=round((time.time() - started) * 1000.0, 1),
            confidence=confidence, raw={"backend": "openai"},
        )

    async def stream(self, request: CompletionRequest) -> AsyncIterator[str]:
        async with _shared_client().stream(
            "POST", f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "messages": self._messages(request),
                  "max_tokens": request.max_tokens, "temperature": 0.2, "stream": True},
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                chunk = line[6:]
                if chunk.strip() == "[DONE]":
                    break
                try:
                    delta = json.loads(chunk)["choices"][0]["delta"].get("content", "")
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue
                if delta:
                    yield delta

    @staticmethod
    def _split_conf(content: str) -> tuple[str, float]:
        conf = 0.7
        lines = content.strip().splitlines()
        if lines and lines[-1].upper().startswith("CONFIDENCE="):
            try:
                conf = float(lines[-1].split("=", 1)[1].strip())
            except ValueError:
                pass
            content = "\n".join(lines[:-1]).strip()
        return content, max(0.0, min(1.0, conf))
