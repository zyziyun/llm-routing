"""Offline tests. No keys, no network. Run: PYTHONPATH=src pytest -q"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from router.classifier import HeuristicClassifier  # noqa: E402
from router.gate import validate_schema  # noqa: E402
from router.router import Router  # noqa: E402
from router.types import CompletionRequest, Difficulty, Tier  # noqa: E402


def test_easy_stays_on_edge():
    r = Router()
    res = r.route(CompletionRequest(prompt="What is the capital of France?"))
    assert res.difficulty == Difficulty.EASY
    assert res.tier_answered == Tier.EDGE
    assert res.escalations == 0


def test_hard_goes_to_frontier():
    r = Router()
    res = r.route(
        CompletionRequest(
            prompt="Design a distributed rate limiter and reason about the consistency trade-offs."
        )
    )
    assert res.difficulty == Difficulty.HARD
    assert res.tier_answered == Tier.FRONTIER


def test_schema_violation_forces_escalation():
    # A hard extraction where weak tiers emit invalid JSON must escalate and
    # end on a tier whose reply actually validates.
    r = Router()
    schema = {"required": ["service", "root_cause"], "types": {"service": "string", "root_cause": "string"}}
    res = r.route(
        CompletionRequest(
            prompt="Extract the failing service and root cause from this long incident log and return strict JSON.",
            json_schema=schema,
        )
    )
    ok, reasons = validate_schema(res.final.text, schema)
    assert ok, reasons


def test_cache_hit_is_free():
    r = Router()
    p = "Define the word ephemeral in one sentence."
    first = r.route(CompletionRequest(prompt=p))
    second = r.route(CompletionRequest(prompt=p))
    assert not first.cache_hit
    assert second.cache_hit
    assert second.total_cost_usd == 0.0


def test_classifier_labels():
    c = HeuristicClassifier()
    assert c.classify(CompletionRequest(prompt="Translate hello to French.")) == Difficulty.EASY
    assert (
        c.classify(
            CompletionRequest(
                prompt="Prove step by step why this distributed algorithm is correct and analyze its complexity."
            )
        )
        == Difficulty.HARD
    )


def test_validate_schema_rejects_prose():
    ok, reasons = validate_schema("Sure! Here is the JSON: { name: }", {"required": ["name"]})
    assert not ok
    assert reasons
