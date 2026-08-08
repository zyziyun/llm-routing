"""Typed settings loaded from env / .env. Validated at startup, so a
misconfigured deploy fails fast instead of at first request."""

from __future__ import annotations

import json

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GW_", env_file=".env", extra="ignore")

    # --- serving ---
    env: str = "dev"
    log_level: str = "INFO"
    request_timeout_s: float = 30.0
    per_attempt_timeout_s: float = 20.0

    # --- state backend ---
    # redis://host:6379/0 for production; empty string => in-memory fallback.
    redis_url: str = ""
    cache_ttl_s: int = 3600

    # --- routing ---
    confidence_threshold: float = 0.62
    edge_backend: str = "mock"
    cheap_backend: str = "mock"
    frontier_backend: str = "mock"

    # --- circuit breaker (per provider) ---
    breaker_fail_threshold: int = 5
    breaker_window_s: int = 30
    breaker_cooldown_s: int = 15

    # --- auth / tenancy ---
    # JSON: {"<api_key>": {"tenant": "acme", "rpm": 120, "daily_usd": 5.0}}
    api_keys_json: str = ""

    def api_keys(self) -> dict[str, dict]:
        if self.api_keys_json:
            return json.loads(self.api_keys_json)
        # Dev default so the service is usable out of the box.
        return {"dev-key": {"tenant": "dev", "rpm": 120, "daily_usd": 10.0}}


settings = Settings()
