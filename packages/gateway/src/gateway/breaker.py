"""Per-provider circuit breaker. This is RELIABILITY routing, distinct from
the quality gate's INTELLIGENCE routing: the gate escalates a weak-but-working
answer, the breaker skips a provider that is failing or timing out.

States: closed (normal) -> open (skip, after N failures in a window) ->
half-open (one trial after cooldown) -> closed on success. State lives in the
shared store so it is consistent across workers.
"""

from __future__ import annotations

import time

from .metrics import BREAKER_TRIPS
from .settings import settings
from .store import Store


class CircuitOpen(Exception):
    pass


class CircuitBreaker:
    def __init__(self, store: Store, name: str) -> None:
        self.store = store
        self.name = name
        self.k_fail = f"cb:fail:{name}"
        self.k_open = f"cb:open:{name}"

    async def allow(self) -> bool:
        open_until = await self.store.get(self.k_open)
        if open_until and time.time() < float(open_until):
            return False  # open: skip this provider
        return True        # closed, or half-open trial

    async def on_success(self) -> None:
        await self.store.delete(self.k_fail, self.k_open)

    async def on_failure(self) -> None:
        n = await self.store.incr(self.k_fail, ttl=settings.breaker_window_s)
        if n >= settings.breaker_fail_threshold:
            await self.store.set(
                self.k_open,
                str(time.time() + settings.breaker_cooldown_s),
                ttl=settings.breaker_cooldown_s,
            )
            BREAKER_TRIPS.labels(provider=self.name).inc()
