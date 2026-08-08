"""The router core. Ties the pieces together in the order the industry
converged on:

    cache  ->  classify  ->  route (SLM-first)  ->  quality gate  ->  escalate

Request flow:
  1. Cache lookup. Hit skips all model calls.
  2. Classify difficulty. Decides where on the ladder to START.
  3. Walk the ladder from the start tier upward. For each tier, call the
     provider, then run the quality gate. Accept and stop on the first
     reply that clears the gate; otherwise escalate to the next tier.
  4. If nothing clears the gate, return the top tier's reply (best effort)
     and flag it.

Cost and latency accrue across every attempt, so escalation is not free and
the eval will show it. That honesty is the point: the router is only a win
when it keeps most traffic on cheap tiers.
"""

from __future__ import annotations

from .classifier import Classifier, HeuristicClassifier
from .config import CONFIG
from .gate import QualityGate, make_llm_judge
from .cache import ResponseCache
from .providers.registry import build_registry
from .types import (
    LADDER,
    Attempt,
    CompletionRequest,
    Difficulty,
    ProviderReply,
    RouteResult,
    Tier,
)

# Which tier the ladder starts at, per difficulty. Easy starts on-device;
# hard skips straight to frontier and does not waste calls on weak tiers.
_START = {
    Difficulty.EASY: Tier.EDGE,
    Difficulty.MEDIUM: Tier.CHEAP,
    Difficulty.HARD: Tier.FRONTIER,
}


class Router:
    def __init__(
        self,
        classifier: Classifier | None = None,
        providers: dict[Tier, object] | None = None,
        cache: ResponseCache | None = None,
    ):
        self.classifier = classifier or HeuristicClassifier()
        self.providers = providers or build_registry()
        self.cache = cache or ResponseCache()
        judge = make_llm_judge(self.providers[Tier.FRONTIER]) if CONFIG.use_llm_judge else None
        self.gate = QualityGate(llm_judge=judge)

    def route(self, request: CompletionRequest) -> RouteResult:
        # 1. Cache first.
        cached = self.cache.get(request.prompt)
        if cached is not None:
            served = ProviderReply(**{**cached.__dict__, "tier": Tier.CACHE,
                                      "cost_usd": 0.0, "latency_ms": 1.0})
            return RouteResult(
                request=request, final=served, attempts=[],
                difficulty=Difficulty(request.metadata.get("difficulty", Difficulty.MEDIUM)),
                cache_hit=True, total_cost_usd=0.0, total_latency_ms=1.0,
            )

        # 2. Classify and record it so mock providers and logs can see it.
        difficulty = self.classifier.classify(request)
        request.metadata["difficulty"] = difficulty.value

        # 3. Walk the ladder from the start tier upward.
        start_idx = LADDER.index(_START[difficulty])
        attempts: list[Attempt] = []
        total_cost = 0.0
        total_latency = 0.0
        final: ProviderReply | None = None

        for tier in LADDER[start_idx:]:
            reply = self.providers[tier].complete(request)
            verdict = self.gate.assess(request, reply)
            attempts.append(Attempt(tier=tier, reply=reply, verdict=verdict))
            total_cost += reply.cost_usd
            total_latency += reply.latency_ms
            final = reply
            if verdict.acceptable:
                break

        assert final is not None
        # 4. Cache only answers that passed the gate.
        if attempts and attempts[-1].verdict.acceptable:
            self.cache.put(request.prompt, final)

        return RouteResult(
            request=request, final=final, attempts=attempts, difficulty=difficulty,
            cache_hit=False, total_cost_usd=round(total_cost, 6),
            total_latency_ms=round(total_latency, 1),
        )
