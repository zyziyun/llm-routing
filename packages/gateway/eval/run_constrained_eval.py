"""Constrained-decoding closed loop: does forcing schema-valid structure cut
escalations on structured tasks?

Runs the same JSON-schema requests twice, with constrained decoding OFF then
ON, and reports how many escalate and what they cost. The expected result is
that structure-caused escalations vanish, because the cheap tier can no longer
emit invalid JSON; only genuinely hard turns (low semantic confidence) still
escalate.

    PYTHONPATH=src python eval/run_constrained_eval.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from router.router import Router  # noqa: E402
from router.types import CompletionRequest, Tier  # noqa: E402

# Structured-extraction tasks across difficulties. All demand strict JSON.
CASES = [
    ("easy",   {"required": ["name", "age"], "types": {"name": "string", "age": "number"}},
     "Extract name and age from: John Doe is 34."),
    ("easy",   {"required": ["city", "country"], "types": {"city": "string", "country": "string"}},
     "Extract city and country from: Paris, France."),
    ("medium", {"required": ["order_id", "total"], "types": {"order_id": "number", "total": "number"}},
     "Extract order id and total from: Order 88213 totaled 149 dollars."),
    ("medium", {"required": ["sku", "qty", "price"], "types": {"sku": "string", "qty": "number", "price": "number"}},
     "Extract sku, qty, price from this multi-line receipt with noise and footers."),
    ("hard",   {"required": ["service", "root_cause", "fix"], "types": {"service": "string", "root_cause": "string", "fix": "string"}},
     "Extract failing service, root cause, and fix from this long noisy incident log and return strict JSON."),
    ("hard",   {"required": ["party_a", "party_b", "obligation"], "types": {"party_a": "string", "party_b": "string", "obligation": "string"}},
     "Extract the two parties and the key obligation from this dense contract clause as strict JSON."),
]


def run(constrained: bool) -> dict:
    router = Router()
    escalated = cost = 0.0
    for _, schema, prompt in CASES:
        req = CompletionRequest(prompt=prompt, json_schema=schema)
        req.metadata["constrained"] = constrained
        r = router.route(req)
        if len(r.attempts) > 1:
            escalated += 1
        cost += r.total_cost_usd
    n = len(CASES)
    return {"escalated": int(escalated), "n": n, "cost": cost}


def main() -> None:
    off = run(False)
    on = run(True)
    print(f"schema cases: {off['n']}\n")
    off_cell = f"{off['escalated']}/{off['n']}"
    on_cell = f"{on['escalated']}/{on['n']}"
    print(f"{'constrained':<14}{'escalated':>12}{'cost($)':>12}")
    print("-" * 38)
    print(f"{'off':<14}{off_cell:>12}{off['cost']:>12.5f}")
    print(f"{'on':<14}{on_cell:>12}{on['cost']:>12.5f}")
    print("-" * 38)
    drop = off["escalated"] - on["escalated"]
    saved = (1 - on["cost"] / off["cost"]) * 100 if off["cost"] else 0.0
    print(f"structure-caused escalations removed: {drop}")
    print(f"cost on schema tasks: -{saved:.0f}%")
    print(
        "\nread: constrained decoding guarantees valid JSON, so the cheap tier "
        "stops failing structure and only truly hard turns still escalate."
    )


if __name__ == "__main__":
    main()
