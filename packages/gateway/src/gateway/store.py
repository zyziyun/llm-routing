"""Shared state backend. Redis in production, in-memory fallback for local
and CI. Same async interface either way, so nothing above this file knows
which one is live. Cache, rate-limit counters, budget spend, and circuit
breaker state all sit here, which is what lets the gateway scale to more
than one worker.
"""

from __future__ import annotations

import asyncio
import time
from typing import Optional

from .settings import settings


class Store:
    async def get(self, key: str) -> Optional[str]: ...
    async def set(self, key: str, value: str, ttl: Optional[int] = None) -> None: ...
    async def delete(self, *keys: str) -> None: ...
    async def incr(self, key: str, ttl: Optional[int] = None) -> int: ...
    async def incrbyfloat(self, key: str, amount: float, ttl: Optional[int] = None) -> float: ...
    async def ping(self) -> bool: ...


class MemoryStore(Store):
    """Async-safe in-process store with TTL. Not shared across processes;
    fine for a single worker, local dev, and tests."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[str, Optional[float]]] = {}
        self._lock = asyncio.Lock()

    def _alive(self, key: str) -> bool:
        item = self._data.get(key)
        if item is None:
            return False
        _, exp = item
        if exp is not None and exp < time.time():
            self._data.pop(key, None)
            return False
        return True

    async def get(self, key: str) -> Optional[str]:
        async with self._lock:
            return self._data[key][0] if self._alive(key) else None

    async def set(self, key: str, value: str, ttl: Optional[int] = None) -> None:
        async with self._lock:
            self._data[key] = (value, time.time() + ttl if ttl else None)

    async def delete(self, *keys: str) -> None:
        async with self._lock:
            for k in keys:
                self._data.pop(k, None)

    async def incr(self, key: str, ttl: Optional[int] = None) -> int:
        async with self._lock:
            cur = int(self._data[key][0]) if self._alive(key) else 0
            cur += 1
            exp = self._data[key][1] if self._alive(key) else (time.time() + ttl if ttl else None)
            self._data[key] = (str(cur), exp)
            return cur

    async def incrbyfloat(self, key: str, amount: float, ttl: Optional[int] = None) -> float:
        async with self._lock:
            cur = float(self._data[key][0]) if self._alive(key) else 0.0
            cur += amount
            exp = self._data[key][1] if self._alive(key) else (time.time() + ttl if ttl else None)
            self._data[key] = (repr(cur), exp)
            return cur

    async def ping(self) -> bool:
        return True


class RedisStore(Store):
    """Redis-backed store for production and multi-worker deploys."""

    def __init__(self, url: str) -> None:
        import redis.asyncio as aioredis  # imported lazily so offline needs no redis

        self._r = aioredis.from_url(url, decode_responses=True)

    async def get(self, key: str) -> Optional[str]:
        return await self._r.get(key)

    async def set(self, key: str, value: str, ttl: Optional[int] = None) -> None:
        await self._r.set(key, value, ex=ttl)

    async def delete(self, *keys: str) -> None:
        if keys:
            await self._r.delete(*keys)

    async def incr(self, key: str, ttl: Optional[int] = None) -> int:
        n = await self._r.incr(key)
        if ttl and n == 1:
            await self._r.expire(key, ttl)
        return n

    async def incrbyfloat(self, key: str, amount: float, ttl: Optional[int] = None) -> float:
        n = await self._r.incrbyfloat(key, amount)
        if ttl:
            await self._r.expire(key, ttl)
        return n

    async def ping(self) -> bool:
        try:
            return bool(await self._r.ping())
        except Exception:
            return False


def build_store() -> Store:
    if settings.redis_url:
        try:
            return RedisStore(settings.redis_url)
        except Exception:  # redis lib missing or bad URL -> degrade, do not crash
            pass
    return MemoryStore()
