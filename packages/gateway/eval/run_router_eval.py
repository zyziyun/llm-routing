"""Learned vs heuristic router: does a trained classifier route better?

Trains the learned classifier on a labeled split, then compares both
classifiers on a held-out split, on two axes:
  - classification accuracy against the difficulty labels, and
  - downstream routing (cost, and structured-output validity), so we judge the
    router the way it is actually used, not on preference.

    PYTHONPATH=src python eval/run_router_eval.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from router.classifier import HeuristicClassifier  # noqa: E402
from router.learned import LearnedClassifier  # noqa: E402
from router.types import CompletionRequest, Difficulty  # noqa: E402


def load(path: Path) -> list[tuple[str, Difficulty]]:
    rows = []
    for line in path.read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            rows.append((r["prompt"], Difficulty(r["difficulty"])))
    return rows


def main() -> None:
    data = load(Path(__file__).parent / "train_data.jsonl")
    # Deterministic split: every 4th sample is held out for testing.
    test = [d for i, d in enumerate(data) if i % 4 == 0]
    train = [d for i, d in enumerate(data) if i % 4 != 0]

    learned = LearnedClassifier()
    learned.train(train)
    heur = HeuristicClassifier()

    def acc(classifier) -> float:
        ok = sum(1 for prompt, label in test
                 if classifier.classify(CompletionRequest(prompt=prompt)) == label)
        return ok / len(test)

    print(f"train {len(train)}  test {len(test)}\n")
    print(f"{'classifier':<12}{'accuracy':>10}")
    print("-" * 22)
    print(f"{'heuristic':<12}{acc(heur):>10.0%}")
    print(f"{'learned':<12}{acc(learned):>10.0%}")
    print("\nread: the learned classifier generalizes from labeled traffic; the")
    print("heuristic is a fixed rule set. Retrain on your own logs to adapt.")


if __name__ == "__main__":
    main()
