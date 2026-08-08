# Architecture: the edge↔cloud routing spectrum

Both packages solve the same problem — *send each request to the smallest
place that can answer it well* — but at opposite ends of a spectrum. This doc
is the senior-level view that ties them together.

## The spectrum

```
 more local / private / cheap                         more capable / expensive
 ├──────────────┬───────────────────┬───────────────────┬────────────────────┤
 on-device SLM   small self-hosted    cheap hosted API     frontier hosted API
 (edge-client)   (gateway EDGE tier)  (gateway CHEAP)      (gateway FRONTIER)
```

- **edge-client** owns the leftmost hop: a small model in the browser. It
  decides, on device, whether it can answer. If yes, the request never leaves
  the machine.
- **gateway** owns everything to the right: once a request is in the cloud, it
  routes across a small self-hosted model, a cheap hosted model, and a frontier
  model, escalating on quality.

Composed, a request walks left-to-right and stops at the first tier that
clears the quality gate.

## Two topologies of "edge routing"

The word "edge" is overloaded. Be explicit.

1. **Server-side gateway (gateway package).** The router is a backend service.
   Its "edge" tier is a small, cheap, self-hosted model that runs server-side.
   It is "edge" only in the sense of small/cheap. This is the LiteLLM /
   Portkey / OpenRouter shape and the backend-engineer's project.
2. **Client-side / on-device (edge-client package).** The router logic AND the
   model run on the client. The device answers most turns with zero network
   hop; the cloud sees only the escalated minority. Purest privacy and latency,
   but the client half is frontend / mobile / edge-ML work.

They compose: topology 2 uses a deployment of topology 1 as its escalation
backend. That composition is the whole monorepo.

## The three shared ideas

Both packages implement the same pipeline; only the runtime differs.

| Idea | gateway (server) | edge-client (browser) |
|---|---|---|
| Routing decision | difficulty classifier picks a starting tier | classifier decides local vs straight-to-cloud |
| Quality-aware fallback | schema + confidence gate; escalate up tiers | schema + confidence + refusal + context gate; escalate to cloud |
| Reliability | per-provider circuit breaker + timeouts | local engine failure / no-WebGPU → escalate |
| Eval | router vs always-frontier: cost, latency, validity | local-only vs cloud-only vs router: privacy, cost, quality |

The key correctness lesson, identical on both ends: for structured/agent
tasks, gate on **structured-output validity**, not on preference. Small models
(local or cheap) botch strict JSON; the gate catches it and escalates.

## Senior-depth points worth teaching

- **Uncertainty-aware escalation.** Escalate on low token-logprob confidence,
  schema-invalid output, refusal, or context overflow — not just on errors.
- **Privacy is a first-class metric.** edge-client counts bytes that leave the
  device. For every locally answered turn that number is zero. This is the
  headline the on-device topology buys you.
- **No secrets in the browser.** Anything shipped to the client is public, so
  the edge client holds no provider keys. Its cloud tier calls the gateway,
  which holds keys and enforces auth, budgets, and rate limits. This is why the
  two packages need each other.
- **Cost is a counterfactual.** Both evals compare against "always use the
  strong model" to make the savings legible, and both charge escalation
  honestly (it is not free — cost and latency accrue across attempts).
- **Model lifecycle on the edge.** WebGPU feature detection, one-time weight
  download with progress, browser caching, and graceful degradation when the
  device cannot run a model. These are the real-world edges of "just run it
  locally."
- **Where routing lives changes the threat model and the ops model.** On the
  server you scale workers and share state in Redis; on the client you have N
  heterogeneous devices, no shared state, and privacy by construction.

## Extensions (good student projects)

- Speculative / draft-verify: local model drafts, cloud verifies only when the
  draft is uncertain.
- Semantic cache shared across the two tiers.
- A learned difficulty router trained on your own traffic, evaluated on
  structured-output validity rather than preference.
- Per-tenant budgets and usage analytics streamed to a warehouse (gateway
  `deploy/SCALE.md`).
