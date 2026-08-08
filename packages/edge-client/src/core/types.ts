// Core types. Erasable-only TypeScript (no enums / namespaces) so the pure
// core runs under `node --test` type-stripping AND bundles under Vite.

export type Tier = "local" | "cloud";

export type Difficulty = "easy" | "medium" | "hard";

// Why a turn was sent to the cloud instead of answered on device. These are
// the "uncertainty-aware escalation" triggers from the SLM-first literature.
export type EscalationReason =
  | "classified_hard"     // the router judged it too hard for the local model up front
  | "low_confidence"      // local answer's confidence under threshold
  | "schema_invalid"      // local answer failed strict JSON validation
  | "refusal"             // local model said it cannot answer
  | "context_too_long"    // prompt exceeds the local model's usable window
  | "local_unavailable";  // no WebGPU / engine failed to load

export interface ChatMessage {
  role: "system" | "user" | "assistant";
  content: string;
}

export interface RouterRequest {
  prompt: string;
  // If set, the reply must be JSON satisfying this minimal schema.
  jsonSchema?: { required: string[]; types?: Record<string, string> };
  maxTokens?: number;
}

export interface EngineReply {
  text: string;
  model: string;
  tier: Tier;
  promptTokens: number;
  completionTokens: number;
  confidence: number;   // 0..1
  latencyMs: number;
  costUsd: number;      // local tier is 0; cloud reports real cost
}

export interface GateVerdict {
  acceptable: boolean;
  confidence: number;
  schemaOk: boolean;
  reasons: EscalationReason[];
}

export interface Attempt {
  tier: Tier;
  reply: EngineReply;
  verdict: GateVerdict;
}

export interface RouteResult {
  request: RouterRequest;
  final: EngineReply;
  attempts: Attempt[];
  difficulty: Difficulty;
  keptLocal: boolean;          // true if the on-device answer was accepted
  escalated: boolean;
  escalationReasons: EscalationReason[];
  costUsd: number;
  latencyMs: number;
  bytesToCloud: number;        // privacy: bytes that left the device (0 if kept local)
}
