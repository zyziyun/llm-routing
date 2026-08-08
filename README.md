# llm-routing

LLM routing across the full **edge↔cloud spectrum**. The same idea — send each
request to the smallest place that can answer it well — in two runtimes that
compose into one system.

| Package | Where it runs | Stack | What it is |
|---|---|---|---|
| [`packages/gateway`](packages/gateway) | Server-side | Python, FastAPI, Redis, k8s | A production LLM gateway: classify → route across tiers → quality-gate → escalate, with per-provider circuit breakers, per-key budgets, an OpenAI-compatible API, and Prometheus metrics. |
| [`packages/edge-client`](packages/edge-client) | On-device (browser) | TypeScript, WebLLM, WebGPU | A router that runs a small model **in the browser**, answers most turns locally, and escalates only the hard ones to the gateway. |

The two halves are one system: the on-device router's escalation backend **is**
the gateway. Run both and the browser answers easy turns locally — nothing
leaves the device — and forwards the hard turns to the deployed gateway.

```
                         ┌─────────────────────── on device (edge-client) ──────────────────────┐
   user ─▶ browser ─▶ classify ─▶ local small model (WebLLM/WebGPU) ─▶ quality gate ─▶ keep local
                                                                              │ (hard / low-conf / invalid)
                                                                              ▼
   ┌───────────────────────────── cloud (gateway) ──────────────────────────────┐
   │ auth ─▶ rate-limit ─▶ budget ─▶ classify ─▶ route (small→cheap→frontier)    │
   │        ─▶ quality gate ─▶ escalate ; circuit breakers ; Redis ; /metrics    │
   └────────────────────────────────────────────────────────────────────────────┘
```

Both ends implement the same three pieces:

- **Routing decision** — classify difficulty, pick a tier.
- **Quality-aware fallback** — accept only if valid and confident, else escalate.
- **Eval** — measure the cost / privacy / quality tradeoff on real cases.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the design and the
tradeoffs, and [`docs/EXPERIMENTS.md`](docs/EXPERIMENTS.md) for the real-model
benchmark: three local models on a cost-quality Pareto, where the router matches
frontier quality at 59% lower cost.

## The edge client, in the browser

The on-device router escalates a hard prompt to the cloud, but strips PII on
device first, so the cloud only sees `[EMAIL]`. The panel tracks local share,
bytes off device, PII kept on device, and cost saved.

![Edge client — on-device PII redaction before escalation](packages/edge-client/docs/screenshots/02-pii-redaction.png)

## The gateway, over HTTP

`bash packages/gateway/demo/live_demo.sh` boots a real uvicorn server and
exercises it end to end: tiered routing on the OpenAI-compatible endpoint, SSE
streaming, auth (401), rate limiting (429), budget caps (402), and a live
Prometheus scrape.

![gateway live HTTP demo](packages/gateway/docs/screenshots/gateway-live-demo.svg)

## Quickstart

```bash
# server-side gateway (Python) — runs offline on mock providers, no keys
cd packages/gateway
pip install -r requirements.lock
PYTHONPATH=src pytest -q                       # 13 tests
PYTHONPATH=src uvicorn gateway.app:app --port 8000

# on-device client (TypeScript) — routing core tests in Node, no browser
cd packages/edge-client
node --test                                    # 8 tests
node eval/run-eval.ts                           # local vs cloud vs router
npm install && npm run dev                      # browser app (WebGPU)
```

Or from the root:

```bash
make test     # both packages
make eval      # both evals
```

## Status

Both packages run and test offline with no API keys and no GPU. The gateway
deploys to Cloud Run or k8s (`packages/gateway/deploy`); the edge client runs a
real model in Chrome/Edge 113+ and degrades gracefully elsewhere. CI runs both
suites, the gateway Docker build, and the edge typecheck on every push.
