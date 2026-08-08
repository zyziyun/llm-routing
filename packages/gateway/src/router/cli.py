"""CLI: route one prompt and print the decision trail.

    PYTHONPATH=src python -m router.cli "What is the capital of France?"
    PYTHONPATH=src python -m router.cli --schema name,age "Extract the person"
"""

from __future__ import annotations

import argparse
import json

from .router import Router
from .types import CompletionRequest


def main() -> None:
    ap = argparse.ArgumentParser(description="Route one prompt through the tier ladder.")
    ap.add_argument("prompt")
    ap.add_argument("--schema", help="comma-separated required JSON keys", default=None)
    args = ap.parse_args()

    schema = None
    if args.schema:
        keys = [k.strip() for k in args.schema.split(",") if k.strip()]
        schema = {"required": keys, "types": {k: "string" for k in keys}}

    result = Router().route(CompletionRequest(prompt=args.prompt, json_schema=schema))

    print(f"difficulty      : {result.difficulty.value}")
    print(f"cache hit       : {result.cache_hit}")
    print(f"answered by     : {result.tier_answered.value}")
    print(f"escalations     : {result.escalations}")
    print(f"total cost (USD): {result.total_cost_usd}")
    print(f"total latency ms: {result.total_latency_ms}")
    print("attempts        :")
    for a in result.attempts:
        flag = "ok" if a.verdict.acceptable else "escalate"
        reason = "" if a.verdict.acceptable else f"  reasons={a.verdict.reasons}"
        print(f"   - {a.tier.value:8s} conf={a.reply.confidence:.2f} {flag}{reason}")
    print("final answer    :")
    print(f"   {result.final.text}")
    print(json.dumps({"model": result.final.model, "tier": result.final.tier.value}))


if __name__ == "__main__":
    main()
