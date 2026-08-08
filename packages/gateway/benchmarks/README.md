# benchmarks

Real local benchmark for the tier ladder. Three Ollama models answer a task set,
the strongest one judges, and the harness reports per-tier quality plus the
cost-quality Pareto of the router against edge-only and frontier-only baselines.
No mock providers, no API keys.

```bash
ollama serve
ollama pull llama3.2:1b      # edge
ollama pull gemma4:e2b       # mid
ollama pull qwen2.5-coder:14b # frontier + judge

python run_bench.py
```

Outputs:

- `results.json` — per-task matrix and aggregated strategies.
- `../docs/screenshots/bench-pareto.svg`, `bench-quality.svg` — charts.

## Constrained decoding

`run_constrained_bench.py` runs the strict-JSON extraction set (`tasks_schema.jsonl`)
on the two cheap tiers, free-form vs decoder-constrained to the schema, and
measures validity and tokens for each. It writes `results_constrained.json` and
`../docs/screenshots/constrained-tokens.svg`.

```bash
python run_constrained_bench.py
```

## Judge A/B (independent judge)

`run_judge_ab.py` re-scores the judged tasks with an independent gold judge
(`claude-opus-5`) alongside the local qwen judge, exposing how much a
self-hosted judge inflates its own scores. Needs `ANTHROPIC_API_KEY` in a
gitignored `.env` here. Writes `results_judge_ab.json` and
`../docs/screenshots/judge-ab.svg`.

```bash
echo 'ANTHROPIC_API_KEY=sk-ant-...' > .env
python run_judge_ab.py
```

Findings and analysis for all experiments are in
[`docs/EXPERIMENTS.md`](../../../docs/EXPERIMENTS.md).

`tasks.jsonl` is the task set: easy / medium / hard prompts graded by the judge,
plus strict-JSON extractions graded on validity. Edit it to benchmark your own
traffic; the tier models are set at the top of `run_bench.py`.
