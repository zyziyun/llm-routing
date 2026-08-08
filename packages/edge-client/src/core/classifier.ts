// On-device difficulty classifier. Runs locally, cheaply, before any model
// call, and decides whether to even attempt the local model or go straight to
// cloud. Heuristic baseline; a WebGPU embedding classifier is a documented
// upgrade (see DESIGN.md). Pure and testable.

import type { Difficulty, RouterRequest } from "./types.ts";

const HARD_CUES = [
  "prove", "derive", "step by step", "reason", "trade-off", "tradeoff",
  "design", "architecture", "compare", "optimi", "edge case", "concurren",
  "distributed", "algorithm", "complexity", "why does", "analyze",
];
const EASY_CUES = [
  "translate", "capital of", "define", "spell", "convert", "format",
  "list the", "what is the", "summarize in one",
];

export function classify(req: RouterRequest): Difficulty {
  const p = req.prompt.toLowerCase();
  const words = p.split(/\s+/).filter(Boolean).length;

  let score = 0;
  for (const c of HARD_CUES) if (p.includes(c)) score += 2;
  for (const c of EASY_CUES) if (p.includes(c)) score -= 2;
  if (words > 60) score += 2;
  else if (words < 12) score -= 1;
  // Strict structured output over a long input trends harder for a small model.
  if (req.jsonSchema && words > 40) score += 1;

  if (score >= 3) return "hard";
  if (score <= -1) return "easy";
  return "medium";
}
