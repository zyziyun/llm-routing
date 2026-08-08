from __future__ import annotations

from router.config import CONFIG, TierConfig
from router.types import Tier

from ..settings import settings
from .base import AsyncProvider
from .mock import AsyncMockProvider


def _build(tier: Tier, backend: str, cfg: TierConfig) -> AsyncProvider:
    if backend == "mock":
        return AsyncMockProvider(tier, cfg)
    if backend == "ollama":
        from .ollama import AsyncOllamaProvider

        return AsyncOllamaProvider(cfg)
    if backend == "openai":
        from .openai_like import AsyncOpenAIProvider

        return AsyncOpenAIProvider(tier, cfg)
    raise ValueError(f"unknown backend {backend!r}")


def build_async_registry() -> dict[Tier, AsyncProvider]:
    return {
        Tier.EDGE: _build(Tier.EDGE, settings.edge_backend, CONFIG.edge),
        Tier.CHEAP: _build(Tier.CHEAP, settings.cheap_backend, CONFIG.cheap),
        Tier.FRONTIER: _build(Tier.FRONTIER, settings.frontier_backend, CONFIG.frontier),
    }
