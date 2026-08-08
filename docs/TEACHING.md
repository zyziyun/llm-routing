# Teaching guide

How to run this monorepo as a course module. It suits an AI-infra / backend
audience that wants senior-level depth, and it splits cleanly into lessons that
each end in something runnable.

## Learning outcomes

By the end a student can:

1. Explain the edge↔cloud routing spectrum and pick where a given workload
   should sit.
2. Build the three-part routing pipeline: difficulty classification, a
   quality gate, and escalation.
3. Justify why structured-output validity, not preference, is the right gate
   for agent tasks.
4. Deploy a stateless gateway (Cloud Run / k8s) with Redis-shared circuit
   breakers, budgets, and metrics.
5. Run a real small model in the browser and reason about privacy, cost, and
   the WebGPU model lifecycle.
6. Prove tradeoffs with an eval instead of asserting them.

## Suggested lessons

Each lesson = one concept + one runnable artifact in the repo.

1. **The problem and the spectrum.** Read `docs/ARCHITECTURE.md`. Run both
   evals; discuss why "always call the frontier model" is the wrong default.
2. **Routing decision.** `packages/*/…/classifier`. Exercise: add a rule or an
   embedding-based classifier; measure how routing accuracy changes.
3. **Quality gate.** `gate.ts` / `gate.py`. Exercise: add a JSON-schema case
   that the small tier fails; watch it escalate. Discuss preference vs
   validity.
4. **Server-side gateway.** `packages/gateway`. Bring it up, hit
   `/v1/chat/completions`, read `/metrics`. Exercise: trip a circuit breaker
   and observe reliability escalation (distinct from quality escalation).
5. **On-device router.** `packages/edge-client`. Run the browser demo on
   WebGPU; watch the "bytes that left the device" stay at zero for easy turns.
   Exercise: lower the confidence threshold and watch the local share rise and
   quality fall.
6. **Composition.** Point the edge client's cloud tier at the running gateway.
   Trace one hard request from browser classify → gateway route → frontier.
7. **Scale and ops.** `packages/gateway/deploy/SCALE.md`. Exercise: add one of
   the five "minimum for production" items (managed Redis, tracing + alerts,
   async usage to a warehouse, secrets manager, or a load test).
8. **Deploy.** `packages/gateway/deploy/DEPLOY.md`. Ship the gateway to Cloud
   Run; host the edge client as static files.

## Exercises with a grading rubric

Give students the repo with a tier disabled or a gate weakened, and have them
restore or improve it. Grade on:

| Dimension | What to look for |
|---|---|
| Routing correctness | easy stays cheap/local; hard escalates; no wasted attempts |
| Gate design | validity + confidence, not just error handling; escalation reasons are specific |
| Reliability | breaker / local-failure paths handled; escalation is honest about cost |
| Eval | measures the right axis (validity, privacy, cost), reproducible |
| Ops (gateway) | health/readiness, metrics, shared state correct across workers |
| Writeup | can defend one tradeoff in prose (a design doc), not just code |

## Talking points that show depth

- Why preference-trained routers (RouteLLM) miss structured-output validity.
- Uncertainty-aware escalation: logprob confidence, schema, refusal, context.
- Reliability routing (circuit breaker) vs intelligence routing (quality gate)
  are different and coexist.
- Privacy as a measured quantity on the client; no provider keys in the
  browser; the gateway as the key-holding escalation backend.
- The cost counterfactual and why escalation is not free.

## What each package proves it can run

- `gateway`: `PYTHONPATH=src pytest -q` (13 tests), `uvicorn gateway.app:app`,
  `python eval/run_eval.py`.
- `edge-client`: `node --test` (8 tests), `node eval/run-eval.ts`,
  `npm run dev` for the browser demo.

All offline, no API keys, no GPU required for the tests and evals.
