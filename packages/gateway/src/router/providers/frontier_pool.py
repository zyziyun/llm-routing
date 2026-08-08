"""Frontier tier as a pool of clouds, with single-select escalation.

The router escalates to the frontier tier ONCE; this pool decides which cloud
actually answers -- the single best value (quality per dollar) or the cheapest,
per policy -- and never walks several clouds in series.

This is the shipped form of docs/EXPERIMENTS.md experiment 4: escalating through
every cloud in turn double-pays on each miss and costs more than just calling one
cloud, so the router *routes to* the frontier, it does not *walk* it. Selection
is by measured effective cost, not static list price, because a reasoning model's
real token bill is only visible after the fact.

Provider-agnostic by construction: every member is built through the same
registry, so a member can be a hosted API, a self-hosted vLLM endpoint, or a
mock. Adding a cloud is a config entry, not a code change.
"""

from __future__ import annotations

from ..config import CloudTier
from ..types import CompletionRequest, ProviderReply, Tier
from .base import Provider


class FrontierPool:
    tier = Tier.FRONTIER

    def __init__(self, members: list[tuple[CloudTier, Provider]], policy: str = "best_value"):
        if not members:
            raise ValueError("FrontierPool needs at least one member")
        if policy not in ("best_value", "cheapest"):
            raise ValueError(f"unknown frontier_select policy {policy!r}")
        self.members = members
        self.policy = policy
        self.model = self._select()[0].model

    def _select(self) -> tuple[CloudTier, Provider]:
        if self.policy == "cheapest":
            return min(self.members, key=lambda m: m[0].price_per_1k)
        # best_value: highest measured quality per dollar. Guard a free/local
        # member (price 0) so it doesn't divide by zero and always win blindly.
        return max(self.members, key=lambda m: m[0].competence / (m[0].price_per_1k + 1e-9))

    def complete(self, request: CompletionRequest) -> ProviderReply:
        cfg, provider = self._select()
        reply = provider.complete(request)
        reply.tier = Tier.FRONTIER
        reply.raw = {**(reply.raw or {}), "frontier_cloud": cfg.name,
                     "frontier_select": self.policy}
        return reply
