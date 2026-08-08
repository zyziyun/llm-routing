// Deterministic mock engines. Two jobs:
//   1. Make the pure core testable under `node --test` with no browser.
//   2. Serve as the no-WebGPU fallback path so the app degrades gracefully.
//
// The local mock mimics a small model: solid on easy prompts, shaky on hard
// ones and on strict JSON, which is exactly what forces realistic escalation.

import type { Engine } from "./types.ts";
import { estimateTokens } from "../core/gate.ts";
import type { EngineReply, RouterRequest } from "../core/types.ts";

function unitHash(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return ((h >>> 0) % 1000) / 1000;
}

function hardness(prompt: string): number {
  const p = prompt.toLowerCase();
  let s = 0.2;
  for (const c of ["prove", "design", "distributed", "algorithm", "reason", "trade", "analyze", "complexity"]) {
    if (p.includes(c)) s += 0.25;
  }
  if (prompt.split(/\s+/).length > 40) s += 0.2;
  return Math.min(1, s);
}

export class MockLocalEngine implements Engine {
  tier = "local" as const;
  model = "mock-slm-1b";

  async ready(): Promise<boolean> {
    return true;
  }

  async complete(req: RouterRequest): Promise<EngineReply> {
    const h = hardness(req.prompt);
    const jitter = (unitHash(req.prompt) - 0.5) * 0.1;
    // Small model: competent on easy, weak on hard; JSON is extra hard.
    let competence = 0.85 - h * 0.6 + jitter;
    if (req.jsonSchema) competence -= 0.15;
    const confidence = Math.max(0, Math.min(1, Number(competence.toFixed(3))));
    const succeeds = confidence >= 0.6;

    const text = req.jsonSchema
      ? (succeeds ? mockJson(req) : "Sure, here is the JSON: { " + req.jsonSchema.required[0] + ": }")
      : (succeeds ? `[local] ${req.prompt.trim().slice(0, 60)} -> answer` : "I can't fully answer that.");

    const pt = estimateTokens(req.prompt);
    const ct = estimateTokens(text);
    return {
      text, model: this.model, tier: "local",
      promptTokens: pt, completionTokens: ct,
      confidence,
      latencyMs: 40 + ct * 1.5,   // on-device: no network, but modest GPU
      costUsd: 0,                 // electricity only
    };
  }
}

export class MockCloudEngine implements Engine {
  tier = "cloud" as const;
  model = "mock-frontier";

  async ready(): Promise<boolean> {
    return true;
  }

  async complete(req: RouterRequest): Promise<EngineReply> {
    const text = req.jsonSchema ? mockJson(req) : `[cloud] ${req.prompt.trim().slice(0, 60)} -> answer`;
    const pt = estimateTokens(req.prompt);
    const ct = estimateTokens(text);
    return {
      text, model: this.model, tier: "cloud",
      promptTokens: pt, completionTokens: ct,
      confidence: 0.95,
      latencyMs: 600 + ct * 2,          // network round-trip dominates
      costUsd: Number(((pt + ct) / 1000 * 0.01).toFixed(6)),
    };
  }
}

function mockJson(req: RouterRequest): string {
  const obj: Record<string, unknown> = {};
  for (const k of req.jsonSchema!.required) {
    const t = req.jsonSchema!.types?.[k] ?? "string";
    obj[k] = t === "number" ? 1 : t === "boolean" ? true : t === "array" ? [] : t === "object" ? {} : "value";
  }
  return JSON.stringify(obj);
}
