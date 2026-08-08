"""Judge A/B: is the local benchmark's judge biased toward its own tier?

Experiment 1 uses qwen2.5-coder:14b as both the frontier tier and the judge. A
model scoring its own outputs is a known bias. This re-scores the same answers
with an independent hosted judge (Claude Haiku) and reports where the two judges
disagree, and specifically whether the local judge inflates the frontier tier it
shares an identity with.

Needs a hosted judge key. Put it in packages/gateway/.env (gitignored):

    ANTHROPIC_API_KEY=sk-ant-...

Then:

    ollama serve
    python benchmarks/run_judge_ab.py
"""

from __future__ import annotations

import json
import os
import re
import statistics
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
SHOTS = HERE.parent / "docs" / "screenshots"
OLLAMA = "http://localhost:11434/v1/chat/completions"
ANTHROPIC = "https://api.anthropic.com/v1/messages"
CLAUDE_JUDGE = "claude-opus-5"  # strong, independent from qwen -> a credible gold judge

TIERS = [("edge", "llama3.2:1b"), ("mid", "gemma4:e2b"), ("frontier", "qwen2.5-coder:14b")]
LOCAL_JUDGE = "qwen2.5-coder:14b"  # same identity as the frontier tier


def _load_env() -> None:
    env = HERE.parent / ".env"
    if env.exists() and not os.environ.get("ANTHROPIC_API_KEY"):
        for line in env.read_text().splitlines():
            if line.strip() and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _score(text: str) -> float:
    m = re.search(r"[01](?:\.\d+)?", text)
    return max(0.0, min(1.0, float(m.group()))) if m else 0.0


def gen(model: str, prompt: str) -> str:
    r = httpx.post(OLLAMA, json={"model": model, "messages": [{"role": "user", "content": prompt}],
                                 "max_tokens": 256, "temperature": 0.0}, timeout=600.0)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def judge_local(question: str, answer: str) -> float:
    r = httpx.post(OLLAMA, json={"model": LOCAL_JUDGE, "temperature": 0.0, "max_tokens": 8,
        "messages": [
            {"role": "system", "content": "You are a strict grader. Output only a number from 0 to 1."},
            {"role": "user", "content": f"Rate how correct and relevant the ANSWER is to the QUESTION, "
                                        f"from 0 to 1.\n\nQUESTION:\n{question}\n\nANSWER:\n{answer}\n\nScore:"}]},
        timeout=600.0)
    r.raise_for_status()
    return _score(r.json()["choices"][0]["message"]["content"])


def judge_claude(question: str, answer: str) -> float:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise SystemExit("ANTHROPIC_API_KEY not set (put it in packages/gateway/.env)")
    # Opus 5 thinks by default and max_tokens caps thinking+text together, so a
    # tiny cap would return empty text. Disable thinking (allowed at default
    # `high` effort) for this plain numeric grader and give a little headroom.
    r = httpx.post(ANTHROPIC, headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                                       "content-type": "application/json"},
        json={"model": CLAUDE_JUDGE, "max_tokens": 16, "thinking": {"type": "disabled"},
              "system": "You are a strict grader. Output only a number from 0 to 1.",
              "messages": [{"role": "user", "content": f"Rate how correct and relevant the ANSWER is to "
                            f"the QUESTION, from 0 to 1.\n\nQUESTION:\n{question}\n\nANSWER:\n{answer}\n\nScore:"}]},
        timeout=120.0)
    r.raise_for_status()
    blocks = r.json()["content"]
    text = next((b["text"] for b in blocks if b.get("type") == "text"), "")
    return _score(text)


def main() -> None:
    _load_env()
    tasks = [json.loads(l) for l in (HERE / "tasks.jsonl").read_text().splitlines() if l.strip()]
    tasks = [t for t in tasks if "schema" not in t]  # judged tasks only, not validity tasks

    rows = []
    for t in tasks:
        for name, model in TIERS:
            ans = gen(model, t["prompt"])
            jl, jc = judge_local(t["prompt"], ans), judge_claude(t["prompt"], ans)
            rows.append({"id": t["id"], "tier": name, "local": jl, "claude": jc, "gap": round(jl - jc, 3)})
            print(f"  {t['id']:<3} {name:<9} local={jl:.2f} claude={jc:.2f} gap={jl-jc:+.2f}")

    by_tier = {}
    for name, _ in TIERS:
        r = [x for x in rows if x["tier"] == name]
        by_tier[name] = {
            "local_mean": round(statistics.mean(x["local"] for x in r), 3),
            "claude_mean": round(statistics.mean(x["claude"] for x in r), 3),
            "mean_gap": round(statistics.mean(x["gap"] for x in r), 3),
        }
    overall_gap = round(statistics.mean(x["gap"] for x in rows), 3)
    corr = _pearson([x["local"] for x in rows], [x["claude"] for x in rows])

    results = {"local_judge": LOCAL_JUDGE, "independent_judge": CLAUDE_JUDGE,
               "by_tier": by_tier, "overall_local_minus_claude": overall_gap,
               "pearson_r": corr, "rows": rows}
    (HERE / "results_judge_ab.json").write_text(json.dumps(results, indent=2))
    _chart(by_tier)

    print("\njudge A/B (local qwen self-judge vs independent Claude)")
    print(f"  {'tier':<10}{'local':>8}{'claude':>8}{'gap':>8}")
    for name, v in by_tier.items():
        print(f"  {name:<10}{v['local_mean']:>8.2f}{v['claude_mean']:>8.2f}{v['mean_gap']:>+8.2f}")
    print(f"\n  overall local-minus-claude: {overall_gap:+.3f}   pearson r: {corr:.3f}")
    fg = by_tier["frontier"]["mean_gap"]
    print(f"  frontier self-preference (local inflates its own tier): {fg:+.3f}")
    print("\nwrote benchmarks/results_judge_ab.json + chart")


def _pearson(a, b):
    n = len(a)
    ma, mb = statistics.mean(a), statistics.mean(b)
    num = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    da = sum((x - ma) ** 2 for x in a) ** 0.5
    db = sum((y - mb) ** 2 for y in b) ** 0.5
    return round(num / (da * db), 3) if da and db else 0.0


def _chart(by_tier) -> None:
    SHOTS.mkdir(parents=True, exist_ok=True)
    BG, FG, MUTED, BLUE, PURPLE = "#0f1115", "#e6e9ef", "#9aa4b2", "#5b8cff", "#c084fc"
    W, H, pad = 480, 300, 54
    names = list(by_tier)
    group_w = (W - 2 * pad) / len(names)
    bw = group_w / 3
    maxh = H - 2 * pad
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
           f'font-family="ui-monospace, Menlo, monospace"><rect width="{W}" height="{H}" fill="{BG}"/>',
           f'<text x="{W//2}" y="24" fill="{FG}" font-size="14" text-anchor="middle">judge A/B: local self-judge vs independent Claude</text>',
           f'<line x1="{pad}" y1="{H-pad}" x2="{W-pad}" y2="{H-pad}" stroke="{MUTED}"/>']
    for i, name in enumerate(names):
        v = by_tier[name]
        base = pad + i * group_w + group_w / 2
        for j, (val, col) in enumerate([(v["local_mean"], BLUE), (v["claude_mean"], PURPLE)]):
            h = maxh * val
            x = base - bw + j * bw
            y = H - pad - h
            svg.append(f'<rect x="{x:.0f}" y="{y:.0f}" width="{bw-6:.0f}" height="{h:.0f}" fill="{col}" rx="3"/>')
            svg.append(f'<text x="{x+(bw-6)/2:.0f}" y="{y-6:.0f}" fill="{FG}" font-size="10" text-anchor="middle">{val:.2f}</text>')
        svg.append(f'<text x="{base:.0f}" y="{H-pad+18:.0f}" fill="{FG}" font-size="11" text-anchor="middle">{name}</text>')
    svg.append(f'<rect x="{W-170}" y="40" width="10" height="10" fill="{BLUE}"/><text x="{W-155}" y="49" fill="{MUTED}" font-size="10">local qwen (self)</text>')
    svg.append(f'<rect x="{W-170}" y="56" width="10" height="10" fill="{PURPLE}"/><text x="{W-155}" y="65" fill="{MUTED}" font-size="10">Claude (independent)</text>')
    svg.append("</svg>")
    (SHOTS / "judge-ab.svg").write_text("\n".join(svg))


if __name__ == "__main__":
    main()
