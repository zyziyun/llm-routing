"""Runnable monitoring demo. Drives the gateway with a scripted mix of
requests (via the in-process TestClient, so no server, no keys, no GPU) and
renders a terminal dashboard: per-request routing decisions, the tier mix,
cost vs an all-frontier baseline, cache hits, and a live scrape of the
Prometheus /metrics endpoint.

    PYTHONPATH=src python demo/demo.py

For the full visual stack (Prometheus + Grafana) use
`docker compose -f deploy/docker-compose.yml up`; for the browser frontend see
packages/edge-client (`npm run dev`).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Quiet the structured request logs so the dashboard stays readable.
os.environ.setdefault("GW_LOG_LEVEL", "ERROR")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from gateway.app import app  # noqa: E402

AUTH = {"Authorization": "Bearer dev-key"}

SCRIPT = [
    ("easy",   "What is the capital of France?"),
    ("easy",   "Translate good morning into Spanish."),
    ("medium", "Explain what a database index is and when it helps."),
    ("medium", "Summarize what a REST API is in two sentences."),
    ("hard",   "Design a distributed rate limiter and reason about the consistency trade-offs."),
    ("hard",   "Derive the average and worst case time complexity of quicksort."),
    ("schema", "Extract the failing service and root cause from this incident log."),
    ("repeat", "What is the capital of France?"),   # cache hit
]

SCHEMA = {"required": ["service", "root_cause"], "types": {"service": "string", "root_cause": "string"}}
FRONTIER_UNIT = 0.01   # counterfactual: cost if every request hit the frontier


def bar(label: str, n: int, total: int, width: int = 24) -> str:
    fill = int(round(width * n / total)) if total else 0
    return f"  {label:<9}{'█' * fill}{'·' * (width - fill)} {n}"


def main() -> None:
    with TestClient(app) as c:
        rows = []
        tiers: dict[str, int] = {}
        total_cost = 0.0
        cache_hits = 0
        print("=" * 60)
        print("  llm-gateway  ·  live routing demo")
        print("=" * 60)
        print(f"  {'kind':<8}{'difficulty':<11}{'tier':<10}{'esc':<5}{'cost$':<9}cache")
        print("  " + "-" * 54)
        for kind, prompt in SCRIPT:
            body = {"messages": [{"role": "user", "content": prompt}]}
            if kind == "schema":
                body["json_schema"] = SCHEMA
            g = c.post("/v1/chat/completions", headers=AUTH, json=body).json()["x_gateway"]
            tiers[g["tier"]] = tiers.get(g["tier"], 0) + 1
            total_cost += g["cost_usd"]
            cache_hits += 1 if g["cache_hit"] else 0
            rows.append(g)
            print(f"  {kind:<8}{g['difficulty']:<11}{g['tier']:<10}"
                  f"{g['escalations']:<5}{g['cost_usd']:<9.5f}{'HIT' if g['cache_hit'] else ''}")

        n = len(SCRIPT)
        baseline = FRONTIER_UNIT * n
        saved = (1 - total_cost / baseline) * 100 if baseline else 0.0

        print("\n  tier distribution")
        for t in ("edge", "cheap", "frontier", "cache"):
            if tiers.get(t):
                print(bar(t, tiers[t], n))

        print(f"\n  requests        {n}")
        print(f"  cache hits      {cache_hits}")
        print(f"  cost            ${total_cost:.5f}   (all-frontier baseline ${baseline:.5f})")
        print(f"  cost saved      {saved:.0f}%")

        print("\n  Prometheus /metrics (selected)")
        metrics = c.get("/metrics").text
        for line in metrics.splitlines():
            if line.startswith(("gw_requests_total", "gw_cost_usd_total",
                                "gw_cache_hits_total", "gw_escalations_total")) \
                    and "_created" not in line:
                print("    " + line)
    print("=" * 60)


if __name__ == "__main__":
    main()
