"""Real edge->cloud benchmark: local small models escalate to real hosted
frontiers. No mock. Judged by an independent gold judge (claude-opus-5), so the
quality numbers are not the self-scored, lenient ones from run_bench.py.

Four real tiers, three providers:
  edge            llama3.2:1b        Ollama, local
  local-frontier  qwen2.5-coder:14b  Ollama, local
  cloud:sonnet    claude-sonnet-5    Anthropic API
  cloud:gpt5      gpt-5              OpenAI API

The router escalates edge -> local-frontier -> cloud, crossing the on-device /
hosted boundary the repo is about. Costs are real token counts times per-tier
prices: local tiers use an equivalent-hosted estimate, cloud tiers use published
API prices (edit PRICES to match your contract). Judge is independent of every
tier, and is never itself a tier, so there is no self-scoring bias.

Needs ANTHROPIC_API_KEY and OPENAI_API_KEY in packages/gateway/.env:

    ollama serve
    python benchmarks/run_hosted_bench.py
"""

from __future__ import annotations

import json
import os
import re
import statistics
import time
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
SHOTS = HERE.parent / "docs" / "screenshots"
OLLAMA = "http://localhost:11434/v1/chat/completions"
ANTHROPIC = "https://api.anthropic.com/v1/messages"
OPENAI = "https://api.openai.com/v1/chat/completions"
DEEPSEEK = "https://api.deepseek.com/v1/chat/completions"
JUDGE_MODEL = "claude-opus-5"  # independent gold judge; never a tier

# (name, kind, model, in_$/1k, out_$/1k). Local prices are equivalent-hosted
# estimates; cloud prices are published rates (verify against your own contract).
# Clouds are listed cheapest-first; deepseek is an open-weight model served via
# a hosted OpenAI-compatible API, so the router treats it as just another tier.
TIERS = [
    ("edge", "ollama", "llama3.2:1b", 0.0001, 0.0001),
    ("local-frontier", "ollama", "qwen2.5-coder:14b", 0.01, 0.01),
    ("cloud:deepseek", "deepseek", "deepseek-chat", 0.00027, 0.0011),
    ("cloud:gpt5", "openai", "gpt-5", 0.00125, 0.010),
    ("cloud:sonnet", "anthropic", "claude-sonnet-5", 0.003, 0.015),
]
# Env key each kind needs; a tier is skipped when its key is absent so the run
# adapts to whatever providers you have configured. ollama needs no key.
KEY_ENV = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "deepseek": "DEEPSEEK_API_KEY"}


def _env() -> None:
    env = HERE.parent / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def generate(kind: str, model: str, prompt: str) -> dict:
    t0 = time.time()
    if kind == "ollama":
        r = httpx.post(OLLAMA, json={"model": model, "messages": [{"role": "user", "content": prompt}],
                                     "max_tokens": 256, "temperature": 0.2}, timeout=600.0)
        r.raise_for_status()
        d = r.json(); u = d.get("usage", {})
        text, pt, ct = d["choices"][0]["message"]["content"], u.get("prompt_tokens", 0), u.get("completion_tokens", 0)
    elif kind == "anthropic":
        r = httpx.post(ANTHROPIC, headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"],
                                           "anthropic-version": "2023-06-01", "content-type": "application/json"},
                       json={"model": model, "max_tokens": 512, "thinking": {"type": "disabled"},
                             "messages": [{"role": "user", "content": prompt}]}, timeout=600.0)
        r.raise_for_status()
        d = r.json(); u = d.get("usage", {})
        text = next((b["text"] for b in d["content"] if b.get("type") == "text"), "")
        pt, ct = u.get("input_tokens", 0), u.get("output_tokens", 0)
    elif kind == "openai":
        # gpt-5 is a reasoning model: no temperature, max_completion_tokens must
        # be generous (reasoning tokens count as completion) or the reply is empty.
        r = httpx.post(OPENAI, headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
                                        "content-type": "application/json"},
                       json={"model": model, "messages": [{"role": "user", "content": prompt}],
                             "max_completion_tokens": 2000}, timeout=600.0)
        r.raise_for_status()
        d = r.json(); u = d.get("usage", {})
        text = d["choices"][0]["message"]["content"] or ""
        pt, ct = u.get("prompt_tokens", 0), u.get("completion_tokens", 0)
    elif kind == "deepseek":
        # Open-weight model behind an OpenAI-compatible hosted API. Standard
        # params (deepseek-chat is the non-reasoning V3; takes max_tokens/temperature).
        r = httpx.post(DEEPSEEK, headers={"Authorization": f"Bearer {os.environ['DEEPSEEK_API_KEY']}",
                                          "content-type": "application/json"},
                       json={"model": model, "messages": [{"role": "user", "content": prompt}],
                             "max_tokens": 512, "temperature": 0.2}, timeout=600.0)
        r.raise_for_status()
        d = r.json(); u = d.get("usage", {})
        text = d["choices"][0]["message"]["content"] or ""
        pt, ct = u.get("prompt_tokens", 0), u.get("completion_tokens", 0)
    else:
        raise ValueError(kind)
    return {"text": text, "prompt_tokens": pt, "completion_tokens": ct,
            "latency_ms": round((time.time() - t0) * 1000, 1)}


def judge(question: str, answer: str) -> float:
    r = httpx.post(ANTHROPIC, headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"],
                                       "anthropic-version": "2023-06-01", "content-type": "application/json"},
                   json={"model": JUDGE_MODEL, "max_tokens": 16, "thinking": {"type": "disabled"},
                         "system": "You are a strict grader. Output only a number from 0 to 1.",
                         "messages": [{"role": "user", "content": f"Rate how correct and relevant the ANSWER is "
                                       f"to the QUESTION, from 0 to 1.\n\nQUESTION:\n{question}\n\nANSWER:\n{answer}\n\nScore:"}]},
                   timeout=120.0)
    r.raise_for_status()
    txt = next((b["text"] for b in r.json()["content"] if b.get("type") == "text"), "")
    m = re.search(r"[01](?:\.\d+)?", txt)
    return max(0.0, min(1.0, float(m.group()))) if m else 0.0


def valid_json(text: str, schema: dict) -> bool:
    try:
        s, e = text.find("{"), text.rfind("}")
        obj = json.loads(text[s:e + 1]) if s != -1 else json.loads(text)
    except Exception:
        return False
    return isinstance(obj, dict) and all(k in obj for k in schema.get("required", []))


def cost(cell: dict, name: str) -> float:
    p = {t[0]: (t[3], t[4]) for t in TIERS}[name]
    return cell["prompt_tokens"] / 1000 * p[0] + cell["completion_tokens"] / 1000 * p[1]


def main() -> None:
    _env()
    tasks = [json.loads(l) for l in (HERE / "tasks.jsonl").read_text().splitlines() if l.strip()]
    tiers = [t for t in TIERS if t[1] == "ollama" or os.environ.get(KEY_ENV.get(t[1], ""))]
    names = [t[0] for t in tiers]
    skipped = [t[0] for t in TIERS if t not in tiers]
    if skipped:
        print(f"skipping (no key): {skipped}")
    matrix: dict[str, dict[str, dict]] = {}
    for i, task in enumerate(tasks, 1):
        matrix[task["id"]] = {}
        for name, kind, model, _, _ in tiers:
            g = generate(kind, model, task["prompt"])
            if "schema" in task:
                score = 1.0 if valid_json(g["text"], task["schema"]) else 0.0
            else:
                score = judge(task["prompt"], g["text"])
            cell = {"score": round(score, 3), "prompt_tokens": g["prompt_tokens"],
                    "completion_tokens": g["completion_tokens"], "latency_ms": g["latency_ms"]}
            cell["cost"] = round(cost(cell, name), 6)
            matrix[task["id"]][name] = cell
            print(f"  [{i}/{len(tasks)}] {task['id']:<3} {name:<15} score={score:.2f} "
                  f"tok={g['prompt_tokens']}+{g['completion_tokens']:<4} ${cell['cost']:.5f} {g['latency_ms']:.0f}ms")

    per_tier = {n: {"quality": round(statistics.mean(matrix[t][n]["score"] for t in matrix), 3),
                    "cost": round(sum(matrix[t][n]["cost"] for t in matrix), 6),
                    "latency_ms": round(statistics.mean(matrix[t][n]["latency_ms"] for t in matrix), 1)}
                for n in names}

    def fixed(name):
        return {"quality": per_tier[name]["quality"], "cost": per_tier[name]["cost"],
                "latency_ms": per_tier[name]["latency_ms"]}

    def router(chain, th):
        q = c = lat = 0.0; mix = {n: 0 for n in chain}
        for t in matrix:
            spent_c = spent_lat = 0.0; chosen = None
            for n in chain:
                cell = matrix[t][n]; spent_c += cell["cost"]; spent_lat += cell["latency_ms"]
                if cell["score"] >= th:
                    chosen = (n, cell["score"]); break
            if chosen is None:
                chosen = (chain[-1], matrix[t][chain[-1]]["score"])
            mix[chosen[0]] += 1; q += chosen[1]; c += spent_c; lat += spent_lat
        n = len(matrix)
        return {"quality": round(q / n, 3), "cost": round(c, 6), "latency_ms": round(lat / n, 1), "mix": mix}

    # Two router shapes, provider-count-agnostic:
    #   cascade  -- walk every cloud in series until one clears the gate. Autonomous
    #               and provider-agnostic, but it double-pays cloud on hard turns.
    #   select   -- escalate to ONE cloud, the best measured quality-per-dollar. This
    #               is the predictive-routing fix (route to the right cloud, don't walk).
    price_in = {t[0]: t[3] for t in TIERS}
    local_names = [n for n in names if not n.startswith("cloud:")]
    cloud_names = sorted((n for n in names if n.startswith("cloud:")), key=lambda n: price_in[n])
    cascade_chain = local_names + cloud_names
    best_cloud = max(cloud_names, key=lambda n: per_tier[n]["quality"] / (per_tier[n]["cost"] + 1e-9)) if cloud_names else None
    select_chain = local_names + ([best_cloud] if best_cloud else [])

    strategies = {"edge-only": fixed("edge"), "local-frontier-only": fixed("local-frontier")}
    for cn in cloud_names:
        strategies[f"cloud-only:{cn.split(':')[1]}"] = fixed(cn)
    for th in (0.7, 0.9):
        strategies[f"router-cascade@{th}"] = router(cascade_chain, th)
        if best_cloud:
            strategies[f"router-select@{th}"] = router(select_chain, th)

    results = {"judge": JUDGE_MODEL, "tiers": names, "cascade_chain": cascade_chain,
               "select_chain": select_chain, "best_value_cloud": best_cloud,
               "prices": {t[0]: {"in_per_1k": t[3], "out_per_1k": t[4]} for t in TIERS if t[0] in names},
               "per_tier": per_tier, "strategies": strategies, "matrix": matrix}
    (HERE / "results_hosted.json").write_text(json.dumps(results, indent=2))
    _charts(per_tier, strategies, names)

    print("\nper-tier (judged by " + JUDGE_MODEL + ")")
    print(f"  {'tier':<16}{'quality':>9}{'cost$':>10}{'avg_ms':>9}")
    for n in names:
        pt = per_tier[n]
        print(f"  {n:<16}{pt['quality']:>9.2f}{pt['cost']:>10.5f}{pt['latency_ms']:>9.0f}")
    print(f"\nbest quality/$ cloud (select target): {best_cloud}")
    print("strategies")
    print(f"  {'strategy':<22}{'quality':>9}{'cost$':>10}{'avg_ms':>9}")
    for k, v in strategies.items():
        print(f"  {k:<22}{v['quality']:>9.2f}{v['cost']:>10.5f}{v['latency_ms']:>9.0f}")
    if best_cloud:
        print(f"\n  router-cascade@0.9 mix: {strategies['router-cascade@0.9']['mix']}")
        print(f"  router-select@0.9  mix: {strategies['router-select@0.9']['mix']}")
    print("wrote benchmarks/results_hosted.json + charts")


def _charts(per_tier, strategies, names) -> None:
    SHOTS.mkdir(parents=True, exist_ok=True)
    BG, FG, MUTED, GREEN, ORANGE, BLUE, PURPLE = "#0f1115", "#e6e9ef", "#9aa4b2", "#3ddc97", "#f7a23b", "#5b8cff", "#c084fc"
    pts = [("edge-only", strategies["edge-only"]), ("local-frontier-only", strategies["local-frontier-only"]),
           ("cloud:sonnet", strategies["cloud-only:sonnet"]), ("cloud:gpt5", strategies["cloud-only:gpt5"])]
    pts += [(k, v) for k, v in strategies.items() if k.startswith("router-")]
    W, H, pad = 560, 380, 58
    costs = [v["cost"] for _, v in pts]; quals = [v["quality"] for _, v in pts]
    cmin, cmax = min(costs), max(costs) or 1
    qmin, qmax = min(quals + [0]), max(quals + [1])
    sx = lambda c: pad + (c - cmin) / (cmax - cmin or 1) * (W - 2 * pad)
    sy = lambda q: H - pad - (q - qmin) / (qmax - qmin or 1) * (H - 2 * pad)
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
           f'font-family="ui-monospace, Menlo, monospace"><rect width="{W}" height="{H}" fill="{BG}"/>',
           f'<text x="{W//2}" y="24" fill="{FG}" font-size="14" text-anchor="middle">edge -> cloud: cost vs quality (judged by claude-opus-5)</text>',
           f'<line x1="{pad}" y1="{H-pad}" x2="{W-pad}" y2="{H-pad}" stroke="{MUTED}"/>',
           f'<line x1="{pad}" y1="{pad}" x2="{pad}" y2="{H-pad}" stroke="{MUTED}"/>',
           f'<text x="{W//2}" y="{H-16}" fill="{MUTED}" font-size="11" text-anchor="middle">cost $/12 tasks (real API pricing for cloud)</text>',
           f'<text x="16" y="{H//2}" fill="{MUTED}" font-size="11" transform="rotate(-90 16 {H//2})" text-anchor="middle">gold-judge quality</text>']
    col = {"edge": GREEN, "local": ORANGE, "cloud:sonnet": PURPLE, "cloud:gpt5": "#e05c6e", "router": BLUE}
    for label, v in pts:
        x, y = sx(v["cost"]), sy(v["quality"])
        c = col["edge"] if "edge" in label else col["local"] if "local" in label else \
            col["cloud:sonnet"] if "sonnet" in label else col["cloud:gpt5"] if "gpt5" in label else col["router"]
        anchor, tx = ("end", x - 8) if x > W - 110 else ("start", x + 8)
        svg.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="5" fill="{c}"/>')
        svg.append(f'<text x="{tx:.0f}" y="{y+3:.0f}" fill="{FG}" font-size="10" text-anchor="{anchor}">{label}</text>')
    svg.append("</svg>")
    (SHOTS / "hosted-pareto.svg").write_text("\n".join(svg))

    W2, H2, pad2 = 560, 280, 54
    bw = (W2 - 2 * pad2) / len(names)
    palette = {"edge": GREEN, "local-frontier": ORANGE, "cloud:sonnet": PURPLE, "cloud:gpt5": "#e05c6e"}
    bars = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W2}" height="{H2}" viewBox="0 0 {W2} {H2}" '
            f'font-family="ui-monospace, Menlo, monospace"><rect width="{W2}" height="{H2}" fill="{BG}"/>',
            f'<text x="{W2//2}" y="24" fill="{FG}" font-size="14" text-anchor="middle">gold-judge quality by tier</text>']
    for i, n in enumerate(names):
        q = per_tier[n]["quality"]; h = (H2 - 2 * pad2) * q
        x = pad2 + i * bw + 12; y = H2 - pad2 - h
        bars.append(f'<rect x="{x:.0f}" y="{y:.0f}" width="{bw-24:.0f}" height="{h:.0f}" fill="{palette.get(n, MUTED)}" rx="4"/>')
        bars.append(f'<text x="{x+(bw-24)/2:.0f}" y="{H2-pad2+18:.0f}" fill="{FG}" font-size="10" text-anchor="middle">{n}</text>')
        bars.append(f'<text x="{x+(bw-24)/2:.0f}" y="{y-6:.0f}" fill="{FG}" font-size="11" text-anchor="middle">{q:.2f}</text>')
    bars.append("</svg>")
    (SHOTS / "hosted-quality.svg").write_text("\n".join(bars))


if __name__ == "__main__":
    main()
