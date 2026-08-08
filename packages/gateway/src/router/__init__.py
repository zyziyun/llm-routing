"""llm-router-lab: a small, deployable LLM router / gateway.

Public surface:
    from router import Router, CompletionRequest
"""

from .router import Router
from .types import CompletionRequest, RouteResult, Tier, Difficulty

__all__ = ["Router", "CompletionRequest", "RouteResult", "Tier", "Difficulty"]
