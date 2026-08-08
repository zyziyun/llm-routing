# llm-routing

A teaching monorepo for **LLM routing across the full edge↔cloud spectrum**.
Same idea in two topologies, built to run, deploy, and teach:

| Package | Topology | Stack | What it is |
|---|---|---|---|
| [`packages/gateway`](packages/gateway) | Server-side gateway | Python, FastAPI, Redis, k8s | A production LLM gateway: classify → route across tiers → quality-gate → escalate, with circuit breakers, budgets, metrics, OpenAI-compatible API. |
| [`packages/edge-client`](packages/edge-client) | On-device / client-side | TypeScript, WebLLM, WebGPU | A router that runs a small model **in the browser**, keeps most turns local, and escalates only the hard ones to the gateway. |

They are one system: the on-device router's escalation backend **is** the
gateway. Run both and the browser answers easy turns locally (nothing leaves
the device) and forwards hard turns to your deployed gateway.

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

## Why one repo

The two halves teach the same three ideas from opposite ends, so seeing them
together is the lesson:

- **AI routing decision** — classify difficulty, pick a tier.
- **Quality-aware fallback** — accept only if valid + confident, else escalate.
- **Eval as output** — prove cost / privacy / quality tradeoffs on real cases.

Read [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the spectrum and the
tradeoffs, and [`docs/TEACHING.md`](docs/TEACHING.md) for the course built on
top of both.

## Quickstart

```bash
# 1. server-side gateway (Python) — runs offline on mock providers
cd packages/gateway
PYTHONPATH=src python -m pytest -q            # 13 tests
PYTHONPATH=src uvicorn gateway.app:app --port 8000

# 2. on-device client (TypeScript) — routing brain tests in Node, no browser
cd packages/edge-client
node --test                                   # 8 tests
node eval/run-eval.ts                          # local vs cloud vs router
npm install && npm run dev                     # full browser demo (WebGPU)
```

Or from the root:

```bash
make test     # runs both packages' tests
make eval      # runs both evals
```

## Status

Both packages run and are tested offline with no API keys and no GPU. The
gateway deploys to Cloud Run / k8s (`packages/gateway/deploy`); the edge client
runs a real model in Chrome/Edge 113+ and degrades gracefully elsewhere.
