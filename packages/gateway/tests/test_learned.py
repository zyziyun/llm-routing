"""Learned classifier trains and integrates with the router. Offline, pure
Python, no extra deps. Run: PYTHONPATH=src pytest -q"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from router.learned import LearnedClassifier  # noqa: E402
from router.router import Router  # noqa: E402
from router.types import CompletionRequest, Difficulty, Tier  # noqa: E402


def _data():
    rows = []
    for line in (Path(__file__).resolve().parents[1] / "eval" / "train_data.jsonl").read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            rows.append((r["prompt"], Difficulty(r["difficulty"])))
    return rows


def test_learns_the_training_signal():
    data = _data()
    clf = LearnedClassifier()
    clf.train(data)
    correct = sum(1 for p, y in data if clf.classify(CompletionRequest(prompt=p)) == y)
    assert correct / len(data) >= 0.9   # fits the labeled signal


def test_generalizes_to_unseen_clear_cases():
    clf = LearnedClassifier()
    clf.train(_data())
    assert clf.classify(CompletionRequest(prompt="What is the capital of Italy?")) == Difficulty.EASY
    assert clf.classify(CompletionRequest(
        prompt="Design a distributed lock and analyze the failure modes.")) == Difficulty.HARD


def test_drops_into_the_router():
    clf = LearnedClassifier()
    clf.train(_data())
    r = Router(classifier=clf).route(CompletionRequest(prompt="Translate hello to German."))
    assert r.difficulty == Difficulty.EASY
    assert r.tier_answered == Tier.EDGE      # easy -> answered on the cheapest tier


def test_predict_proba_sums_to_one():
    clf = LearnedClassifier()
    clf.train(_data())
    proba = clf.predict_proba("Explain what a mutex is.")
    assert abs(sum(proba.values()) - 1.0) < 1e-6
