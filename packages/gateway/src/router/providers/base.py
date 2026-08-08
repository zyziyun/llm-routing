"""Provider protocol. A provider turns a request into a ProviderReply for
one tier. Real and mock providers implement the same interface, so the
router is agnostic to what is behind each tier."""

from __future__ import annotations

from typing import Protocol

from ..types import CompletionRequest, ProviderReply, Tier


class Provider(Protocol):
    tier: Tier
    model: str

    def complete(self, request: CompletionRequest) -> ProviderReply: ...


def estimate_tokens(text: str) -> int:
    """Cheap token estimate, ~4 chars per token. Good enough for cost math
    here; swap for a real tokenizer when you wire real providers."""
    return max(1, len(text) // 4)
