// On-device engine backed by WebLLM (@mlc-ai/web-llm). This is the real
// "edge": a quantized small model runs in the browser on WebGPU, weights
// cached after first download, inference fully local. Browser-only.
//
// Confidence is derived from token logprobs when the model returns them, which
// is the on-device uncertainty signal the gate uses to decide escalation.

import type { Engine } from "./types.ts";
import { estimateTokens } from "../core/gate.ts";
import type { EngineReply, RouterRequest } from "../core/types.ts";

// Small models that fit the browser memory ceiling. 1B for phones/weak GPUs,
// 3B when there is headroom. IDs are WebLLM's MLC-quantized model tags.
export const LOCAL_MODELS = {
  tiny: "Llama-3.2-1B-Instruct-q4f16_1-MLC",
  small: "Llama-3.2-3B-Instruct-q4f16_1-MLC",
  qwen: "Qwen2.5-1.5B-Instruct-q4f16_1-MLC",
} as const;

export type InitProgress = { progress: number; text: string };

export class WebLLMEngine implements Engine {
  tier = "local" as const;
  model: string;
  private engine: any = null;
  private loading: Promise<void> | null = null;
  private onProgress?: (p: InitProgress) => void;

  constructor(model: string = LOCAL_MODELS.tiny, onProgress?: (p: InitProgress) => void) {
    this.model = model;
    this.onProgress = onProgress;
  }

  // WebGPU capability gate. If false, the app must fall back to cloud-only.
  static webgpuAvailable(): boolean {
    return typeof navigator !== "undefined" && "gpu" in navigator;
  }

  async ready(): Promise<boolean> {
    if (!WebLLMEngine.webgpuAvailable()) return false;
    if (this.engine) return true;
    if (!this.loading) this.loading = this.load();
    try {
      await this.loading;
      return this.engine !== null;
    } catch {
      return false;
    }
  }

  private async load(): Promise<void> {
    // Dynamic import so a no-WebGPU build never pulls the WASM/WebGPU runtime.
    const webllm = await import("@mlc-ai/web-llm");
    this.engine = await webllm.CreateMLCEngine(this.model, {
      initProgressCallback: (r: any) =>
        this.onProgress?.({ progress: r.progress ?? 0, text: r.text ?? "" }),
    });
  }

  async complete(req: RouterRequest): Promise<EngineReply> {
    if (!(await this.ready())) throw new Error("WebLLM not ready");
    const t0 = performance.now();
    const messages = buildMessages(req);
    const res = await this.engine.chat.completions.create({
      messages,
      max_tokens: req.maxTokens ?? 512,
      temperature: 0.2,
      logprobs: true,
      top_logprobs: 1,
    });
    const choice = res.choices[0];
    const text: string = choice.message.content ?? "";
    return {
      text,
      model: this.model,
      tier: "local",
      promptTokens: res.usage?.prompt_tokens ?? estimateTokens(req.prompt),
      completionTokens: res.usage?.completion_tokens ?? estimateTokens(text),
      confidence: confidenceFromLogprobs(choice),
      latencyMs: Number((performance.now() - t0).toFixed(1)),
      costUsd: 0,
    };
  }

  async *stream(req: RouterRequest): AsyncIterable<string> {
    if (!(await this.ready())) throw new Error("WebLLM not ready");
    const chunks = await this.engine.chat.completions.create({
      messages: buildMessages(req),
      max_tokens: req.maxTokens ?? 512,
      temperature: 0.2,
      stream: true,
    });
    for await (const c of chunks) {
      const d = c.choices?.[0]?.delta?.content;
      if (d) yield d;
    }
  }
}

function buildMessages(req: RouterRequest) {
  const sys = req.jsonSchema
    ? `Respond with ONLY valid JSON containing keys: ${req.jsonSchema.required.join(", ")}.`
    : "You are a concise, helpful assistant.";
  return [
    { role: "system", content: sys },
    { role: "user", content: req.prompt },
  ];
}

// Map mean top-token logprob to a 0..1 confidence via exp(). Falls back to a
// conservative value so borderline answers escalate rather than pass silently.
function confidenceFromLogprobs(choice: any): number {
  const content = choice.logprobs?.content;
  if (Array.isArray(content) && content.length) {
    const lps = content.map((c: any) => c.logprob ?? 0);
    const mean = lps.reduce((a: number, b: number) => a + b, 0) / lps.length;
    return Number(Math.min(1, Math.exp(mean)).toFixed(3));
  }
  return 0.5;
}
