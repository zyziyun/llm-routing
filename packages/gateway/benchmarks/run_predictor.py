"""A real predictive router: train a classifier to answer "can the cheap tier
handle this query?" and route from the query alone, with a confidence dial.

Experiment 5 showed the predictive *ceiling* dominates cascade but a naive k-NN
over 12 tasks realized only half of it. This does it properly: 48 varied prompts,
a real logistic-regression predictor over prompt embeddings, out-of-fold
evaluation, and a confidence-abstain knob (escalate when unsure). It is the
RouteLLM idea in miniature -- predict whether the cheap tier wins, route once.

Two phases. Labeling (paid, cached) runs the edge tier and a cheap cloud on every
prompt and scores both with the gold judge; training/eval (free) embeds the
prompts and learns the router. Re-runs reuse the label cache.

    ollama serve            # llama3.2:1b + nomic-embed-text pulled
    # ANTHROPIC_API_KEY + DEEPSEEK_API_KEY in ../.env
    python benchmarks/run_predictor.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import numpy as np

HERE = Path(__file__).resolve().parent
SHOTS = HERE.parent / "docs" / "screenshots"
OLLAMA = "http://localhost:11434/v1/chat/completions"
EMBED = "http://localhost:11434/api/embeddings"
ANTHROPIC = "https://api.anthropic.com/v1/messages"
DEEPSEEK = "https://api.deepseek.com/v1/chat/completions"
JUDGE = "claude-opus-5"
EDGE_MODEL, EDGE_PRICE = "llama3.2:1b", 0.0001          # $/1k, local equiv
CLOUD_MODEL, CLOUD_PRICE = "deepseek-chat", 0.0007      # $/1k, hosted open model
TAU = 0.7   # edge "suffices" if its gold-judge score clears this
FOLDS = 3


def _env() -> None:
    env = HERE.parent / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def gen_ollama(model, prompt):
    r = httpx.post(OLLAMA, json={"model": model, "messages": [{"role": "user", "content": prompt}],
                                 "max_tokens": 256, "temperature": 0.2}, timeout=600.0)
    r.raise_for_status(); d = r.json(); u = d.get("usage", {})
    return d["choices"][0]["message"]["content"], u.get("prompt_tokens", 0) + u.get("completion_tokens", 0)


def gen_deepseek(prompt):
    r = httpx.post(DEEPSEEK, headers={"Authorization": f"Bearer {os.environ['DEEPSEEK_API_KEY']}",
                                      "content-type": "application/json"},
                   json={"model": CLOUD_MODEL, "messages": [{"role": "user", "content": prompt}],
                         "max_tokens": 512, "temperature": 0.2}, timeout=600.0)
    r.raise_for_status(); d = r.json(); u = d.get("usage", {})
    return d["choices"][0]["message"]["content"], u.get("prompt_tokens", 0) + u.get("completion_tokens", 0)


def judge(question, answer):
    r = httpx.post(ANTHROPIC, headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"],
                                       "anthropic-version": "2023-06-01", "content-type": "application/json"},
                   json={"model": JUDGE, "max_tokens": 16, "thinking": {"type": "disabled"},
                         "system": "You are a strict grader. Output only a number from 0 to 1.",
                         "messages": [{"role": "user", "content": f"Rate how correct and relevant the ANSWER is "
                                       f"to the QUESTION, from 0 to 1.\n\nQUESTION:\n{question}\n\nANSWER:\n{answer}\n\nScore:"}]},
                   timeout=120.0)
    r.raise_for_status()
    import re
    t = next((b["text"] for b in r.json()["content"] if b.get("type") == "text"), "")
    m = re.search(r"[01](?:\.\d+)?", t)
    return max(0.0, min(1.0, float(m.group()))) if m else 0.0


def embed(text):
    r = httpx.post(EMBED, json={"model": "nomic-embed-text", "prompt": text}, timeout=120.0)
    r.raise_for_status(); return r.json()["embedding"]


def label(prompts):
    cache = HERE / "results_predictor_labels.json"
    if cache.exists():
        print("using cached labels")
        return json.loads(cache.read_text())
    print(f"labeling {len(prompts)} prompts (edge + deepseek + gold judge)...")
    rows = []
    for i, p in enumerate(prompts, 1):
        et, etok = gen_ollama(EDGE_MODEL, p)
        ct, ctok = gen_deepseek(p)
        es, cs = judge(p, et), judge(p, ct)
        rows.append({"prompt": p,
                     "edge_score": es, "edge_cost": round(etok / 1000 * EDGE_PRICE, 6),
                     "cloud_score": cs, "cloud_cost": round(ctok / 1000 * CLOUD_PRICE, 6),
                     "edge_ok": 1 if es >= TAU else 0})
        print(f"  [{i}/{len(prompts)}] edge={es:.2f} cloud={cs:.2f} edge_ok={rows[-1]['edge_ok']}")
    cache.write_text(json.dumps(rows, indent=2))
    return rows


# --- logistic regression (numpy) ---
def train_lr(X, y, epochs=400, lr=0.1, l2=1e-3):
    n, d = X.shape
    w = np.zeros(d); b = 0.0
    for _ in range(epochs):
        z = X @ w + b
        p = 1 / (1 + np.exp(-z))
        g = p - y
        w -= lr * (X.T @ g / n + l2 * w)
        b -= lr * g.mean()
    return w, b


def predict_lr(w, b, X):
    return 1 / (1 + np.exp(-(X @ w + b)))


def pca(X, dims):
    """Reduce to `dims` components so LR doesn't overfit with more features than
    samples. Unsupervised (no labels), so out-of-fold leakage is minimal."""
    Xc = X - X.mean(axis=0, keepdims=True)
    _, _, Vt = np.linalg.svd(Xc, full_matrices=False)
    return Xc @ Vt[:dims].T


def kfold_oof(X, y, k, model):
    """Out-of-fold P(edge_ok): each prediction from a model that didn't see it.
    Indices are SHUFFLED first -- the task set is ordered easy->hard, so unshuffled
    folds would test a class the model never trained on (accuracy below chance)."""
    n = len(y)
    idx = np.random.default_rng(0).permutation(n)
    folds = np.array_split(idx, k)
    p = np.zeros(n)
    for f in range(k):
        te = folds[f]; tr = np.concatenate([folds[j] for j in range(k) if j != f])
        if model == "lr":
            w, b = train_lr(X[tr], y[tr]); p[te] = predict_lr(w, b, X[te])
        else:  # knn cosine, k=5
            for i in te:
                sims = X[tr] @ X[i]
                nn = tr[np.argsort(-sims)[:5]]
                p[i] = y[nn].mean()
    return p


def main() -> None:
    _env()
    prompts = [json.loads(l)["prompt"] for l in (HERE / "tasks_big.jsonl").read_text().splitlines() if l.strip()]
    rows = label(prompts)
    y = np.array([r["edge_ok"] for r in rows], dtype=float)
    es = np.array([r["edge_score"] for r in rows]); ec = np.array([r["edge_cost"] for r in rows])
    cs = np.array([r["cloud_score"] for r in rows]); cc = np.array([r["cloud_cost"] for r in rows])
    print(f"\n{int(y.sum())}/{len(y)} prompts the edge tier handles (edge_ok), gold judge, TAU={TAU}")

    print("embedding prompts (nomic-embed-text, local)...")
    X = np.array([embed(p) for p in prompts])
    X = X / (np.linalg.norm(X, axis=1, keepdims=True) + 1e-9)
    Xp = pca(X, 16)   # LR trains on 16 PCA dims; kNN uses full-space cosine

    p_lr = kfold_oof(Xp, y, FOLDS, "lr")
    p_knn = kfold_oof(X, y, FOLDS, "knn")
    acc_lr = ((p_lr >= 0.5).astype(float) == y).mean()
    acc_knn = ((p_knn >= 0.5).astype(float) == y).mean()

    def route(mask_edge):  # mask_edge[i]=True -> route edge, else cloud
        q = np.where(mask_edge, es, cs); c = np.where(mask_edge, ec, cc)
        return round(q.mean(), 3), round(c.sum(), 6), int(mask_edge.sum())

    strategies = {}
    strategies["edge-only"] = route(np.ones(len(y), bool))
    strategies["cloud-only"] = route(np.zeros(len(y), bool))
    # cascade: run edge, escalate on gate miss -> pays edge always + cloud on misses
    casc_q = np.where(y == 1, es, cs); casc_c = ec + np.where(y == 1, 0.0, cc)
    strategies["cascade (pays edge then escalates)"] = (round(casc_q.mean(), 3), round(casc_c.sum(), 6), int(y.sum()))
    strategies["oracle (route-once perfect)"] = route(y == 1)
    for thr in (0.4, 0.5, 0.6, 0.7):
        strategies[f"predictive-LR@{thr}"] = route(p_lr >= thr)
    strategies["predictive-kNN@0.5"] = route(p_knn >= 0.5)

    out = {"tau": TAU, "n": len(y), "edge_ok_count": int(y.sum()),
           "acc_lr": round(acc_lr, 3), "acc_knn": round(acc_knn, 3),
           "strategies": {k: {"quality": v[0], "cost": v[1], "routed_edge": v[2]} for k, v in strategies.items()}}
    (HERE / "results_predictor.json").write_text(json.dumps(out, indent=2))
    _chart(strategies)

    print(f"\npredictor accuracy (out-of-fold): LR {acc_lr*100:.0f}%  vs  kNN {acc_knn*100:.0f}%")
    print(f"\n  {'strategy':<34}{'quality':>9}{'cost$':>10}{'edge/48':>9}")
    for k, (q, c, e) in strategies.items():
        print(f"  {k:<34}{q:>9.2f}{c:>10.5f}{e:>7}/48")


def _chart(strategies) -> None:
    SHOTS.mkdir(parents=True, exist_ok=True)
    BG, FG, MUTED, GREEN, PURPLE, BLUE, ORANGE = "#0f1115", "#e6e9ef", "#9aa4b2", "#3ddc97", "#c084fc", "#5b8cff", "#f7a23b"
    def color(k):
        if "edge-only" in k: return GREEN
        if "cloud-only" in k: return PURPLE
        if "cascade" in k: return "#e05c6e"
        if "oracle" in k: return FG
        if "kNN" in k: return ORANGE
        return BLUE
    pts = list(strategies.items())
    W, H, pad = 580, 380, 62
    costs = [v[1] for _, v in pts]; quals = [v[0] for _, v in pts]
    cmin, cmax = min(costs), max(costs); qmin, qmax = min(quals + [0.4]), max(quals + [1.0])
    sx = lambda c: pad + (c - cmin) / (cmax - cmin or 1) * (W - 2 * pad)
    sy = lambda q: H - pad - (q - qmin) / (qmax - qmin or 1) * (H - 2 * pad)
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
           f'font-family="ui-monospace, Menlo, monospace"><rect width="{W}" height="{H}" fill="{BG}"/>',
           f'<text x="{W//2}" y="24" fill="{FG}" font-size="14" text-anchor="middle">predictive routing: trained LR vs cascade / kNN / oracle</text>',
           f'<line x1="{pad}" y1="{H-pad}" x2="{W-pad}" y2="{H-pad}" stroke="{MUTED}"/>',
           f'<line x1="{pad}" y1="{pad}" x2="{pad}" y2="{H-pad}" stroke="{MUTED}"/>',
           f'<text x="{W//2}" y="{H-14}" fill="{MUTED}" font-size="11" text-anchor="middle">cost $/48 tasks</text>',
           f'<text x="16" y="{H//2}" fill="{MUTED}" font-size="11" transform="rotate(-90 16 {H//2})" text-anchor="middle">gold-judge quality</text>']
    lr = sorted([(k, v) for k, v in pts if "predictive-LR" in k], key=lambda kv: kv[1][1])
    if len(lr) > 1:
        d = " ".join(f"{sx(v[1]):.0f},{sy(v[0]):.0f}" for _, v in lr)
        svg.append(f'<polyline points="{d}" fill="none" stroke="{BLUE}" stroke-width="1.5" opacity="0.6"/>')
    for k, v in pts:
        x, y = sx(v[1]), sy(v[0])
        anchor, tx = ("end", x - 8) if x > W - 150 else ("start", x + 8)
        svg.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="5" fill="{color(k)}"/>')
        svg.append(f'<text x="{tx:.0f}" y="{y+3:.0f}" fill="{FG}" font-size="9" text-anchor="{anchor}">{k}</text>')
    svg.append("</svg>")
    (SHOTS / "predictor-pareto.svg").write_text("\n".join(svg))


if __name__ == "__main__":
    main()
