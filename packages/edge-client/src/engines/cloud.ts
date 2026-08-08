// Cloud escalation engine. Calls an OpenAI-compatible gateway over HTTP.
//
// SECURITY, the senior point: a browser client must NEVER hold provider API
// keys, because anything shipped to the browser is public. So this does not
// call OpenAI directly. It calls YOUR gateway (the server-side project), which
// holds the provider keys and enforces auth, budgets, and rate limits. The
// browser only carries a short-lived, per-user gateway token.

import type { Engine } from "./types.ts";
import { estimateTokens } from "../core/gate.ts";
import type { EngineReply, RouterRequest } from "../core/types.ts";

export interface CloudConfig {
  baseUrl: string;          // e.g. https://llm-gateway-xxxx.run.app
  token: string;            // per-user gateway token, NOT a provider key
  unitCostUsd?: number;     // for the counterfactual cost display
}

export class CloudEngine implements Engine {
  tier = "cloud" as const;
  model = "gateway";
  private cfg: CloudConfig;

  constructor(cfg: CloudConfig) {
    this.cfg = cfg;
  }

  async ready(): Promise<boolean> {
    return Boolean(this.cfg.baseUrl && this.cfg.token);
  }

  async complete(req: RouterRequest): Promise<EngineReply> {
    const t0 = performance.now();
    const resp = await fetch(`${this.cfg.baseUrl}/v1/chat/completions`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${this.cfg.token}`,
      },
      body: JSON.stringify({
        messages: [{ role: "user", content: req.prompt }],
        json_schema: req.jsonSchema
          ? { required: req.jsonSchema.required, types: req.jsonSchema.types }
          : undefined,
        max_tokens: req.maxTokens ?? 512,
      }),
    });
    if (!resp.ok) throw new Error(`gateway ${resp.status}`);
    const data = await resp.json();
    const text: string = data.choices?.[0]?.message?.content ?? "";
    const gw = data.x_gateway ?? {};
    return {
      text,
      model: data.model ?? "gateway",
      tier: "cloud",
      promptTokens: data.usage?.prompt_tokens ?? estimateTokens(req.prompt),
      completionTokens: data.usage?.completion_tokens ?? estimateTokens(text),
      confidence: 0.95,   // trust the gateway's own quality gate on the cloud side
      latencyMs: Number((performance.now() - t0).toFixed(1)),
      costUsd: Number(gw.cost_usd ?? this.cfg.unitCostUsd ?? 0.005),
    };
  }
}
