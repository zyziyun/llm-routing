"""Core data types for the router.

Kept as plain dataclasses so the routing core has no web-framework or
pydantic dependency. The FastAPI layer maps these to/from request models.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Tier(str, Enum):
    """A capability/cost tier. The ladder is EDGE -> CHEAP -> FRONTIER.

    EDGE is an on-device small model (Ollama / Apple Foundation Models).
    CHEAP is a small hosted model. FRONTIER is a top hosted model.
    CACHE is a synthetic tier used when a cached answer is served.
    """

    EDGE = "edge"
    CHEAP = "cheap"
    FRONTIER = "frontier"
    CACHE = "cache"


# The escalation ladder, cheapest first. CACHE is not part of it.
LADDER: list[Tier] = [Tier.EDGE, Tier.CHEAP, Tier.FRONTIER]


class Difficulty(str, Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


@dataclass
class CompletionRequest:
    """One inbound request to the gateway."""

    prompt: str
    # If set, the reply must be JSON conforming to this minimal schema:
    #   {"required": ["field", ...], "types": {"field": "string|number|array|object|boolean"}}
    json_schema: dict[str, Any] | None = None
    max_tokens: int = 512
    # Populated by the classifier and read by mock providers. Real
    # providers ignore it. Never trust it as ground truth.
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def requires_schema(self) -> bool:
        return self.json_schema is not None


@dataclass
class ProviderReply:
    text: str
    model: str
    tier: Tier
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    latency_ms: float
    # Self-reported confidence in [0, 1]. Real providers can derive this
    # from logprobs or a self-check pass; mocks compute it deterministically.
    confidence: float
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class GateVerdict:
    acceptable: bool
    score: float          # 0..1 overall quality score used for logging
    schema_ok: bool
    confidence: float
    reasons: list[str] = field(default_factory=list)


@dataclass
class Attempt:
    tier: Tier
    reply: ProviderReply
    verdict: GateVerdict


@dataclass
class RouteResult:
    request: CompletionRequest
    final: ProviderReply
    attempts: list[Attempt]
    difficulty: Difficulty
    cache_hit: bool
    total_cost_usd: float
    total_latency_ms: float

    @property
    def tier_answered(self) -> Tier:
        return self.final.tier

    @property
    def escalations(self) -> int:
        # Number of times we had to move up a tier before accepting.
        return max(0, len([a for a in self.attempts]) - 1)
