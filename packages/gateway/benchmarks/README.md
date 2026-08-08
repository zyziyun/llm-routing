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

Findings and analysis are in [`docs/EXPERIMENTS.md`](../../../docs/EXPERIMENTS.md).

`tasks.jsonl` is the task set: easy / medium / hard prompts graded by the judge,
plus strict-JSON extractions graded on validity. Edit it to benchmark your own
traffic; the tier models are set at the top of `run_bench.py`.
