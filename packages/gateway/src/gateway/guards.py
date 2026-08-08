"""Per-key rate limiting and budget caps. Cost governance and abuse control,
enforced in the shared store so limits hold across workers.

Rate limit: fixed-window per minute (simple, predictable, redis-cheap).
Budget: rolling daily spend cap in USD; the router reports actual cost and we
reject once the day's cap is hit.
"""

from __future__ import annotations

import time

from .store import Store


def _minute_bucket() -> int:
    return int(time.time() // 60)


def _day_bucket() -> str:
    return time.strftime("%Y%m%d", time.gmtime())


class RateLimiter:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def check(self, api_key: str, rpm: int) -> bool:
        key = f"rl:{api_key}:{_minute_bucket()}"
        n = await self.store.incr(key, ttl=60)
        return n <= rpm


class BudgetGuard:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def remaining(self, api_key: str, daily_cap: float) -> float:
        key = f"spend:{api_key}:{_day_bucket()}"
        spent = float(await self.store.get(key) or 0.0)
        return max(0.0, daily_cap - spent)

    async def charge(self, api_key: str, amount: float) -> None:
        key = f"spend:{api_key}:{_day_bucket()}"
        await self.store.incrbyfloat(key, amount, ttl=86400 * 2)
