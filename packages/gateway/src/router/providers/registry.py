"""Builds the tier -> provider mapping from config. Swapping a tier's
backend (mock / ollama / openai) never touches the router core."""

from __future__ import annotations

from ..config import CONFIG, TierConfig
from ..types import Tier
from .base import Provider
from .mock import MockProvider


def _build(tier: Tier, backend: str, cfg: TierConfig) -> Provider:
    if backend == "mock":
        return MockProvider(tier, cfg)
    if backend == "ollama":
        from .ollama import OllamaProvider

        return OllamaProvider(cfg)
    if backend == "openai":
        from .openai_like import OpenAILikeProvider

        return OpenAILikeProvider(tier, cfg)
    raise ValueError(f"unknown backend {backend!r} for tier {tier.value}")


def build_registry() -> dict[Tier, Provider]:
    return {
        Tier.EDGE: _build(Tier.EDGE, CONFIG.edge_backend, CONFIG.edge),
        Tier.CHEAP: _build(Tier.CHEAP, CONFIG.cheap_backend, CONFIG.cheap),
        Tier.FRONTIER: _build(Tier.FRONTIER, CONFIG.frontier_backend, CONFIG.frontier),
    }
