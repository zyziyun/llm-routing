"""Async provider protocol. Same reply shape as the lab core, but every
call is awaitable so one worker handles many concurrent requests."""

from __future__ import annotations

from typing import AsyncIterator, Protocol

from router.types import CompletionRequest, ProviderReply, Tier


class AsyncProvider(Protocol):
    tier: Tier
    model: str

    async def complete(self, request: CompletionRequest) -> ProviderReply: ...

    def stream(self, request: CompletionRequest) -> AsyncIterator[str]:
        """Yield text chunks. Default implementations may buffer then chunk."""
        ...
