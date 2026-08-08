# Serve an open model on Colab (Pro / Pro+) and route to it

Paste these cells into a Colab notebook. Pick an **L4** GPU (Runtime → Change
runtime type → L4): 24 GB, supports bf16, low compute-unit burn. On **Pro+**
turn on **background execution** so the server and tunnel survive after you close
the tab.

This gives you an OpenAI-compatible vLLM endpoint reachable from anywhere (your
M5, the router harness), so a self-hosted open model becomes just another tier.

## Cell 1 — install

```python
!pip install -q vllm pyngrok
```

## Cell 2 — start vLLM (OpenAI-compatible server) in the background

`Qwen/Qwen2.5-7B-Instruct` in bf16 fits L4 (24 GB) with room for the KV cache.
For a bigger model use an AWQ 4-bit build (e.g. `Qwen/Qwen2.5-14B-Instruct-AWQ`).

```python
import subprocess, time
server = subprocess.Popen([
    "vllm", "serve", "Qwen/Qwen2.5-7B-Instruct",
    "--dtype", "bfloat16",
    "--max-model-len", "4096",
    "--port", "8000",
])
# wait for the server to come up (first boot downloads weights, ~2-4 min)
import urllib.request
for _ in range(120):
    try:
        urllib.request.urlopen("http://localhost:8000/v1/models"); print("up"); break
    except Exception:
        time.sleep(5)
```

## Cell 3 — open a public tunnel

```python
from pyngrok import ngrok
ngrok.set_auth_token("PASTE_YOUR_NGROK_TOKEN")   # free at dashboard.ngrok.com
url = ngrok.connect(8000).public_url
print("BASE_URL:", url + "/v1")   # <- use this as SERVE_BASE_URL
```

## Cell 4 — sanity check

```python
import httpx
r = httpx.post(url + "/v1/chat/completions",
    json={"model": "Qwen/Qwen2.5-7B-Instruct",
          "messages": [{"role": "user", "content": "Reply with the single word OK."}],
          "max_tokens": 8}, timeout=120)
print(r.json()["choices"][0]["message"]["content"])
```

## Cell 5 — (optional) run the serving benchmark inside Colab

```python
!git clone https://github.com/zyziyun/llm-routing.git
%cd llm-routing/packages/gateway
import os
os.environ["SERVE_BASE_URL"] = url + "/v1"
os.environ["SERVE_MODEL"] = "Qwen/Qwen2.5-7B-Instruct"
os.environ["GPU_HOURLY"] = "0.80"   # see README: L4-equivalent $/hr for real $/token
!python serving/bench_serving.py
```

## From your laptop instead

Once Cell 3 prints the URL, you can drive it from the M5 without running anything
else in Colab:

```bash
export SERVE_BASE_URL=https://<tunnel>.ngrok.app/v1
export SERVE_MODEL=Qwen/Qwen2.5-7B-Instruct
export GPU_HOURLY=0.80
python serving/bench_serving.py
```

Or plug it into the router as a real self-hosted tier — it is OpenAI-compatible,
so point an `openai`-kind tier's base URL at the tunnel (see `serving/README.md`).

## Notes

- **Keep Cell 2 running.** The server dies with the runtime. Pro+ background
  execution keeps it alive ~24 h; free/Pro sessions time out sooner.
- **Compute units:** L4 burns few units/hr; A100 burns many. Prefer L4 unless a
  model needs more than 24 GB.
- **True $/token:** Colab bills compute units, not GPU $/hr, so `GPU_HOURLY` here
  is an estimate for the cost math. For a hard cost-per-token number, run the same
  benchmark on a per-hour GPU (RunPod) — see `serving/README.md`.
