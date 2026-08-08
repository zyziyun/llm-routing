# Experiments: real local models

Everything below is real inference. Three models served by Ollama form the tier
ladder, a fourth acts as an LLM judge, and the numbers come from running the
`benchmarks/tasks.jsonl` set through each tier. No mock providers, no API keys,
no synthetic scores.

```bash
ollama serve
cd packages/gateway && python benchmarks/run_bench.py
```

Hardware: Apple M5, 32 GB. Reproduce with `benchmarks/run_bench.py`; raw
per-task numbers are in `benchmarks/results.json`.

## Setup

| Tier | Model | Size | Equivalent hosted price |
|---|---|---|---|
| edge | `llama3.2:1b` | 1.3 GB | $0.0001 / 1K tok |
| mid | `gemma4:e2b` | 7.2 GB | $0.0006 / 1K tok |
| frontier | `qwen2.5-coder:14b` | 9.0 GB | $0.01 / 1K tok |

The judge is `qwen2.5-coder:14b`, scoring each answer 0 to 1 for correctness and
relevance. Schema tasks are graded on strict JSON validity instead of the judge.
The task set is 12 prompts: 4 easy, 3 medium, 3 hard, 2 strict-JSON extractions.
Cost is the equivalent hosted spend, so local free inference still has a
meaningful cost axis to route against.

## Per-tier results

![judge quality by tier](../packages/gateway/docs/screenshots/bench-quality.svg)

| Tier | Judge quality | Avg latency | Avg tokens |
|---|---|---|---|
| edge (1b) | 0.69 | 2.7 s | 153 |
| mid (2b) | 0.42 | 6.8 s | 251 |
| frontier (14b) | 0.90 | 9.3 s | 160 |

> These quality numbers are self-scored by the frontier model and run high.
> Experiment 3 measures the bias and Experiment 4 re-runs under an independent
> judge (edge falls to 0.43, frontier to 0.79). The ordering here holds; the
> levels are optimistic. Read the absolute numbers as a lenient upper bound.

## Finding 1: the ladder is not monotonic

The mid tier scores **below** the smaller edge tier on this set, 0.42 against
0.69. Two real causes show up in the raw numbers: the 2B model is the most
verbose of the three at 251 tokens per answer, and on several medium tasks it
padded a wrong or off-topic answer that the strict judge scored near zero, while
the 1B model gave a short correct one.

The lesson holds beyond these two models: a tier ladder has to be measured, not
assumed. Dropping a model in between two others because it is nominally bigger
is not guaranteed to buy quality, and here it buys latency and tokens for a
quality loss. A router that trusts model size as a proxy for capability would
route straight into the weakest tier.

## Finding 2: the router matches frontier quality at a fraction of the cost

Walking the ladder small to large and stopping at the first answer that clears a
confidence bar, swept across thresholds:

![cost vs quality](../packages/gateway/docs/screenshots/bench-pareto.svg)

| Strategy | Quality | Cost $/req | Avg latency |
|---|---|---|---|
| edge-only | 0.69 | 0.00018 | 2.7 s |
| frontier-only | 0.90 | 0.01925 | 9.3 s |
| router @0.5 | 0.78 | 0.00141 | 4.4 s |
| **router @0.6** | **0.90** | **0.00784** | 9.2 s |
| router @0.9 | 0.90 | 0.01103 | 11.4 s |

At threshold 0.6 the router **matches frontier quality (0.90) at 59% lower
cost**. Its tier mix is 7 edge, 2 mid, 3 frontier: two thirds of the traffic
never touches the expensive model, and the hard third that does is exactly the
third the frontier is needed for.

## Finding 3: escalation trades latency for cost, not against it

The router is not a latency win here, and the honest chart shows it. Because a
miss on a cheap tier is discovered only after that tier answers, escalation runs
tiers in sequence and their latencies add up. Router @0.6 sits near frontier
latency while paying far less. The gate is a cost and quality instrument; when
latency is the priority the same confidence dial should be lowered so fewer
requests pay the sequential penalty, or the tiers should run speculatively in
parallel.

## Finding 4: strict JSON is a real failure mode, including on the frontier

On the two extraction tasks, the edge model produced invalid or wrong-shaped
JSON on both. The frontier model passed one and still failed the other by
renaming a required field. This is not a small-model quirk; it is why the gate
treats schema validity as a first-class accept condition and why
`CONSTRAINED_DECODING` exists. A model that is smart enough to extract the values
can still emit a structure the caller cannot parse, and only decoding-level
constraints remove that failure mode rather than hoping the model complies.

## Experiment 2: constrained decoding on real small models

`benchmarks/run_constrained_bench.py` runs 10 strict-JSON extraction tasks on the
two cheap tiers twice: once free-form, once with the decoder constrained to the
task's JSON Schema through Ollama's OpenAI-compatible `response_format`, the
local-tier analogue of Outlines or XGrammar. Both conditions ask for JSON in the
prompt, so the only variable is the decoder constraint. Validity is strict: parse
must succeed, every required key present, every value the right type.

The first pass looked like a landslide for constraints, 0% free-form to 40%. It
was an artifact. At a 200-token cap the verbose free-form answers were truncated
mid-object and scored invalid. That is a token-budget confound, not a structure
failure, so the budget was raised to 400 and the run repeated. The honest result:

![tokens per answer, free vs constrained](../packages/gateway/docs/screenshots/constrained-tokens.svg)

| Tier | Free-form valid | Constrained valid | Avg tokens free | Avg tokens constrained |
|---|---|---|---|---|
| edge (1b) | 100% | 100% | 27 | 23 |
| mid (2b) | 100% | 100% | 266 | 24 |

Two findings, neither the one the naive run suggested.

**Validity is not where constraint pays off here.** Given a clear instruction and
enough tokens, both the 1B and the 2B model already emit strict-valid JSON on
every task. Constrained decoding removes zero validity-caused escalations on this
set. Instruction following, not decoding, carried simple single-object
extraction.

**Output discipline is where it pays off.** The 2B model free-form averages 266
completion tokens per answer, wrapping every result in markdown fences and a
preamble, against 24 constrained: **11x fewer tokens for the same valid JSON**.
The 1B model is already terse, 27 to 23. That verbosity is a real failure mode,
not a cosmetic one: it is exactly what truncated the first run under a normal
token cap and turned valid content into invalid output. Constrained decoding
makes small-model structured output compact, deterministic, and truncation-proof,
which is a cost, latency, and reliability win at once.

The honest caveat: these schemas are shallow. Constraint's validity benefit grows
with nested objects, enums, and arrays, and with weaker instruction following. On
flat two-field extractions a good prompt is enough for validity, and the win is
the 11x token collapse.

## Experiment 3: is the judge biased toward its own tier?

Experiment 1 used `qwen2.5-coder:14b` as both the frontier tier and the judge. A
model scoring its own outputs is a known bias, so it needs checking rather than
assuming. `benchmarks/run_judge_ab.py` re-scores the same answers with an
independent gold judge, `claude-opus-5`, and compares the two judges tier by
tier. Requires an `ANTHROPIC_API_KEY` in `packages/gateway/.env`.

![local self-judge vs independent Claude](../packages/gateway/docs/screenshots/judge-ab.svg)

| Tier | qwen (self-judge) | Opus 5 (independent) | inflation |
|---|---|---|---|
| edge (1b) | 0.87 | 0.58 | +0.29 |
| mid (2b) | 0.35 | 0.34 | +0.01 |
| frontier (14b) | 0.96 | 0.85 | +0.11 |

Overall the local judge scores **0.14 higher** than the independent one, and the
two judges correlate at **r = 0.86**.

**The ordering holds; the absolute numbers were optimistic.** An r of 0.86 means
the two judges rank answers the same way, so Experiment 1's *shape* stands: the
tier ladder and the router's cost-quality frontier don't move. What moves is the
level. Every tier's quality in Experiment 1 was inflated by a lenient judge.

**Self-preference is real but not the main bias.** The naive worry is that qwen
flatters its own frontier outputs, and it does, by +0.11. But that is the
*second* largest distortion. The largest is leniency toward the **weakest** tier:
qwen overrates the 1B edge model by +0.29, most of it on the hard tasks, where it
scored a garbled irrationality proof 0.90 that the gold judge scored 0.05. The
mid tier shows almost no gap because it mostly failed outright and both judges
agree on a failure. So the honest correction is not "discount the frontier" but
"the cheap tier is worse than a self-hosted judge reports," which **widens** the
real edge-to-frontier gap (0.58 vs 0.85) and makes the case for escalating hard
turns stronger, not weaker.

The methodological takeaway: a local judge is fine for *relative* routing
decisions, since it preserves order, but absolute quality claims need an
independent judge. A self-hosted eval loop should treat its own scores as a
lenient upper bound.

## Experiment 4: real edge-to-cloud escalation across providers

Experiments 1-3 are all local. This one adds the boundary the whole repo is
about: local small models that escalate to **real hosted frontiers**.
`benchmarks/run_hosted_bench.py` runs a four-tier ladder across three providers
and judges everything with the independent `claude-opus-5` gold judge (so these
numbers already carry Experiment 3's correction, not the self-judge's leniency).

| Tier | Model | Provider | Gold quality | Cost / 12 tasks |
|---|---|---|---|---|
| edge | `llama3.2:1b` | Ollama (local) | 0.43 | $0.0002 |
| local-frontier | `qwen2.5-coder:14b` | Ollama (local) | 0.79 | $0.018 |
| cloud:sonnet | `claude-sonnet-5` | Anthropic | 0.83 | $0.043 |
| cloud:gpt5 | `gpt-5` | OpenAI | 0.75 | $0.069 |

Local prices are equivalent-hosted estimates; cloud prices are real published
rates (input/output priced separately). The judge is never a tier, so there is
no self-scoring bias.

![edge to cloud cost vs quality](../packages/gateway/docs/screenshots/hosted-pareto.svg)

**The gold judge confirms Experiment 1 was optimistic.** Under the independent
judge the local tiers drop hard: edge from 0.69 to 0.43, local-frontier (the
same qwen model) from 0.90 to 0.79. Experiment 1's ordering held, but its
absolute quality was inflated by the self-judge, exactly as Experiment 3
predicted. Trust the numbers in this table over Experiment 1's.

**The router auto-selects the cloud, and that is the whole point.** Nothing is
pinned to one cloud model. The router walks a cost-ordered chain and the quality
gate picks whichever tier first clears the bar; at the cloud step it chooses
across providers on its own. That is what lets the server-side router run
autonomously: at threshold 0.9 it kept 8 of 12 tasks on local models and
escalated only the 4 hardest, and the cloud pick was made by the gate, not by a
human.

**But escalating through two clouds in series is a cost trap.** The obvious
autonomous design tries each cloud in turn until one passes. It works on quality
(0.85) but costs $0.079 — *more* than just calling `claude-sonnet-5` directly
($0.043, 0.83). Two reasons, both real: a miss on the first cloud still bills it
before the second runs, and static input-price ordering put `gpt-5` first, which
on this set was both pricier (reasoning tokens inflate its output bill) and lower
quality. Speculative escalation pays off among cheap local tiers (Experiment 1);
among expensive clouds it loses.

| Strategy | Quality | Cost / 12 | vs sonnet-only |
|---|---|---|---|
| cloud-only:sonnet | 0.83 | $0.043 | baseline |
| router-2cloud @0.9 (try both clouds) | 0.85 | $0.079 | +84% cost |
| **router-1cloud @0.9 (select one cloud)** | **0.84** | **$0.037** | **-13% cost** |
| router-1cloud @0.7 | 0.83 | $0.029 | **-31% cost** |

**The fix is to select one cloud, not try several.** A router that escalates to a
single chosen cloud beats always-cloud by 13% at equal-or-better quality, and by
31% at the same quality as sonnet-only, while still keeping two thirds of traffic
local. The design rule: the cloud tier should be *routed to* (predict the best
single provider), not *walked* — and it should be ordered by measured effective
cost, not static list price, since a reasoning model's token bill is only visible
after the fact.

## What this validates

- SLM-first with an escalation gate is not a story, it reproduces on real
  models: most traffic stays cheap and the expensive tier is spent only where it
  changes the answer.
- The confidence threshold is the one dial. Sweeping it traces the cost-quality
  frontier directly, and 0.6 is the knee for this workload.
- Capability is not size. The ladder must be validated per workload, which is
  what this harness is for.
