// On-device quality gate. Decides whether the LOCAL model's answer is good
// enough to keep, or whether this turn must escalate to the cloud. Same idea
// as the server-side gateway, but it runs on the client so the escalation
// decision itself never leaves the device.
//
// Escalation triggers, in order of how often they fire in practice:
//   1. schema invalid  (small models botch strict JSON)
//   2. low confidence   (uncertainty-aware escalation)
//   3. refusal          (model says it cannot answer)
//   4. context too long (prompt beyond the local model's usable window)

import type { EngineReply, EscalationReason, GateVerdict, RouterRequest } from "./types.ts";

export interface GateConfig {
  confidenceThreshold: number;   // e.g. 0.6
  localContextTokens: number;    // usable window of the on-device model
}

export const DEFAULT_GATE: GateConfig = {
  confidenceThreshold: 0.6,
  localContextTokens: 4096,
};

const REFUSAL_MARKERS = [
  "i can't", "i cannot", "i'm not able", "i am not able",
  "as an ai", "i don't have enough", "cannot help with that",
];

export function extractJson(text: string): unknown {
  const t = text.trim();
  try {
    return JSON.parse(t);
  } catch {
    const s = t.indexOf("{");
    const e = t.lastIndexOf("}");
    if (s !== -1 && e > s) return JSON.parse(t.slice(s, e + 1)); // may throw
    throw new SyntaxError("no JSON object found");
  }
}

export function validateSchema(
  text: string,
  schema: { required: string[]; types?: Record<string, string> },
): { ok: boolean; reason?: string } {
  let obj: unknown;
  try {
    obj = extractJson(text);
  } catch {
    return { ok: false, reason: "not valid JSON" };
  }
  if (typeof obj !== "object" || obj === null || Array.isArray(obj)) {
    return { ok: false, reason: "not a JSON object" };
  }
  const rec = obj as Record<string, unknown>;
  for (const key of schema.required) {
    if (!(key in rec)) return { ok: false, reason: `missing ${key}` };
    const want = schema.types?.[key];
    if (want && !typeOk(rec[key], want)) return { ok: false, reason: `bad type for ${key}` };
  }
  return { ok: true };
}

function typeOk(v: unknown, want: string): boolean {
  if (want === "string") return typeof v === "string";
  if (want === "number") return typeof v === "number";
  if (want === "boolean") return typeof v === "boolean";
  if (want === "array") return Array.isArray(v);
  if (want === "object") return typeof v === "object" && v !== null && !Array.isArray(v);
  return true;
}

// Cheap token estimate, ~4 chars/token. Good enough for a window check.
export function estimateTokens(text: string): number {
  return Math.max(1, Math.ceil(text.length / 4));
}

export function assessLocal(
  req: RouterRequest,
  reply: EngineReply,
  cfg: GateConfig = DEFAULT_GATE,
): GateVerdict {
  const reasons: EscalationReason[] = [];

  if (estimateTokens(req.prompt) > cfg.localContextTokens) {
    reasons.push("context_too_long");
  }

  let schemaOk = true;
  if (req.jsonSchema) {
    const r = validateSchema(reply.text, req.jsonSchema);
    schemaOk = r.ok;
    if (!r.ok) reasons.push("schema_invalid");
  }

  const low = reply.confidence < cfg.confidenceThreshold;
  if (low) reasons.push("low_confidence");

  const lc = reply.text.toLowerCase();
  if (REFUSAL_MARKERS.some((m) => lc.includes(m))) reasons.push("refusal");

  return {
    acceptable: reasons.length === 0,
    confidence: reply.confidence,
    schemaOk,
    reasons,
  };
}
