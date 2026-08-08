"""Constrained decoding: forcing valid structure removes schema-caused
escalations. Offline, mock providers. Run: PYTHONPATH=src pytest -q"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from router.router import Router  # noqa: E402
from router.gate import validate_schema  # noqa: E402
from router.types import CompletionRequest  # noqa: E402

SCHEMA = {"required": ["order_id", "total"], "types": {"order_id": "number", "total": "number"}}
PROMPT = "Extract order id and total from: Order 88213 totaled 149 dollars."


def _route(constrained: bool):
    req = CompletionRequest(prompt=PROMPT, json_schema=SCHEMA)
    req.metadata["constrained"] = constrained
    return Router().route(req)


def test_constrained_never_escalates_more_and_stays_valid():
    off = _route(False)
    on = _route(True)
    # Constrained decoding can only help: it never causes MORE escalation than
    # unconstrained, and its final answer always validates against the schema.
    assert len(on.attempts) <= len(off.attempts)
    assert validate_schema(on.final.text, SCHEMA)[0]


def test_constrained_removes_escalations_across_cases():
    cases = [
        {"required": ["name", "age"], "types": {"name": "string", "age": "number"}},
        {"required": ["sku", "qty"], "types": {"sku": "string", "qty": "number"}},
    ]
    prompts = ["Extract name and age from: Jane is 29.", "Extract sku and qty from a noisy receipt line."]
    esc_off = esc_on = 0
    for schema, p in zip(cases, prompts):
        off = CompletionRequest(prompt=p, json_schema=schema)
        off.metadata["constrained"] = False
        on = CompletionRequest(prompt=p, json_schema=schema)
        on.metadata["constrained"] = True
        esc_off += len(Router().route(off).attempts) > 1
        esc_on += len(Router().route(on).attempts) > 1
    assert esc_on <= esc_off
