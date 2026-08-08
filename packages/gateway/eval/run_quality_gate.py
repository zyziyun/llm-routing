"""Quality regression gate for CI.

Runs the router over a golden set and enforces three budgets. It exits non-zero
if any is breached, so a change that quietly regresses quality fails the build:

  - validity: every schema task's final answer must be valid JSON. If someone
    weakens the gate and lets invalid structure through, this drops -> fail.
  - cost: total spend must stay under budget. If routing breaks and everything
    escalates to frontier, cost rises -> fail.
  - escalation: the escalated share must stay under budget. Catches both
    over-escalation and (via validity) under-escalation that ships bad answers.

Offline and deterministic (mock providers). With real models you would add an
LLM-as-judge / RAGAS faithfulness score here as a fourth budget.

    PYTHONPATH=src python eval/run_quality_gate.py   # exit 0 pass, 1 regression
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from router.gate import validate_schema  # noqa: E402
from router.router import Router  # noqa: E402
from router.types import CompletionRequest  # noqa: E402

# Budgets, pinned to the current healthy baseline with margin. Tighten as the
# router improves; a regression past these fails CI.
VALIDITY_MIN = 1.0        # 100% of schema tasks must validate
COST_MAX_USD = 0.0060     # baseline router ~0.0042 on this golden set
ESCALATION_MAX = 0.60     # escalated share ceiling


def _load(path: Path) -> list[CompletionRequest]:
    reqs = []
    for line in path.read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            reqs.append(CompletionRequest(prompt=r["prompt"], json_schema=r.get("json_schema")))
    return reqs


def evaluate() -> tuple[bool, dict]:
    cases = _load(Path(__file__).parent / "cases.jsonl")
    router = Router()
    cost = escalated = valid = schema_n = 0.0
    for c in cases:
        req = CompletionRequest(prompt=c.prompt, json_schema=c.json_schema)
        r = router.route(req)
        cost += r.total_cost_usd
        if len(r.attempts) > 1:
            escalated += 1
        if req.requires_schema:
            schema_n += 1
            if validate_schema(r.final.text, req.json_schema)[0]:
                valid += 1
    n = len(cases)
    m = {
        "validity": (valid / schema_n) if schema_n else 1.0,
        "cost": round(cost, 6),
        "escalation": escalated / n,
        "n": n,
        "schema_n": int(schema_n),
    }
    passed = (
        m["validity"] >= VALIDITY_MIN
        and m["cost"] <= COST_MAX_USD
        and m["escalation"] <= ESCALATION_MAX
    )
    return passed, m


def main() -> None:
    passed, m = evaluate()
    checks = [
        ("validity", f"{m['validity']:.0%}", ">=", f"{VALIDITY_MIN:.0%}", m["validity"] >= VALIDITY_MIN),
        ("cost($)", f"{m['cost']:.5f}", "<=", f"{COST_MAX_USD:.5f}", m["cost"] <= COST_MAX_USD),
        ("escalation", f"{m['escalation']:.0%}", "<=", f"{ESCALATION_MAX:.0%}", m["escalation"] <= ESCALATION_MAX),
    ]
    print(f"golden set: {m['n']} cases ({m['schema_n']} schema)\n")
    print(f"{'metric':<12}{'value':>10}{'':>4}{'budget':>10}{'':>4}{'ok':>4}")
    print("-" * 46)
    for name, val, op, budget, ok in checks:
        print(f"{name:<12}{val:>10}{op:>4}{budget:>10}{'':>4}{'yes' if ok else 'NO':>4}")
    print("-" * 46)
    print("QUALITY GATE: " + ("PASS" if passed else "FAIL"))
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()
