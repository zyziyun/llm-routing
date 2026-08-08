"""The quality regression gate passes on the current code. Offline. If a
change regresses validity/cost/escalation past budget, this fails too."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))

from run_quality_gate import evaluate  # noqa: E402


def test_quality_gate_passes():
    passed, metrics = evaluate()
    assert passed, metrics
    assert metrics["validity"] == 1.0
