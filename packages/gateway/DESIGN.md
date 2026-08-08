# Design notes

This is the document to read before defending the project in an interview.
It states the business context, the architecture, and the tradeoffs that
were deliberate.

## 1. Business context

A product team runs a lot of LLM calls. The bill grows with traffic, and the
naive fix, downgrading everyone to a cheap model, hurts quality on the hard
requests. The team wants to cut inference cost without dropping below a
quality bar, and to keep serving when a provider has an outage.

- **User:** the platform or product team behind an LLM feature.
- **Pain:** cost scales with traffic; blanket downgrade hurts quality; single
  provider is a reliability risk.
- **Why a service, not a config:** the routing decision is per-request and
  quality-aware. A static "use model X" config cannot tell an easy request
  from a hard one, and cannot notice that a cheap model just returned invalid
  JSON. That judgement is the product.

This is a real 2026 problem: frontier capex and per-token prices are high,
and "route by difficulty" is now a standard cost lever.

## 1a. Where does the router run? Two topologies

"Edge LLM routing" is used two ways. Be explicit about which you mean.

1. **Server-side gateway (this repo).** The router is a backend service. The
   "edge" tier is a small, cheap, *self-hosted* model that runs server-side,
   next to the gateway: same host, a sidecar, or a GPU pool. It is "edge" only
   in the sense of small and cheap, not literally on the user's device. When
   the gateway runs in the cloud, that model is NOT on the client. This is the
   LiteLLM / Portkey / OpenRouter shape and the one that fits a backend
   engineer.

2. **Client-side / on-device router.** The router logic AND the small model
   run ON the client: a phone, a desktop app, or the browser via WebLLM/WASM.
   The device answers 80-90% locally with no network hop and only escalates
   the hard turns to a cloud gateway. This is the purest "edge," best for
   privacy and latency, but the client half is mobile/frontend/edge-ML work,
   and the cloud only sees the escalated minority.

They compose: an on-device router (topology 2) can use a deployment of this
gateway (topology 1) as its escalation backend.

**This repo is topology 1.** Read the EDGE tier as "small / self-hosted," not
"on the user's device." The `Tier.EDGE` name is kept for brevity.

## 2. Gateway vs router, and why this is both

The industry splits these:

- A **gateway** (LiteLLM, Portkey) is the body: one API over many providers,
  with fallback, retries, caching, budgets, observability. It is about
  *availability*, not model-selection intelligence.
- A **router** (RouteLLM) is the brain: it decides *which* model a request
  should use, usually by predicted difficulty.

Most production stacks want both. This lab is a compact version of both: the
gateway plumbing (tiers, cache, fallback, cost accounting) plus the router
brain (classify, quality-gated escalation).

## 3. Request lifecycle

```
cache  ->  classify  ->  route (SLM-first)  ->  quality gate  ->  escalate
```

1. **Cache first.** A hit skips every model call, so it is the cheapest
   outcome and must come before routing. Exact-hash by default; embedding
   similarity optional so paraphrases hit too.
2. **Classify.** Estimate difficulty; this only picks the *starting* tier.
3. **Route SLM-first.** Walk the ladder `EDGE -> CHEAP -> FRONTIER` from the
   start tier upward.
4. **Quality gate.** Accept a reply only if it validates and clears the
   confidence bar; otherwise escalate.

## 4. The quality gate is the point

Two escalation triggers, straight from the on-device routing literature:

- **Structured-output validity.** If the request demands JSON, the reply must
  parse and satisfy the schema. This is deliberately the primary gate,
  because **preference-trained routers like RouteLLM do not capture it**.
  They are calibrated on human preference between open-ended answers, not on
  whether a tool call or JSON extraction actually succeeds. For agent work,
  validate structured-output validity on your own task types, not MT-Bench.
- **Confidence bar.** A low-confidence reply, especially from the on-device
  model, is bumped up a tier. This is "uncertainty-aware escalation."

An optional third stage runs an LLM-as-judge on non-schema tasks, scoring the
answer with the frontier model. Off by default so the lab needs no keys; for
RAG tasks, swap in RAGAS-style faithfulness and answer-relevance.

## 5. Tradeoffs worth defending

- **Escalation is not free.** Cost and latency accrue across every attempt.
  A request that walks `edge -> cheap -> frontier` costs more and is slower
  than going straight to frontier. The router only wins because most traffic
  stops early. The eval measures this honestly, including the tier mix.
- **One dial.** `CONFIDENCE_THRESHOLD` is the whole cost/quality tradeoff.
  Keeping it a single, named number makes the behavior explainable and
  tunable, instead of scattering magic constants.
- **Mock-first design.** Providers sit behind one interface, and the default
  mock backend makes the router deterministic and testable with no keys. The
  same interface hosts Ollama and OpenAI-compatible backends. This is what
  lets the eval be reproducible and the tests run in CI.
- **Classifier can be wrong, and that is OK.** It only chooses the starting
  tier. The gate is the real correctness mechanism: a misclassified hard
  request that starts too low simply escalates. Cheap insurance.
- **Reliability routing vs intelligence routing are different.** Fallback on
  provider error is about availability; escalation on low quality is about
  model selection. This lab does both but keeps them conceptually separate in
  the gate and the ladder.

## 6. What to build next

- Real embedding classifier and semantic cache.
- Per-tenant budgets and rate limits (the multi-tenant business context).
- Circuit breaker per provider for the reliability business context.
- Train a small difficulty predictor on your own traffic and compare its
  routing accuracy on structured-output validity, not just preference.
