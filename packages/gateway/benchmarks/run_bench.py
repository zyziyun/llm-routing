"""Real local benchmark. No mock, no keys, no cost: three real models served
by Ollama form the tier ladder, and a fourth (the strongest) acts as an
LLM-as-judge. Produces real quality / latency / validity numbers and the
cost-quality Pareto of the router against edge-only and frontier-only.

    ollama serve            # if not already running
    python benchmarks/run_bench.py

Writes benchmarks/results.json and two SVG charts under docs/screenshots/.
"""

from __future__ import annotations

import json
import re
import statistics
import time
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
GATEWAY = HERE.parent
SHOTS = GATEWAY / "docs" / "screenshots"
OLLAMA = "http://localhost:11434/v1/chat/completions"

# Real tier ladder (small -> mid -> large) and an equivalent hosted price so
# the cost axis is meaningful. Local inference is free; the price reflects what
# a model of this size costs on a hosted API (USD per 1K tokens).
TIERS = [
    ("edge", "llama3.2:1b", 0.0001),
    ("mid", "gemma4:e2b", 0.0006),
    ("frontier", "qwen2.5-coder:14b", 0.01),
]
JUDGE_MODEL = "qwen2.5-coder:14b"
PRICE = {name: p for name, _, p in TIERS}


def call(model: str, messages: list[dict], max_tokens: int = 256) -> dict:
    t0 = time.time()
    r = httpx.post(OLLAMA, json={"model": model, "messages": messages,
                                 "max_tokens": max_tokens, "temperature": 0.2}, timeout=600.0)
    r.raise_for_status()
    d = r.json()
    u = d.get("usage", {})
    return {
        "text": d["choices"][0]["message"]["content"],
        "prompt_tokens": u.get("prompt_tokens", 0),
        "completion_tokens": u.get("completion_tokens", 0),
        "latency_ms": round((time.time() - t0) * 1000, 1),
    }


def judge(question: str, answer: str) -> float:
    msg = [
        {"role": "system", "content": "You are a strict grader. Output only a number from 0 to 1."},
        {"role": "user", "content": f"Rate how correct and relevant the ANSWER is to the QUESTION, "
                                    f"from 0 to 1.\n\nQUESTION:\n{question}\n\nANSWER:\n{answer}\n\nScore:"},
    ]
    out = call(JUDGE_MODEL, msg, max_tokens=8)["text"]
    m = re.search(r"[01](?:\.\d+)?", out)
    return max(0.0, min(1.0, float(m.group()))) if m else 0.0


def valid_json(text: str, schema: dict) -> bool:
    try:
        s, e = text.find("{"), text.rfind("}")
        obj = json.loads(text[s:e + 1]) if s != -1 else json.loads(text)
    except Exception:
        return False
    return isinstance(obj, dict) and all(k in obj for k in schema.get("required", []))


def load_tasks() -> list[dict]:
    return [json.loads(l) for l in (HERE / "tasks.jsonl").read_text().splitlines() if l.strip()]


def available(model: str) -> bool:
    try:
        call(model, [{"role": "user", "content": "hi"}], max_tokens=1)
        return True
    except Exception:
        return False


def main() -> None:
    tasks = load_tasks()
    tiers = [(n, m, p) for n, m, p in TIERS if available(m)]
    print("models available:", [m for _, m, _ in tiers])
    if len(tiers) < 2:
        raise SystemExit("need at least two tier models (pull with `ollama pull`)")

    # matrix[task_id][tier] = {score, tokens, latency, valid}
    matrix: dict[str, dict[str, dict]] = {}
    for i, task in enumerate(tasks, 1):
        matrix[task["id"]] = {}
        for name, model, _ in tiers:
            gen = call(model, [{"role": "user", "content": task["prompt"]}])
            tokens = gen["prompt_tokens"] + gen["completion_tokens"]
            if "schema" in task:
                ok = valid_json(gen["text"], task["schema"])
                score = 1.0 if ok else 0.0
            else:
                ok = None
                score = judge(task["prompt"], gen["text"])
            matrix[task["id"]][name] = {"score": round(score, 3), "tokens": tokens,
                                        "latency_ms": gen["latency_ms"], "valid": ok}
            print(f"  [{i}/{len(tasks)}] {task['id']:<3} {name:<9} score={score:.2f} "
                  f"tok={tokens:<4} {gen['latency_ms']:.0f}ms")

    names = [n for n, _, _ in tiers]
    per_tier = {
        n: {
            "quality": round(statistics.mean(matrix[t][n]["score"] for t in matrix), 3),
            "latency_ms": round(statistics.mean(matrix[t][n]["latency_ms"] for t in matrix), 1),
            "tokens": round(statistics.mean(matrix[t][n]["tokens"] for t in matrix), 1),
        }
        for n in names
    }

    def strategy_router(threshold: float) -> dict:
        q = c = lat = 0.0
        mix = {n: 0 for n in names}
        for t in matrix:
            spent_tokens = 0.0
            spent_lat = 0.0
            chosen = None
            for n in names:  # walk small -> large
                cell = matrix[t][n]
                spent_tokens += cell["tokens"] / 1000 * PRICE[n]
                spent_lat += cell["latency_ms"]
                if cell["score"] >= threshold:
                    chosen = (n, cell["score"])
                    break
            if chosen is None:
                chosen = (names[-1], matrix[t][names[-1]]["score"])
            mix[chosen[0]] += 1
            q += chosen[1]
            c += spent_tokens
            lat += spent_lat
        n = len(matrix)
        return {"quality": round(q / n, 3), "cost": round(c, 6),
                "latency_ms": round(lat / n, 1), "mix": mix}

    def strategy_fixed(tier: str) -> dict:
        n = len(matrix)
        q = statistics.mean(matrix[t][tier]["score"] for t in matrix)
        c = sum(matrix[t][tier]["tokens"] / 1000 * PRICE[tier] for t in matrix)
        lat = statistics.mean(matrix[t][tier]["latency_ms"] for t in matrix)
        return {"quality": round(q, 3), "cost": round(c, 6), "latency_ms": round(lat, 1)}

    thresholds = [0.5, 0.6, 0.7, 0.8, 0.9]
    strategies = {
        "edge-only": strategy_fixed(names[0]),
        "frontier-only": strategy_fixed(names[-1]),
        **{f"router@{t}": strategy_router(t) for t in thresholds},
    }

    results = {"tiers": names, "models": {n: m for n, m, _ in tiers},
               "per_tier": per_tier, "strategies": strategies, "matrix": matrix}
    (HERE / "results.json").write_text(json.dumps(results, indent=2))

    print("\nper-tier (real local inference)")
    print(f"  {'tier':<10}{'quality':>9}{'avg_ms':>9}{'avg_tok':>9}")
    for n in names:
        pt = per_tier[n]
        print(f"  {n:<10}{pt['quality']:>9.2f}{pt['latency_ms']:>9.0f}{pt['tokens']:>9.0f}")

    print("\nstrategies (cost = equivalent hosted $/req)")
    print(f"  {'strategy':<16}{'quality':>9}{'cost$':>10}{'avg_ms':>9}")
    for k, v in strategies.items():
        print(f"  {k:<16}{v['quality']:>9.2f}{v['cost']:>10.5f}{v['latency_ms']:>9.0f}")

    _charts(per_tier, strategies, names)
    print("\nwrote benchmarks/results.json + charts under docs/screenshots/")


def _charts(per_tier, strategies, names) -> None:
    SHOTS.mkdir(parents=True, exist_ok=True)
    BG, FG, MUTED, GREEN, ORANGE, BLUE = "#0f1115", "#e6e9ef", "#9aa4b2", "#3ddc97", "#f7a23b", "#5b8cff"

    # Pareto: cost (x) vs quality (y)
    pts = [("edge-only", strategies["edge-only"]), ("frontier-only", strategies["frontier-only"])]
    pts += [(k, v) for k, v in strategies.items() if k.startswith("router@")]
    W, H, pad = 520, 360, 56
    costs = [v["cost"] for _, v in pts] or [0, 1]
    quals = [v["quality"] for _, v in pts] or [0, 1]
    cmin, cmax = min(costs), max(costs) or 1
    qmin, qmax = min(quals + [0]), max(quals + [1])

    def sx(c):
        return pad + (c - cmin) / (cmax - cmin or 1) * (W - 2 * pad)

    def sy(q):
        return H - pad - (q - qmin) / (qmax - qmin or 1) * (H - 2 * pad)

    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
           f'font-family="ui-monospace, Menlo, monospace"><rect width="{W}" height="{H}" fill="{BG}"/>',
           f'<text x="{W//2}" y="24" fill="{FG}" font-size="14" text-anchor="middle">cost vs quality (real local models)</text>',
           f'<line x1="{pad}" y1="{H-pad}" x2="{W-pad}" y2="{H-pad}" stroke="{MUTED}"/>',
           f'<line x1="{pad}" y1="{pad}" x2="{pad}" y2="{H-pad}" stroke="{MUTED}"/>',
           f'<text x="{W//2}" y="{H-16}" fill="{MUTED}" font-size="11" text-anchor="middle">cost $/req (equivalent hosted)</text>',
           f'<text x="16" y="{H//2}" fill="{MUTED}" font-size="11" transform="rotate(-90 16 {H//2})" text-anchor="middle">judge quality</text>']
    # Collapse points that land on the same coordinate (ties across thresholds)
    # into one dot with a merged label, so identical results read as identical.
    groups: dict[tuple, list] = {}
    for label, v in pts:
        key = (round(sx(v["cost"])), round(sy(v["quality"])), v["cost"], v["quality"])
        groups.setdefault(key, []).append((label, v))
    for (x, y, _, _), members in groups.items():
        label = members[0][0]
        routers = [m[0].split("@")[1] for m in members if m[0].startswith("router@")]
        if routers:
            label = "router@" + ("-".join([routers[0], routers[-1]]) if len(routers) > 1 else routers[0])
        col = GREEN if "edge" in label else ORANGE if "frontier" in label else BLUE
        svg.append(f'<circle cx="{x}" cy="{y}" r="5" fill="{col}"/>')
        anchor, tx = ("end", x - 8) if x > W - 90 else ("start", x + 8)
        svg.append(f'<text x="{tx}" y="{y+3}" fill="{FG}" font-size="10" text-anchor="{anchor}">{label}</text>')
    svg.append("</svg>")
    (SHOTS / "bench-pareto.svg").write_text("\n".join(svg))

    # Per-tier quality bars
    W2, H2, pad2 = 460, 260, 50
    bw = (W2 - 2 * pad2) / len(names)
    bars = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W2}" height="{H2}" viewBox="0 0 {W2} {H2}" '
            f'font-family="ui-monospace, Menlo, monospace"><rect width="{W2}" height="{H2}" fill="{BG}"/>',
            f'<text x="{W2//2}" y="24" fill="{FG}" font-size="14" text-anchor="middle">judge quality by tier</text>']
    palette = {"edge": GREEN, "mid": ORANGE, "frontier": BLUE}
    for i, n in enumerate(names):
        q = per_tier[n]["quality"]
        h = (H2 - 2 * pad2) * q
        x = pad2 + i * bw + 10
        y = H2 - pad2 - h
        bars.append(f'<rect x="{x:.0f}" y="{y:.0f}" width="{bw-20:.0f}" height="{h:.0f}" '
                    f'fill="{palette.get(n, MUTED)}" rx="4"/>')
        bars.append(f'<text x="{x+(bw-20)/2:.0f}" y="{H2-pad2+18:.0f}" fill="{FG}" font-size="11" text-anchor="middle">{n}</text>')
        bars.append(f'<text x="{x+(bw-20)/2:.0f}" y="{y-6:.0f}" fill="{FG}" font-size="11" text-anchor="middle">{q:.2f}</text>')
    bars.append("</svg>")
    (SHOTS / "bench-quality.svg").write_text("\n".join(bars))


if __name__ == "__main__":
    main()
