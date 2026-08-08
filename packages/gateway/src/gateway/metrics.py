"""Prometheus metrics. Exposed at /metrics for scraping. These are the
numbers you put on a Grafana dashboard: request rate, latency, spend, tier
mix, breaker trips."""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

REQUESTS = Counter(
    "gw_requests_total", "Requests handled", ["tier", "outcome"]
)
LATENCY = Histogram(
    "gw_request_latency_seconds", "End-to-end routing latency", ["tier"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10),
)
COST = Counter("gw_cost_usd_total", "Estimated spend", ["tier"])
ESCALATIONS = Counter("gw_escalations_total", "Tier escalations")
CACHE_HITS = Counter("gw_cache_hits_total", "Cache hits")
BREAKER_TRIPS = Counter("gw_breaker_trips_total", "Circuit breaker opens", ["provider"])
RATE_LIMITED = Counter("gw_rate_limited_total", "Requests rejected by rate limit")
BUDGET_BLOCKED = Counter("gw_budget_blocked_total", "Requests rejected by budget cap")
INFLIGHT = Gauge("gw_inflight_requests", "In-flight requests")
