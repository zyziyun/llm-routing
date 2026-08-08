"""Quality gate: the second and most important place AI enters a router.

This is what turns a plain error-fallback into a quality-aware control loop.
A reply is accepted only if BOTH hold:

  1. Structured-output validity. If the request demands JSON, the reply must
     parse and satisfy the minimal schema. This is the check that actually
     matters for agent/tool tasks, and it is exactly what preference-trained
     routers like RouteLLM do NOT capture. Validate it yourself.
  2. Confidence bar. The reply's confidence must clear the threshold. On the
     EDGE tier this is the "uncertainty-aware escalation" trigger: a
     low-confidence local answer is bumped to a stronger tier.

Optionally a third stage runs an LLM-as-judge for non-schema tasks, scoring
the answer's quality with a stronger model. Off by default so the lab needs
no keys.
"""

from __future__ import annotations

import json
from typing import Any

from .config import CONFIG
from .types import CompletionRequest, GateVerdict, ProviderReply, Tier


def _extract_json(text: str) -> Any:
    """Best-effort JSON extraction: whole string, else first {...} block."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return json.loads(text[start : end + 1])  # may raise; caller catches
    raise json.JSONDecodeError("no JSON found", text, 0)


def validate_schema(text: str, schema: dict) -> tuple[bool, list[str]]:
    required = schema.get("required", [])
    types = schema.get("types", {})
    try:
        obj = _extract_json(text)
    except json.JSONDecodeError:
        return False, ["reply is not valid JSON"]
    if not isinstance(obj, dict):
        return False, ["top-level JSON is not an object"]
    reasons: list[str] = []
    for key in required:
        if key not in obj:
            reasons.append(f"missing required key: {key}")
            continue
        want = types.get(key)
        if want and not _type_ok(obj[key], want):
            reasons.append(f"key {key} has wrong type, want {want}")
    return (len(reasons) == 0), reasons


def _type_ok(value: Any, want: str) -> bool:
    return {
        "string": isinstance(value, str),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "array": isinstance(value, list),
        "object": isinstance(value, dict),
    }.get(want, True)


class QualityGate:
    def __init__(self, llm_judge=None):
        # llm_judge: optional callable(request, reply) -> float in [0,1].
        self.llm_judge = llm_judge

    def assess(self, request: CompletionRequest, reply: ProviderReply) -> GateVerdict:
        reasons: list[str] = []
        schema_ok = True
        if request.requires_schema:
            schema_ok, schema_reasons = validate_schema(reply.text, request.json_schema)
            reasons += schema_reasons

        confidence = reply.confidence
        conf_ok = confidence >= CONFIG.confidence_threshold
        if not conf_ok:
            reasons.append(
                f"confidence {confidence:.2f} < {CONFIG.confidence_threshold:.2f}"
            )

        judge_ok = True
        judge_score = 1.0
        if (
            CONFIG.use_llm_judge
            and self.llm_judge is not None
            and not request.requires_schema
            and reply.tier != Tier.FRONTIER  # do not judge the top tier against itself
        ):
            judge_score = self.llm_judge(request, reply)
            judge_ok = judge_score >= CONFIG.llm_judge_threshold
            if not judge_ok:
                reasons.append(f"judge score {judge_score:.2f} < {CONFIG.llm_judge_threshold:.2f}")

        acceptable = schema_ok and conf_ok and judge_ok
        # Overall score for logging: blend confidence and judge signal.
        score = round(min(confidence, judge_score) if not request.requires_schema
                      else (confidence if schema_ok else 0.0), 3)
        return GateVerdict(
            acceptable=acceptable,
            score=score,
            schema_ok=schema_ok,
            confidence=confidence,
            reasons=reasons,
        )


def make_llm_judge(frontier_provider):
    """Build an LLM-as-judge that scores an answer with the frontier model.

    Returns a callable(request, reply) -> float. The judge asks the strong
    model to rate faithfulness+relevance in [0,1]. Kept simple on purpose;
    for RAG tasks, swap in RAGAS-style faithfulness/answer-relevance metrics.
    """

    def judge(request: CompletionRequest, reply: ProviderReply) -> float:
        probe = CompletionRequest(
            prompt=(
                "Rate the answer from 0 to 1 for correctness and relevance to the "
                "question. Reply with only the number.\n\n"
                f"QUESTION:\n{request.prompt}\n\nANSWER:\n{reply.text}"
            ),
            max_tokens=8,
        )
        out = frontier_provider.complete(probe)
        try:
            return max(0.0, min(1.0, float(out.text.strip().split()[0])))
        except (ValueError, IndexError):
            return 0.5

    return judge
