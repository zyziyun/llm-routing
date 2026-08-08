"""Runtime configuration. All knobs live here and can be overridden by env.

The defaults make it run fully offline with mock providers, no API
keys, no GPU. Point the *_BACKEND vars at real providers to go live.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _f(name: str, default: float) -> float:
    v = os.environ.get(name)
    return float(v) if v else default


@dataclass(frozen=True)
class TierConfig:
    model: str
    # USD per 1K tokens (prompt+completion combined for simplicity here).
    price_per_1k: float
    # Simulated latency for the mock provider, milliseconds.
    base_latency_ms: float
    # How good this tier is, 0..1, used only by the mock provider.
    competence: float


@dataclass(frozen=True)
class Config:
    # Which backend each tier uses: "mock" | "ollama" | "openai".
    edge_backend: str = os.environ.get("EDGE_BACKEND", "mock")
    cheap_backend: str = os.environ.get("CHEAP_BACKEND", "mock")
    frontier_backend: str = os.environ.get("FRONTIER_BACKEND", "mock")

    # Escalation gate. A reply is accepted only if schema validates (when a
    # schema is required) AND confidence >= this threshold. Lower it and more
    # work stays on the cheap tiers at some quality risk; raise it and more
    # requests escalate. This single dial is the cost/quality tradeoff.
    confidence_threshold: float = _f("CONFIDENCE_THRESHOLD", 0.62)

    # Optional second-stage LLM-as-judge on non-schema tasks. Off by default
    # so it needs no keys; when on, the FRONTIER provider scores quality.
    use_llm_judge: bool = os.environ.get("USE_LLM_JUDGE", "0") == "1"
    llm_judge_threshold: float = _f("LLM_JUDGE_THRESHOLD", 0.6)

    # Semantic cache: exact-hash by default; set to "embed" to use embeddings.
    cache_mode: str = os.environ.get("CACHE_MODE", "exact")
    cache_sim_threshold: float = _f("CACHE_SIM_THRESHOLD", 0.92)

    edge: TierConfig = TierConfig(
        model=os.environ.get("EDGE_MODEL", "llama3.2:3b"),
        price_per_1k=_f("EDGE_PRICE_PER_1K", 0.0),      # on-device, free
        base_latency_ms=_f("EDGE_LATENCY_MS", 90.0),
        competence=_f("EDGE_COMPETENCE", 0.74),
    )
    cheap: TierConfig = TierConfig(
        model=os.environ.get("CHEAP_MODEL", "gpt-4o-mini"),
        price_per_1k=_f("CHEAP_PRICE_PER_1K", 0.0006),
        base_latency_ms=_f("CHEAP_LATENCY_MS", 350.0),
        competence=_f("CHEAP_COMPETENCE", 0.85),
    )
    frontier: TierConfig = TierConfig(
        model=os.environ.get("FRONTIER_MODEL", "gpt-5"),
        price_per_1k=_f("FRONTIER_PRICE_PER_1K", 0.01),
        base_latency_ms=_f("FRONTIER_LATENCY_MS", 900.0),
        competence=_f("FRONTIER_COMPETENCE", 0.97),
    )


CONFIG = Config()
