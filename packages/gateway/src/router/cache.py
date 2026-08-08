"""Response cache. Checked BEFORE routing, because a cache hit skips the
model call entirely, which is the cheapest possible outcome.

Two modes:
  - exact: hash of the normalized prompt.
  - embed: cosine similarity over an embedding function, so paraphrases
    hit too. Provide `embed`; without it, exact mode is used.
"""

from __future__ import annotations

import hashlib
from typing import Callable

from .config import CONFIG
from .types import ProviderReply


class ResponseCache:
    def __init__(self, embed: Callable[[str], list[float]] | None = None):
        self.embed = embed
        self._exact: dict[str, ProviderReply] = {}
        self._vectors: list[tuple[list[float], str]] = []

    @staticmethod
    def _key(prompt: str) -> str:
        norm = " ".join(prompt.lower().split())
        return hashlib.sha256(norm.encode("utf-8")).hexdigest()

    def get(self, prompt: str) -> ProviderReply | None:
        key = self._key(prompt)
        if key in self._exact:
            return self._exact[key]
        if CONFIG.cache_mode == "embed" and self.embed is not None and self._vectors:
            q = self._norm(self.embed(prompt))
            for vec, k in self._vectors:
                if self._cos(q, vec) >= CONFIG.cache_sim_threshold:
                    return self._exact.get(k)
        return None

    def put(self, prompt: str, reply: ProviderReply) -> None:
        key = self._key(prompt)
        self._exact[key] = reply
        if CONFIG.cache_mode == "embed" and self.embed is not None:
            self._vectors.append((self._norm(self.embed(prompt)), key))

    @staticmethod
    def _norm(v: list[float]) -> list[float]:
        mag = sum(x * x for x in v) ** 0.5 or 1.0
        return [x / mag for x in v]

    @staticmethod
    def _cos(a: list[float], b: list[float]) -> float:
        return sum(x * y for x, y in zip(a, b))
