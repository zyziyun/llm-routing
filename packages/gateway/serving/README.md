# serving

Self-host an open model with vLLM and measure the two things a hosted API hides:
**continuous-batching throughput** and **real cost-per-token**. This is the
serving counterpart to `benchmarks/` — those route across models; this one runs
the GPU itself.

Why bother when `benchmarks/run_hosted_bench.py` already routes to a hosted open
model (DeepSeek)? Because serving is a different lesson. Calling an API gives you
a price and a latency; serving gives you the levers behind them — batch size, KV
cache, quantization, GPU utilization — and lets you compute what a token *costs*
rather than what a vendor *charges*.

## Run it

1. Bring up an OpenAI-compatible vLLM endpoint. Easiest on Colab Pro/Pro+ (L4):
   follow [`COLAB.md`](COLAB.md). Or a per-hour GPU (RunPod/Vast) with the same
   `vllm serve` command.
2. Point the benchmark at it and give the GPU's hourly rate:

```bash
export SERVE_BASE_URL=https://<tunnel>.ngrok.app/v1   # or http://localhost:8000/v1
export SERVE_MODEL=Qwen/Qwen2.5-7B-Instruct
export GPU_HOURLY=0.34        # the GPU's real $/hr
python serving/bench_serving.py
```

It sweeps concurrency (1,2,4,8,16), reports tokens/s, req/s, the
continuous-batching gain over concurrency 1, and `$/1M output tokens =
(GPU $/hr / 3600) / (tokens/s)`. Writes `results_serving.json` and
`../docs/screenshots/serving-throughput.svg`.

Works against any OpenAI-compatible endpoint, so you can dry-run it against a
local Ollama (`SERVE_BASE_URL=http://localhost:11434/v1`, `SERVE_MODEL=llama3.2:1b`)
before spending on a GPU.

## Picking a platform (cheap-first)

| Platform | Use it for | Rough cost |
|---|---|---|
| Colab Pro/Pro+ (L4) | serve + measure throughput; within your subscription | compute units (L4 cheap, A100 pricey) |
| RunPod Community/Serverless | hard $/GPU-hr numbers; scale-to-zero | 4090 ~$0.34/hr |
| Vast.ai | absolute cheapest, tolerate variance | 4090 ~$0.29-0.39/hr |

Colab bills compute units, not GPU $/hr, so its `$/token` is an estimate. For a
defensible cost-per-token figure, run the same benchmark on a per-hour GPU.

## Wiring the served model into the router

The vLLM endpoint is OpenAI-compatible, so it drops into the router as a tier:
add a row to `benchmarks/run_hosted_bench.py` `TIERS` with an `openai`-kind entry
whose calls target `SERVE_BASE_URL`, or set the gateway's `OPENAI_BASE_URL` to the
tunnel. That turns "a model I serve myself" into a first-class routing tier next
to edge and the hosted clouds.

## Guardrails

- Prefer a small model (7-8B, or 14B AWQ 4-bit) so it fits a cheap 24 GB card.
- Use scale-to-zero (RunPod serverless) or tear the pod down when done; idle GPU
  time is where the money goes, not the per-hour rate.
- Cap the run (`REQS_PER_LEVEL`, `MAX_TOKENS`) — a full sweep is a few dozen short
  requests and costs cents.
