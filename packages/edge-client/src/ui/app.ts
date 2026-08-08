// UI wiring. Pure DOM, no framework, so the teaching focus stays on the
// routing logic rather than a component library. Renders the per-request
// decision trail and a live session panel: local share, bytes kept private,
// and cost saved versus cloud-only.

import { EdgeRouter } from "../core/router.ts";
import { accumulate, costSavedPct, emptyMetrics, localShare, type SessionMetrics } from "../core/metrics.ts";
import type { RouteResult } from "../core/types.ts";

const CLOUD_UNIT_COST = 0.005; // counterfactual per-request cloud cost for savings math

export function mountApp(router: EdgeRouter, statusText: string) {
  const $ = (id: string) => document.getElementById(id)!;
  ($("status") as HTMLElement).innerHTML = statusText;

  let metrics = emptyMetrics();
  renderMetrics(metrics);

  ($("send") as HTMLButtonElement).addEventListener("click", async () => {
    const promptEl = $("prompt") as HTMLTextAreaElement;
    const prompt = promptEl.value.trim();
    if (!prompt) return;
    const wantSchema = ($("schema") as HTMLInputElement).checked;

    const btn = $("send") as HTMLButtonElement;
    btn.disabled = true;
    btn.textContent = "Routing…";

    const req = {
      prompt,
      jsonSchema: wantSchema
        ? { required: ["answer", "confidence"], types: { answer: "string", confidence: "number" } }
        : undefined,
    };

    try {
      const result = await router.route(req);
      metrics = accumulate(metrics, result, CLOUD_UNIT_COST);
      renderResult(result);
      renderMetrics(metrics);
    } catch (e) {
      ($("out") as HTMLElement).textContent = `error: ${(e as Error).message}`;
      ($("answer") as HTMLElement).classList.remove("hidden");
    } finally {
      btn.disabled = false;
      btn.textContent = "Route";
    }
  });

  function renderResult(r: RouteResult) {
    ($("answer") as HTMLElement).classList.remove("hidden");
    const trail = r.attempts
      .map((a) => `<span class="pill ${a.tier}">${a.tier}${a.verdict.acceptable ? " ✓" : " ✗"}</span>`)
      .join("");
    const priv = r.keptLocal
      ? `<span class="pill local">0 bytes left device</span>`
      : `<span class="pill cloud">${r.bytesToCloud} bytes → cloud</span>`;
    const why = r.escalated ? `<span class="pill cloud">why: ${r.escalationReasons.join(", ")}</span>` : "";
    ($("trail") as HTMLElement).innerHTML =
      `<span class="pill">difficulty: ${r.difficulty}</span>${trail}${priv}${why}`;
    ($("out") as HTMLElement).textContent = r.final.text;
  }

  function renderMetrics(m: SessionMetrics) {
    const stat = (b: string, s: string) => `<div class="stat"><b>${b}</b><span>${s}</span></div>`;
    ($("metrics") as HTMLElement).innerHTML =
      stat(`${Math.round(localShare(m) * 100)}%`, `answered on device (${m.keptLocal}/${m.total})`) +
      stat(`${m.bytesToCloud}`, "bytes that left the device") +
      stat(`${Math.round(costSavedPct(m))}%`, "cost saved vs cloud-only") +
      stat(`$${m.costUsd.toFixed(4)}`, "actual cloud spend");
  }
}
