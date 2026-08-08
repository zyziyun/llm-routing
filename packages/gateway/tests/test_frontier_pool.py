"""FrontierPool: the router escalates to the frontier once and the pool commits
to a single best-value cloud, never walking several. Offline, mock members.
Run: PYTHONPATH=src pytest -q"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from router.config import CloudTier, TierConfig  # noqa: E402
from router.providers.base import Provider  # noqa: E402
from router.providers.frontier_pool import FrontierPool  # noqa: E402
from router.providers.mock import MockProvider  # noqa: E402
from router.router import Router  # noqa: E402
from router.types import CompletionRequest, Tier  # noqa: E402


class _Counting:
    """Wraps a provider to count how many times it was actually called."""

    def __init__(self, inner: Provider):
        self.inner = inner
        self.model = inner.model
        self.tier = inner.tier
        self.calls = 0

    def complete(self, request):
        self.calls += 1
        return self.inner.complete(request)


def _member(name, price, competence):
    ct = CloudTier(name=name, backend="mock", model=f"{name}-model",
                   price_per_1k=price, base_latency_ms=500.0, competence=competence)
    prov = _Counting(MockProvider(Tier.FRONTIER, ct.as_tier_config()))
    return ct, prov


def test_best_value_selects_one_cloud_and_calls_only_it():
    # cheap+strong deepseek should win on quality-per-dollar over a dear sonnet
    # and a dear-and-weaker gpt5; and only the winner is called (no cascade).
    ds = _member("deepseek", price=0.0007, competence=0.90)
    sonnet = _member("sonnet", price=0.003, competence=0.85)
    gpt5 = _member("gpt5", price=0.010, competence=0.80)
    pool = FrontierPool([ds, sonnet, gpt5], policy="best_value")

    reply = pool.complete(CompletionRequest(prompt="hard reasoning task",
                                            metadata={"difficulty": "hard"}))
    assert reply.raw["frontier_cloud"] == "deepseek"
    assert reply.tier == Tier.FRONTIER
    assert ds[1].calls == 1
    assert sonnet[1].calls == 0 and gpt5[1].calls == 0  # never walks the others


def test_cheapest_policy_picks_lowest_price():
    a = _member("a", price=0.005, competence=0.99)
    b = _member("b", price=0.001, competence=0.70)
    pool = FrontierPool([a, b], policy="cheapest")
    reply = pool.complete(CompletionRequest(prompt="x", metadata={"difficulty": "hard"}))
    assert reply.raw["frontier_cloud"] == "b"
    assert b[1].calls == 1 and a[1].calls == 0


def test_router_escalates_to_pool_without_cascading_clouds():
    ds = _member("deepseek", price=0.0007, competence=0.92)
    sonnet = _member("sonnet", price=0.003, competence=0.85)
    pool = FrontierPool([ds, sonnet], policy="best_value")
    providers = {
        Tier.EDGE: MockProvider(Tier.EDGE, TierConfig("edge", 0.0, 90.0, 0.74)),
        Tier.CHEAP: MockProvider(Tier.CHEAP, TierConfig("cheap", 0.0006, 350.0, 0.85)),
        Tier.FRONTIER: pool,
    }
    r = Router(providers=providers)
    res = r.route(CompletionRequest(
        prompt="Design a distributed rate limiter and reason about the consistency trade-offs."))
    assert res.tier_answered == Tier.FRONTIER
    assert res.final.raw["frontier_cloud"] == "deepseek"
    # frontier appears at most once in the attempt trail -- routed to, not walked.
    assert [a.tier for a in res.attempts].count(Tier.FRONTIER) == 1
    assert ds[1].calls == 1 and sonnet[1].calls == 0
