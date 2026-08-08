"""Predictive router: decide the tier from the query alone, route once.

run_hosted_bench.py showed the cascade router double-pays cloud on hard turns
(walk edge -> ... -> cloud, billing each miss). The fix the field converged on
(RouteLLM, aurelio semantic-router) is *predictive* routing: look at the query,
predict the tier that will clear the quality bar, and go straight there -- one
call, no speculative escalation.

This measures that. It reuses the gold-judge matrix from run_hosted_bench.py
(so no models are re-run) and only computes local embeddings. The predictor is a
cosine k-NN over prompt embeddings (nomic-embed-text via Ollama) -- the same
"nearest example utterances" mechanism as aurelio semantic-router. Because the
task set is tiny (12), accuracy is estimated with leave-one-out cross-validation:
each task is routed by a predictor trained on the other 11. Treat the numbers as
a demonstration of the mechanism and its cost shape, not a production accuracy.

    ollama serve
    ollama pull nomic-embed-text
    python benchmarks/run_hosted_bench.py   # produces results_hosted.json first
    python benchmarks/run_predictive_bench.py
"""

from __future__ import annotations

import json
import math
import statistics
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
SHOTS = HERE.parent / "docs" / "screenshots"
EMBED = "http://localhost:11434/api/embeddings"
EMBED_MODEL = "nomic-embed-text"
TAU = 0.7  # quality bar: the cheapest tier clearing this is the ideal route


def embed(text: str) -> list[float]:
    r = httpx.post(EMBED, json={"model": EMBED_MODEL, "prompt": text}, timeout=120.0)
    r.raise_for_status()
    return r.json()["embedding"]


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)); nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def main() -> None:
    res = json.loads((HERE / "results_hosted.json").read_text())
    matrix, names, per_tier = res["matrix"], res["tiers"], res["per_tier"]
    prompts = {json.loads(l)["id"]: json.loads(l)["prompt"]
               for l in (HERE / "tasks.jsonl").read_text().splitlines() if l.strip()}
    ids = list(matrix)

    # Escalation order = tiers cheapest-first (by measured mean cost). The ideal
    # ("oracle") route for a task is the cheapest tier whose gold score clears TAU;
    # if none does, the highest-scoring tier (tie-break cheapest) is the best shot.
    order = sorted(names, key=lambda n: per_tier[n]["cost"])
    cost_rank = {n: i for i, n in enumerate(order)}

    def oracle_label(tid: str) -> str:
        for n in order:
            if matrix[tid][n]["score"] >= TAU:
                return n
        return max(order, key=lambda n: (matrix[tid][n]["score"], -cost_rank[n]))

    labels = {tid: oracle_label(tid) for tid in ids}
    embs = {tid: embed(prompts[tid]) for tid in ids}

    def predict(tid: str, k: int = 3) -> str:
        # Similarity-weighted vote over the k nearest OTHER tasks (LOOCV).
        sims = sorted(((cosine(embs[tid], embs[o]), o) for o in ids if o != tid), reverse=True)[:k]
        weight: dict[str, float] = {}
        for s, o in sims:
            weight[labels[o]] = weight.get(labels[o], 0.0) + max(s, 0.0)
        return max(weight, key=weight.get) if weight else order[0]

    preds = {tid: predict(tid) for tid in ids}

    def evaluate(route) -> dict:
        q = c = lat = 0.0; correct = under = over = 0
        for tid in ids:
            n = route(tid); cell = matrix[tid][n]
            q += cell["score"]; c += cell["cost"]; lat += cell["latency_ms"]
            if n == labels[tid]:
                correct += 1
            elif cost_rank[n] < cost_rank[labels[tid]]:
                under += 1   # routed cheaper than needed -> quality risk
            else:
                over += 1    # routed dearer than needed -> wasted spend
        N = len(ids)
        return {"quality": round(q / N, 3), "cost": round(c, 6), "latency_ms": round(lat / N, 1),
                "accuracy": round(correct / N, 3), "under": under, "over": over}

    predictive = evaluate(lambda t: preds[t])
    oracle = evaluate(lambda t: labels[t])
    # Pull the already-computed cascade/select/fixed strategies for comparison.
    S = res["strategies"]
    best_cloud = res.get("best_value_cloud")
    comp = {
        "edge-only": S["edge-only"],
        f"cloud-only:{best_cloud.split(':')[1]}" if best_cloud else "cloud-only": S.get(
            f"cloud-only:{best_cloud.split(':')[1]}") if best_cloud else None,
        "router-cascade@0.7": S.get("router-cascade@0.7"),
        "router-select@0.7": S.get("router-select@0.7"),
        "router-predictive": predictive,
        "oracle (upper bound)": oracle,
    }
    comp = {k: v for k, v in comp.items() if v}

    out = {"judge": res.get("judge"), "tau": TAU, "embed_model": EMBED_MODEL,
           "escalation_order": order, "labels": labels, "predictions": preds,
           "predictive": predictive, "oracle": oracle, "comparison": comp}
    (HERE / "results_predictive.json").write_text(json.dumps(out, indent=2))
    _chart(comp)

    print(f"predictive router (embedding k-NN, LOOCV, TAU={TAU}, judge={res.get('judge')})")
    print(f"  escalation order (cheapest-first): {order}")
    print(f"\n  {'strategy':<26}{'quality':>9}{'cost$':>10}{'avg_ms':>9}")
    for k, v in comp.items():
        print(f"  {k:<26}{v['quality']:>9.2f}{v['cost']:>10.5f}{v['latency_ms']:>9.0f}")
    print(f"\n  predictive routing accuracy vs oracle: {predictive['accuracy']*100:.0f}%"
          f"  (under-routed {predictive['under']}, over-routed {predictive['over']} of {len(ids)})")
    print("  wrote benchmarks/results_predictive.json + chart")


def _chart(comp) -> None:
    SHOTS.mkdir(parents=True, exist_ok=True)
    BG, FG, MUTED = "#0f1115", "#e6e9ef", "#9aa4b2"
    color = {"edge": "#3ddc97", "cloud-only": "#c084fc", "cascade": "#e05c6e",
             "select": "#f7a23b", "predictive": "#5b8cff", "oracle": "#e6e9ef"}
    def col(k):
        for key, c in color.items():
            if key in k:
                return c
        return MUTED
    pts = list(comp.items())
    W, H, pad = 560, 380, 60
    costs = [v["cost"] for _, v in pts]; quals = [v["quality"] for _, v in pts]
    cmin, cmax = min(costs), max(costs); qmin, qmax = min(quals + [0.4]), max(quals + [0.9])
    sx = lambda c: pad + (c - cmin) / (cmax - cmin or 1) * (W - 2 * pad)
    sy = lambda q: H - pad - (q - qmin) / (qmax - qmin or 1) * (H - 2 * pad)
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
           f'font-family="ui-monospace, Menlo, monospace"><rect width="{W}" height="{H}" fill="{BG}"/>',
           f'<text x="{W//2}" y="24" fill="{FG}" font-size="14" text-anchor="middle">predictive vs cascade routing (judged by claude-opus-5)</text>',
           f'<line x1="{pad}" y1="{H-pad}" x2="{W-pad}" y2="{H-pad}" stroke="{MUTED}"/>',
           f'<line x1="{pad}" y1="{pad}" x2="{pad}" y2="{H-pad}" stroke="{MUTED}"/>',
           f'<text x="{W//2}" y="{H-14}" fill="{MUTED}" font-size="11" text-anchor="middle">cost $/12 tasks</text>',
           f'<text x="16" y="{H//2}" fill="{MUTED}" font-size="11" transform="rotate(-90 16 {H//2})" text-anchor="middle">gold-judge quality</text>']
    for k, v in pts:
        x, y = sx(v["cost"]), sy(v["quality"])
        anchor, tx = ("end", x - 8) if x > W - 150 else ("start", x + 8)
        svg.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="5" fill="{col(k)}"/>')
        svg.append(f'<text x="{tx:.0f}" y="{y+3:.0f}" fill="{FG}" font-size="10" text-anchor="{anchor}">{k}</text>')
    svg.append("</svg>")
    (SHOTS / "predictive-pareto.svg").write_text("\n".join(svg))


if __name__ == "__main__":
    main()
