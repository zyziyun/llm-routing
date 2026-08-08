# Serve a big open model on RunPod and find the self-host break-even

The point of renting a GPU is a model your Mac can't serve. This runs
`Qwen2.5-72B-Instruct-AWQ` (a frontier-class open model, ~40 GB) and answers the
real serving question: **at what traffic does self-hosting beat calling a hosted
API?**

## 1. Launch a pod

[console.runpod.io](https://console.runpod.io) → **Deploy** → GPU pod:

- GPU: **A100 80GB** (~$1.79-1.99/hr) or **H100 80GB** (~$2.9/hr, faster). 80 GB
  is needed for 72B-AWQ + KV cache.
- Template: **RunPod PyTorch** (any recent CUDA image). Note the pod's $/hr.
- Start it, open the **web terminal** (Connect → Start Web Terminal).

## 2. Serve the model (in the web terminal)

```bash
pip install -q vllm httpx
nohup vllm serve Qwen/Qwen2.5-72B-Instruct-AWQ \
  --quantization awq_marlin --max-model-len 4096 --port 8000 \
  > vllm.log 2>&1 &
# first boot downloads ~40 GB, ~5-10 min. watch it:
tail -f vllm.log   # ctrl-C once you see "Application startup complete"
```

## 3. Run the benchmark

Write the standalone bench (bracket-free base64, so nothing to fetch from the
private repo), set the pod's real GPU price and the hosted price to beat, run it:

```bash
# paste the `echo <base64> | base64 -d > bench.py` line from the chat, then:
GPU_HOURLY=1.99 HOSTED_PRICE_PER_1M=1.10 SERVE_MODEL=Qwen/Qwen2.5-72B-Instruct-AWQ \
  CONCURRENCY=1,2,4,8,16,32 python bench.py
```

- `GPU_HOURLY` = the pod's actual $/hr (from the RunPod card).
- `HOSTED_PRICE_PER_1M` = the API you'd otherwise call, output $/1M (DeepSeek ≈
  $1.10; set to Claude/GPT if comparing to those).

It sweeps concurrency, reports tokens/s, the continuous-batching gain, self-host
`$/1M output`, and the **break-even concurrency** where self-hosting drops below
the hosted price.

## 4. What you're proving

Self-host `$/1M = (GPU $/hr / 3600) / (tokens/s) × 1e6`. Throughput rises with
concurrency, so self-host cost per token falls as the GPU fills. Below the
break-even you're paying for idle silicon and the API is cheaper; above it, self
-hosting a 72B wins. That threshold — not a sticker price — is the real decision,
and it only exists for a model big enough that you'd consider self-hosting.

## 5. Tear down

Stop/terminate the pod as soon as you have the numbers. Idle GPU time is the
cost, not the run.

Send the printed table + the break-even line back; it goes into
`docs/EXPERIMENTS.md` as the serving finding and links the self-host economics to
the hosted-API tiers in `run_hosted_bench.py`.
