"""Deterministic mock provider.

Lets everything run with no keys, no GPU, no network, while still
producing a realistic cost/quality/escalation story:

  - Easy tasks: even the EDGE tier answers confidently and validly.
  - Hard tasks: cheap tiers produce low confidence or invalid JSON, which
    trips the quality gate and forces escalation to FRONTIER.

Determinism comes from hashing the prompt, so the same request always
routes the same way. That makes eval runs reproducible.
"""

from __future__ import annotations

import hashlib
import json

from ..config import TierConfig
from ..types import CompletionRequest, Difficulty, ProviderReply, Tier
from .base import estimate_tokens

_DIFF_PENALTY = {Difficulty.EASY: 0.0, Difficulty.MEDIUM: 0.20, Difficulty.HARD: 0.25}
# Strict structured output is disproportionately hard for weaker models, so
# non-frontier tiers take an extra hit on schema tasks. This is what makes a
# cheap model botch strict JSON extraction and forces a quality escalation.
_SCHEMA_PENALTY = 0.15


def _unit_hash(text: str) -> float:
    """Stable pseudo-random number in [0, 1) from text."""
    h = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return int(h[:8], 16) / 0xFFFFFFFF


class MockProvider:
    def __init__(self, tier: Tier, cfg: TierConfig):
        self.tier = tier
        self.model = cfg.model
        self.cfg = cfg

    def complete(self, request: CompletionRequest) -> ProviderReply:
        difficulty = Difficulty(request.metadata.get("difficulty", Difficulty.MEDIUM))
        penalty = _DIFF_PENALTY[difficulty]

        # Effective competence for THIS request, jittered deterministically.
        jitter = (_unit_hash(request.prompt + self.tier.value) - 0.5) * 0.08
        schema_hit = _SCHEMA_PENALTY if (request.requires_schema and self.tier != Tier.FRONTIER) else 0.0
        effective = max(0.0, min(1.0, self.cfg.competence - penalty - schema_hit + jitter))
        # Confidence tracks effective competence with a little noise.
        confidence = round(max(0.0, min(1.0, effective)), 3)
        succeeds = effective >= 0.6

        if request.requires_schema:
            text = self._schema_answer(request, valid=succeeds)
        else:
            tag = self.tier.value
            text = (
                f"[{tag}] {request.prompt.strip()[:80]} -> answer"
                if succeeds
                else f"[{tag}] partial/low-confidence answer"
            )

        p_tok = estimate_tokens(request.prompt)
        c_tok = estimate_tokens(text)
        cost = (p_tok + c_tok) / 1000.0 * self.cfg.price_per_1k
        latency = self.cfg.base_latency_ms + c_tok * 0.6

        return ProviderReply(
            text=text,
            model=self.model,
            tier=self.tier,
            prompt_tokens=p_tok,
            completion_tokens=c_tok,
            cost_usd=round(cost, 6),
            latency_ms=round(latency, 1),
            confidence=confidence,
            raw={"mock": True, "difficulty": difficulty.value, "succeeds": succeeds},
        )

    def _schema_answer(self, request: CompletionRequest, valid: bool) -> str:
        required = (request.json_schema or {}).get("required", [])
        types = (request.json_schema or {}).get("types", {})
        if not valid:
            # Realistic small-model failure: prose wrapped around broken JSON.
            return "Sure! Here is the JSON:\n{ " + ", ".join(required[:1]) + ": }"
        obj = {}
        for key in required:
            t = types.get(key, "string")
            obj[key] = {
                "string": "value",
                "number": 1,
                "boolean": True,
                "array": [],
                "object": {},
            }.get(t, "value")
        return json.dumps(obj)
