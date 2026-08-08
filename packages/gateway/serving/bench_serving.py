"""Serving benchmark: measure what you only get by running the GPU yourself --
continuous-batching throughput and real cost-per-token.

Calling a hosted API (DeepSeek, Claude) hides the serving economics. When you
serve an open model with vLLM, the interesting numbers are: how much throughput
continuous batching buys as concurrency rises, and what a token actually costs
given the GPU's hourly rate. This hits any OpenAI-compatible endpoint (your vLLM
server on Colab/RunPod, or even Ollama for a dry run) and reports both.

    # point at the vLLM server (the ngrok URL from the Colab notebook, or local)
    export SERVE_BASE_URL=https://<your-tunnel>.ngrok.app/v1
    export SERVE_MODEL=Qwen/Qwen2.5-7B-Instruct
    export GPU_HOURLY=0.34          # the GPU's $/hr (RunPod 4090 ~0.34; see README for Colab)
    python serving/bench_serving.py

No API key needed for a local/self-hosted vLLM; set SERVE_API_KEY if the endpoint
requires one.
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
SHOTS = HERE.parent / "docs" / "screenshots"
BASE = os.environ.get("SERVE_BASE_URL", "http://localhost:8000/v1").rstrip("/")
MODEL = os.environ.get("SERVE_MODEL", "Qwen/Qwen2.5-7B-Instruct")
API_KEY = os.environ.get("SERVE_API_KEY", "not-needed")
GPU_HOURLY = float(os.environ.get("GPU_HOURLY", "0.34"))  # $/hr of the GPU you're serving on
CONCURRENCY = [int(c) for c in os.environ.get("CONCURRENCY", "1,2,4,8,16").split(",")]
REQS_PER_LEVEL = int(os.environ.get("REQS_PER_LEVEL", "24"))
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "128"))
PROMPT = ("Write a clear, self-contained paragraph explaining how a CPU cache "
          "improves performance. Be concrete.")


def _headers() -> dict:
    return {"Authorization": f"Bearer {API_KEY}", "content-type": "application/json"}


def one_request(client: httpx.Client) -> int:
    """Send one non-streaming completion, return output-token count."""
    r = client.post(f"{BASE}/chat/completions", headers=_headers(),
                    json={"model": MODEL, "messages": [{"role": "user", "content": PROMPT}],
                          "max_tokens": MAX_TOKENS, "temperature": 0.2}, timeout=300.0)
    r.raise_for_status()
    return r.json().get("usage", {}).get("completion_tokens", 0)


def ttft_ms() -> float:
    """Time to first streamed token at concurrency 1."""
    t0 = time.time()
    with httpx.Client(timeout=300.0) as c:
        with c.stream("POST", f"{BASE}/chat/completions", headers=_headers(),
                      json={"model": MODEL, "messages": [{"role": "user", "content": PROMPT}],
                            "max_tokens": MAX_TOKENS, "temperature": 0.2, "stream": True}) as s:
            for line in s.iter_lines():
                if line and line.strip() not in ("data: [DONE]", ""):
                    return round((time.time() - t0) * 1000, 1)
    return -1.0


def run_level(concurrency: int) -> dict:
    q: queue.Queue[int] = queue.Queue()
    for _ in range(REQS_PER_LEVEL):
        q.put(1)
    out_tokens = [0]
    lock = threading.Lock()

    def worker():
        with httpx.Client() as client:
            while True:
                try:
                    q.get_nowait()
                except queue.Empty:
                    return
                n = one_request(client)
                with lock:
                    out_tokens[0] += n

    t0 = time.time()
    threads = [threading.Thread(target=worker) for _ in range(concurrency)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = time.time() - t0
    tok_s = out_tokens[0] / wall if wall else 0.0
    req_s = REQS_PER_LEVEL / wall if wall else 0.0
    # cost per 1M output tokens = (GPU $/sec) / (output tok/sec) * 1e6
    cost_per_1m = (GPU_HOURLY / 3600) / tok_s * 1e6 if tok_s else 0.0
    return {"concurrency": concurrency, "wall_s": round(wall, 2),
            "output_tokens": out_tokens[0], "tok_per_s": round(tok_s, 1),
            "req_per_s": round(req_s, 2), "cost_per_1m_out": round(cost_per_1m, 4)}


def main() -> None:
    print(f"serving benchmark: {MODEL} @ {BASE}  (GPU ${GPU_HOURLY}/hr)")
    # warm up + single-request latency / TTFT
    with httpx.Client() as c:
        t0 = time.time(); one_request(c); warm_ms = round((time.time() - t0) * 1000, 1)
    first_token = ttft_ms()
    print(f"  single-request latency {warm_ms:.0f}ms, TTFT {first_token:.0f}ms\n")

    rows = [run_level(c) for c in CONCURRENCY]
    base_tok = rows[0]["tok_per_s"] or 1.0
    for r in rows:
        r["batching_gain"] = round(r["tok_per_s"] / base_tok, 2)

    results = {"model": MODEL, "base_url": BASE, "gpu_hourly": GPU_HOURLY,
               "max_tokens": MAX_TOKENS, "reqs_per_level": REQS_PER_LEVEL,
               "single_latency_ms": warm_ms, "ttft_ms": first_token, "levels": rows}
    (HERE / "results_serving.json").write_text(json.dumps(results, indent=2))
    _chart(rows)

    print(f"  {'concurrency':>11}{'tok/s':>9}{'req/s':>8}{'gain':>7}{'$/1M out':>11}")
    for r in rows:
        print(f"  {r['concurrency']:>11}{r['tok_per_s']:>9.0f}{r['req_per_s']:>8.2f}"
              f"{r['batching_gain']:>6.1f}x{r['cost_per_1m_out']:>11.4f}")
    best = rows[-1]
    print(f"\n  continuous batching gain at c={best['concurrency']}: {best['batching_gain']:.1f}x "
          f"throughput, ${best['cost_per_1m_out']:.4f}/1M output tokens")
    print("  wrote serving/results_serving.json + chart")


def _chart(rows) -> None:
    SHOTS.mkdir(parents=True, exist_ok=True)
    BG, FG, MUTED, BLUE, GREEN = "#0f1115", "#e6e9ef", "#9aa4b2", "#5b8cff", "#3ddc97"
    W, H, pad = 520, 340, 58
    xs = [r["concurrency"] for r in rows]
    tok = [r["tok_per_s"] for r in rows]
    cost = [r["cost_per_1m_out"] for r in rows]
    xmax = max(xs) or 1
    tmax = max(tok) or 1
    cmax = max(cost) or 1
    sx = lambda x: pad + (x / xmax) * (W - 2 * pad)
    syt = lambda v: H - pad - (v / tmax) * (H - 2 * pad)
    syc = lambda v: H - pad - (v / cmax) * (H - 2 * pad)
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
           f'font-family="ui-monospace, Menlo, monospace"><rect width="{W}" height="{H}" fill="{BG}"/>',
           f'<text x="{W//2}" y="24" fill="{FG}" font-size="14" text-anchor="middle">vLLM serving: throughput and cost vs concurrency</text>',
           f'<line x1="{pad}" y1="{H-pad}" x2="{W-pad}" y2="{H-pad}" stroke="{MUTED}"/>',
           f'<text x="{W//2}" y="{H-16}" fill="{MUTED}" font-size="11" text-anchor="middle">concurrency</text>',
           f'<text x="{pad}" y="{pad-8}" fill="{GREEN}" font-size="10">green: tokens/s (batching gain)</text>',
           f'<text x="{W-pad}" y="{pad-8}" fill="{BLUE}" font-size="10" text-anchor="end">blue: $/1M output tok</text>']
    def poly(pts, color):
        d = " ".join(f"{x:.0f},{y:.0f}" for x, y in pts)
        return f'<polyline points="{d}" fill="none" stroke="{color}" stroke-width="2"/>'
    svg.append(poly([(sx(r["concurrency"]), syt(r["tok_per_s"])) for r in rows], GREEN))
    svg.append(poly([(sx(r["concurrency"]), syc(r["cost_per_1m_out"])) for r in rows], BLUE))
    for r in rows:
        x = sx(r["concurrency"])
        svg.append(f'<circle cx="{x:.0f}" cy="{syt(r["tok_per_s"]):.0f}" r="4" fill="{GREEN}"/>')
        svg.append(f'<text x="{x:.0f}" y="{syt(r["tok_per_s"])-8:.0f}" fill="{FG}" font-size="9" text-anchor="middle">{r["tok_per_s"]:.0f}</text>')
        svg.append(f'<circle cx="{x:.0f}" cy="{syc(r["cost_per_1m_out"]):.0f}" r="4" fill="{BLUE}"/>')
        svg.append(f'<text x="{x:.0f}" y="{H-pad+16:.0f}" fill="{MUTED}" font-size="10" text-anchor="middle">{r["concurrency"]}</text>')
    svg.append("</svg>")
    (SHOTS / "serving-throughput.svg").write_text("\n".join(svg))


if __name__ == "__main__":
    main()
