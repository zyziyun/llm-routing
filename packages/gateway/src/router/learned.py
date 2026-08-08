"""Learned difficulty classifier: the ML upgrade to the heuristic router.

A hashing bag-of-words featurizer plus a 3-class softmax regression, trained
on labeled prompts, drop-in for the heuristic `classify`. Pure Python, no
numpy / sklearn, so it trains in the test suite and CI with no extra deps.

This is the RouteLLM idea done right for this system: RouteLLM is trained on
human *preference* between open-ended answers, which does not capture whether a
structured/agent task actually succeeds. Here the classifier predicts a routing
*difficulty* and is evaluated downstream on structured-output validity and cost,
not preference. Swap the hashing featurizer for real embeddings (sentence-
transformers server-side, transformers.js in the browser) to go further.
"""

from __future__ import annotations

import hashlib
import math

from .types import CompletionRequest, Difficulty

_CLASSES = [Difficulty.EASY, Difficulty.MEDIUM, Difficulty.HARD]
_DIM = 128


def _tokens(text: str) -> list[str]:
    out: list[str] = []
    word = []
    for ch in text.lower():
        if ch.isalnum():
            word.append(ch)
        elif word:
            out.append("".join(word))
            word = []
    if word:
        out.append("".join(word))
    return out


def featurize(text: str, dim: int = _DIM) -> list[float]:
    """Hashed bag-of-words, L2-normalized. Model-free and deterministic."""
    vec = [0.0] * dim
    for tok in _tokens(text):
        h = int(hashlib.md5(tok.encode()).hexdigest(), 16) % dim
        vec[h] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


class LearnedClassifier:
    def __init__(self, dim: int = _DIM):
        self.dim = dim
        # weights[class][feature], bias[class]
        self.W = [[0.0] * dim for _ in _CLASSES]
        self.b = [0.0] * len(_CLASSES)
        self._trained = False

    def _logits(self, x: list[float]) -> list[float]:
        return [sum(self.W[c][i] * x[i] for i in range(self.dim)) + self.b[c]
                for c in range(len(_CLASSES))]

    @staticmethod
    def _softmax(z: list[float]) -> list[float]:
        m = max(z)
        e = [math.exp(v - m) for v in z]
        s = sum(e) or 1.0
        return [v / s for v in e]

    def train(self, data: list[tuple[str, Difficulty]], epochs: int = 400, lr: float = 0.5) -> None:
        xs = [featurize(t, self.dim) for t, _ in data]
        ys = [_CLASSES.index(d) for _, d in data]
        for _ in range(epochs):
            for x, y in zip(xs, ys):
                p = self._softmax(self._logits(x))
                for c in range(len(_CLASSES)):
                    err = p[c] - (1.0 if c == y else 0.0)
                    self.b[c] -= lr * err
                    if err:
                        wc = self.W[c]
                        for i in range(self.dim):
                            if x[i]:
                                wc[i] -= lr * err * x[i]
        self._trained = True

    def predict_proba(self, text: str) -> dict[Difficulty, float]:
        p = self._softmax(self._logits(featurize(text, self.dim)))
        return {_CLASSES[i]: p[i] for i in range(len(_CLASSES))}

    def classify(self, req: CompletionRequest) -> Difficulty:
        # Matches the Classifier protocol so it drops into Router(classifier=...).
        proba = self.predict_proba(req.prompt)
        return max(proba, key=proba.get)
