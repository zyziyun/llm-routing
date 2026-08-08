"""Eval harness: baseline (always frontier) vs the router.

Reports, per strategy:
  - total cost
  - average latency
  - quality/validity rate: fraction of replies that pass the gate. For
    schema cases this is structured-output validity, which is the metric
    that actually matters for agent tasks and the one preference-trained
    routers miss. For the rest it is the confidence/judge gate.
  - the router's tier mix: where the traffic actually went.

Run:
    PYTHONPATH=src python eval/run_eval.py
    PYTHONPATH=src python eval/run_eval.py --cases eval/cases.jsonl
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from router.gate import QualityGate  # noqa: E402
from router.providers.registry import build_registry  # noqa: E402
from router.router import Router  # noqa: E402
from router.types import CompletionRequest, Tier  # noqa: E402


def load_cases(path: str) -> list[CompletionRequest]:
    reqs = []
    for line in Path(path).read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        reqs.append(
            CompletionRequest(prompt=row["prompt"], json_schema=row.get("json_schema"))
        )
    return reqs


def run_baseline(cases: list[CompletionRequest]) -> dict:
    """Always call the frontier model. This is the 'use GPT-4 for everything'
    default the router is trying to beat."""
    providers = build_registry()
    gate = QualityGate()
    cost = latency = passed = 0.0
    for req in cases:
        # Fresh request so the shared classifier metadata does not leak.
        r = CompletionRequest(prompt=req.prompt, json_schema=req.json_schema)
        r.metadata["difficulty"] = "hard"  # frontier is unaffected; keeps mock honest
        reply = providers[Tier.FRONTIER].complete(r)
        v = gate.assess(r, reply)
        cost += reply.cost_usd
        latency += reply.latency_ms
        passed += 1 if v.acceptable else 0
    n = len(cases)
    return {"cost": cost, "avg_latency": latency / n, "quality": passed / n}


def run_router(cases: list[CompletionRequest]) -> dict:
    router = Router()
    cost = latency = passed = 0.0
    mix: dict[str, int] = {}
    for req in cases:
        r = CompletionRequest(prompt=req.prompt, json_schema=req.json_schema)
        result = router.route(r)
        cost += result.total_cost_usd
        latency += result.total_latency_ms
        passed += 1 if (result.attempts and result.attempts[-1].verdict.acceptable) else 0
        mix[result.tier_answered.value] = mix.get(result.tier_answered.value, 0) + 1
    n = len(cases)
    return {"cost": cost, "avg_latency": latency / n, "quality": passed / n, "mix": mix}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default=str(Path(__file__).parent / "cases.jsonl"))
    args = ap.parse_args()

    cases = load_cases(args.cases)
    base = run_baseline(cases)
    routed = run_router(cases)

    saved = (1 - routed["cost"] / base["cost"]) * 100 if base["cost"] else 0.0

    print(f"cases: {len(cases)}\n")
    print(f"{'strategy':<18}{'cost($)':>10}{'avg_ms':>10}{'quality':>10}")
    print("-" * 48)
    print(f"{'baseline-frontier':<18}{base['cost']:>10.5f}{base['avg_latency']:>10.1f}{base['quality']:>10.0%}")
    print(f"{'router':<18}{routed['cost']:>10.5f}{routed['avg_latency']:>10.1f}{routed['quality']:>10.0%}")
    print("-" * 48)
    print(f"cost saved vs baseline: {saved:.1f}%")
    print(f"router tier mix       : {routed['mix']}")
    print(
        "\nread: the router should cut cost sharply while keeping quality "
        "close to baseline. If quality drops too far, raise CONFIDENCE_THRESHOLD."
    )


if __name__ == "__main__":
    main()
