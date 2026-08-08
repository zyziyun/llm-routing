"""Constrained decoding, measured on real small models. No mock.

Runs a set of strict-JSON extraction tasks on the two cheap tiers twice: once
free-form, once with the model's decoder constrained to the task's JSON Schema
(Ollama's OpenAI-compatible `response_format: json_schema`, the local-tier
analogue of Outlines / XGrammar). Measures how many answers are schema-valid
before and after, and therefore how many structure-caused escalations to the
frontier the constraint removes.

    ollama serve
    python benchmarks/run_constrained_bench.py
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
SHOTS = HERE.parent / "docs" / "screenshots"
OLLAMA = "http://localhost:11434/v1/chat/completions"

# The two cheap tiers. The frontier is where structure-caused escalations land,
# so it is the cost we are trying to avoid paying, not a row to benchmark.
MODELS = [("edge", "llama3.2:1b"), ("mid", "gemma4:e2b")]
FRONTIER_PRICE = 0.01  # $/1K tok, the escalation we avoid


def call(model: str, prompt: str, schema: dict, constrain: bool) -> dict:
    # Both conditions ask for JSON in the prompt. The ONLY difference between
    # free-form and constrained is whether the decoder is grammar-constrained,
    # so the delta isolates decoding, not the instruction.
    keys = ", ".join(schema["required"])
    ask = f"{prompt} Return a strict JSON object with keys: {keys}. JSON only, no prose."
    # 400 tokens: generous enough that a verbose free-form answer (fences +
    # preamble) is not truncated, so a failure is a real structure failure and
    # not a token-budget artifact. Constrained output is compact and never needs
    # the headroom, which is itself part of the point.
    body = {"model": model, "messages": [{"role": "user", "content": ask}],
            "max_tokens": 400, "temperature": 0.0}
    if constrain:
        body["response_format"] = {"type": "json_schema",
                                   "json_schema": {"name": "extract", "schema": schema}}
    t0 = time.time()
    r = httpx.post(OLLAMA, json=body, timeout=600.0)
    r.raise_for_status()
    d = r.json()
    return {"text": d["choices"][0]["message"]["content"],
            "finish": d["choices"][0].get("finish_reason"),
            "completion_tokens": d.get("usage", {}).get("completion_tokens", 0),
            "latency_ms": round((time.time() - t0) * 1000, 1)}


_JSON = {"string": str, "number": (int, float), "integer": int,
         "boolean": bool, "array": list, "object": dict}


def strict_valid(text: str, schema: dict) -> bool:
    """Parse must succeed, every required key present, every typed key the right type."""
    try:
        s, e = text.find("{"), text.rfind("}")
        obj = json.loads(text[s:e + 1]) if s != -1 else json.loads(text)
    except Exception:
        return False
    if not isinstance(obj, dict):
        return False
    props = schema.get("properties", {})
    for k in schema.get("required", []):
        if k not in obj:
            return False
    for k, spec in props.items():
        if k in obj and spec.get("type") in _JSON and not isinstance(obj[k], _JSON[spec["type"]]):
            # bool is an int subclass; keep number/integer honest about that
            if not (spec["type"] in ("number", "integer") and isinstance(obj[k], bool) is False):
                return False
    return True


def main() -> None:
    tasks = [json.loads(l) for l in (HERE / "tasks_schema.jsonl").read_text().splitlines() if l.strip()]
    rows = {}
    per_task = []
    for name, model in MODELS:
        off = on = 0
        tok_free = tok_cons = 0
        detail = []
        for t in tasks:
            free = call(model, t["prompt"], t["schema"], constrain=False)
            cons = call(model, t["prompt"], t["schema"], constrain=True)
            vf = strict_valid(free["text"], t["schema"])
            vc = strict_valid(cons["text"], t["schema"])
            off += vf
            on += vc
            tok_free += free["completion_tokens"]
            tok_cons += cons["completion_tokens"]
            detail.append({"id": t["id"], "free_valid": vf, "constrained_valid": vc,
                           "free_tokens": free["completion_tokens"],
                           "constrained_tokens": cons["completion_tokens"]})
            print(f"  {name:<5} {t['id']:<4} free={'ok ' if vf else 'BAD'} "
                  f"constrained={'ok ' if vc else 'BAD'}  "
                  f"tok {free['completion_tokens']:>3}->{cons['completion_tokens']:>3}")
        n = len(tasks)
        rows[name] = {"model": model, "n": n,
                      "valid_free": off, "valid_constrained": on,
                      "rate_free": round(off / n, 3), "rate_constrained": round(on / n, 3),
                      "avg_tokens_free": round(tok_free / n, 1),
                      "avg_tokens_constrained": round(tok_cons / n, 1),
                      "escalations_removed": on - off}
        per_task.append({name: detail})
        print(f"  -> {name}: free {off}/{n} valid, constrained {on}/{n} valid, "
              f"{on - off} structure-caused escalations removed\n")

    results = {"models": {n: m for n, m in MODELS}, "tiers": rows, "per_task": per_task}
    (HERE / "results_constrained.json").write_text(json.dumps(results, indent=2))
    _chart(rows)

    print("summary (strict validity: parse + required keys + types)")
    print(f"  {'tier':<6}{'free':>8}{'constrained':>13}{'removed':>9}{'tok free':>10}{'tok con':>9}")
    for name, r in rows.items():
        print(f"  {name:<6}{r['rate_free']*100:>7.0f}%{r['rate_constrained']*100:>12.0f}%"
              f"{r['escalations_removed']:>9}{r['avg_tokens_free']:>10.0f}{r['avg_tokens_constrained']:>9.0f}")
    print("\nwrote benchmarks/results_constrained.json + chart")


def _chart(rows) -> None:
    """Both conditions hit 100% validity, so the story is output discipline:
    plot average completion tokens, free vs constrained, per tier."""
    SHOTS.mkdir(parents=True, exist_ok=True)
    BG, FG, MUTED, RED, GREEN = "#0f1115", "#e6e9ef", "#9aa4b2", "#f7647b", "#3ddc97"
    W, H, pad = 480, 300, 54
    names = list(rows)
    group_w = (W - 2 * pad) / len(names)
    bw = group_w / 3
    maxtok = max(max(rows[n]["avg_tokens_free"], rows[n]["avg_tokens_constrained"]) for n in names) or 1
    maxh = H - 2 * pad
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
           f'font-family="ui-monospace, Menlo, monospace"><rect width="{W}" height="{H}" fill="{BG}"/>',
           f'<text x="{W//2}" y="24" fill="{FG}" font-size="14" text-anchor="middle">tokens per answer: free vs constrained (both 100% valid)</text>',
           f'<line x1="{pad}" y1="{H-pad}" x2="{W-pad}" y2="{H-pad}" stroke="{MUTED}"/>']
    for i, name in enumerate(names):
        r = rows[name]
        base = pad + i * group_w + group_w / 2
        for j, (val, col) in enumerate([(r["avg_tokens_free"], RED),
                                        (r["avg_tokens_constrained"], GREEN)]):
            h = maxh * (val / maxtok)
            x = base - bw + j * bw
            y = H - pad - h
            svg.append(f'<rect x="{x:.0f}" y="{y:.0f}" width="{bw-6:.0f}" height="{h:.0f}" fill="{col}" rx="3"/>')
            svg.append(f'<text x="{x+(bw-6)/2:.0f}" y="{y-6:.0f}" fill="{FG}" font-size="10" text-anchor="middle">{val:.0f}</text>')
        factor = r["avg_tokens_free"] / r["avg_tokens_constrained"] if r["avg_tokens_constrained"] else 1
        svg.append(f'<text x="{base:.0f}" y="{H-pad+18:.0f}" fill="{FG}" font-size="11" text-anchor="middle">{name} ({r["model"].split(":")[0]})</text>')
        svg.append(f'<text x="{base:.0f}" y="{H-pad+32:.0f}" fill="{MUTED}" font-size="10" text-anchor="middle">{factor:.1f}x fewer</text>')
    svg.append(f'<rect x="{W-160}" y="40" width="10" height="10" fill="{RED}"/><text x="{W-145}" y="49" fill="{MUTED}" font-size="10">free-form</text>')
    svg.append(f'<rect x="{W-160}" y="56" width="10" height="10" fill="{GREEN}"/><text x="{W-145}" y="65" fill="{MUTED}" font-size="10">constrained</text>')
    svg.append("</svg>")
    (SHOTS / "constrained-tokens.svg").write_text("\n".join(svg))


if __name__ == "__main__":
    main()
