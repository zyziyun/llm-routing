# Scaling this gateway: the infra to add

The app is production-shaped. Running it at real scale is mostly an
infrastructure exercise around it. This is the map: the target architecture,
then what to add, marking what the repo already has (DONE) vs the gaps.

## Target architecture

```
              ┌─────────── edge ───────────┐
client ─▶ CDN + WAF (Cloud Armor) ─▶ Cloud Run / GKE gateway pods (autoscaled)
                                        │
        ┌───────────────────────────────┼───────────────────────────────┐
        ▼                               ▼                               ▼
  Memorystore Redis            model tiers                       async usage
  (cache, breaker,        EDGE: vLLM/Ollama on GPU pool     Pub/Sub or Kafka ─▶ BigQuery
   rate-limit, budget)    CHEAP/FRONTIER: hosted APIs         (billing + analytics)
        │
        ▼
  observability: OpenTelemetry ─▶ Cloud Trace ; Prometheus ─▶ Grafana ; logs ─▶ Cloud Logging ; Alertmanager
  secrets: Secret Manager   |   IaC: Terraform   |   CI/CD: GitHub Actions canary
```

## What to add, by area

### 1. Scale-out and load
- DONE: async app, pooled httpx client, Cloud Run `$PORT`, k8s HPA manifest.
- ADD: tune per-instance concurrency; run a load test (k6 or Locust) and
  record capacity numbers (RPS, p50/p99, cost/1k req). Multi-region for
  latency and failover.

### 2. Shared state
- DONE: state abstraction with Redis backend + in-memory fallback.
- ADD: managed Redis (Memorystore / Upstash / ElastiCache), HA / cluster
  mode; cache-stampede protection (single-flight per key); semantic cache
  backed by a real vector store (Redis vector or pgvector).

### 3. Reliability
- DONE: per-provider circuit breaker, per-attempt timeouts, quality + failure
  escalation.
- ADD: retries with exponential backoff and jitter on transient upstream
  errors; per-provider concurrency bulkheads so one slow provider cannot
  starve others; hedged requests for tail latency; graceful connection
  draining on shutdown; idempotency keys; chaos tests (kill a provider,
  assert the breaker holds).

### 4. Async and data plane
- ADD: emit a usage event per request to Pub/Sub or Kafka, consumed into
  BigQuery or Postgres for billing, per-tenant reporting, and tier-mix cost
  analysis. Keep it OFF the hot path so logging cost never slows a request.
  For long jobs, put a queue in front and process with workers instead of
  serving synchronously.

### 5. Observability
- DONE: Prometheus `/metrics`, structured JSON logs with request_id.
- ADD: OpenTelemetry tracing with context propagation (trace a request across
  gateway and providers); log aggregation (Loki / Cloud Logging); SLOs plus
  Alertmanager alerts on error rate, p99 latency, breaker trips, and budget
  exhaustion; a Grafana dashboard shipped as code.

### 6. Security
- DONE: API-key auth, per-key limits, k8s Secret reference for provider keys.
- ADD: Secret Manager for all secrets (no plaintext env in prod); per-tenant
  scoping, optionally JWT/OAuth; input validation and prompt-injection /
  PII guardrails on the request path; edge rate limiting and WAF (Cloud
  Armor); TLS everywhere, least-privilege IAM, container image scanning.

### 7. Cost governance
- DONE: per-key daily budget cap and rate limit.
- ADD: global spend ceiling with alerting; usage and cost dashboards per
  tenant and per tier; anomaly alerts on sudden spend.

### 8. Model-tier infra (only if self-hosting the small model)
- ADD: GPU node pool with vLLM or Triton, continuous batching and KV cache;
  autoscale on queue depth (KEDA); a model registry and versioning; canary a
  new model against the current one on real traffic before promoting.

### 9. IaC and CI/CD
- DONE: GitHub Actions runs tests and builds the image.
- ADD: Terraform for Cloud Run / Memorystore / Secret Manager / monitoring so
  the whole stack is reproducible; canary or blue-green deploys; image scan in
  the pipeline.

## Minimum to call it "production at scale"

If you only add five things, add these:

1. Managed Redis (Memorystore / Upstash) for shared state.
2. Autoscaling with a real load test and documented capacity numbers.
3. OpenTelemetry tracing + Alertmanager alerts on error rate, p99, breaker,
   budget.
4. Secret Manager for provider keys.
5. Async usage events to a warehouse for billing and analytics.

Everything else is depth you add as traffic and team grow.
