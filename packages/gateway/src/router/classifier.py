"""Difficulty classifier: the first place AI enters a router.

Two implementations behind one interface:

  - HeuristicClassifier: rules over length, reasoning cues, and whether a
    schema is demanded. Zero-cost, deterministic, a fine baseline.
  - EmbeddingClassifier: nearest-neighbour over a few labelled anchors using
    an embedding function you provide. This is the "AI routing decision"
    upgrade the handout talks about; wire it to a real embedder to use it.

The classifier decides which tier the ladder STARTS at, not the final
answer. The quality gate still has the last word via escalation.
"""

from __future__ import annotations

from typing import Callable, Protocol

from .types import CompletionRequest, Difficulty

_HARD_CUES = (
    "prove", "derive", "step by step", "reason", "trade-off", "tradeoff",
    "design", "architecture", "why", "compare", "optimi", "edge case",
    "concurren", "distributed", "algorithm", "complexity",
)
_EASY_CUES = ("translate", "capital of", "define", "spell", "convert", "format", "list the")


class Classifier(Protocol):
    def classify(self, request: CompletionRequest) -> Difficulty: ...


class HeuristicClassifier:
    def classify(self, request: CompletionRequest) -> Difficulty:
        p = request.prompt.lower()
        words = len(p.split())

        score = 0
        score += sum(2 for c in _HARD_CUES if c in p)
        score -= sum(2 for c in _EASY_CUES if c in p)
        if words > 60:
            score += 2
        elif words < 12:
            score -= 1
        # A demanded schema is not itself hard, but structured extraction on
        # long inputs tends to be, so nudge up a little.
        if request.requires_schema and words > 40:
            score += 1

        if score >= 3:
            return Difficulty.HARD
        if score <= -1:
            return Difficulty.EASY
        return Difficulty.MEDIUM


class EmbeddingClassifier:
    """Nearest-anchor classifier. `embed` maps text -> list[float].

    Provide a handful of labelled anchors; at query time we pick the label
    of the closest anchor by cosine similarity. Swap `embed` for a real
    sentence-embedding model to make this genuinely semantic.
    """

    def __init__(
        self,
        embed: Callable[[str], list[float]],
        anchors: list[tuple[str, Difficulty]],
    ):
        self.embed = embed
        self.anchors = [(self._norm(embed(t)), d) for t, d in anchors]

    def classify(self, request: CompletionRequest) -> Difficulty:
        q = self._norm(self.embed(request.prompt))
        best, best_sim = Difficulty.MEDIUM, -2.0
        for vec, label in self.anchors:
            sim = sum(a * b for a, b in zip(q, vec))
            if sim > best_sim:
                best_sim, best = sim, label
        return best

    @staticmethod
    def _norm(v: list[float]) -> list[float]:
        mag = sum(x * x for x in v) ** 0.5 or 1.0
        return [x / mag for x in v]
