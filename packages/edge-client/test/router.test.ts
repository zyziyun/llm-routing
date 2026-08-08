// Pure-core tests. No browser, no WebGPU, no network. Run:
//   node --test
// (Node 22.6+/24 strips TS types; erasable-only core makes this work.)

import { test } from "node:test";
import assert from "node:assert/strict";

import { EdgeRouter } from "../src/core/router.ts";
import { classify } from "../src/core/classifier.ts";
import { validateSchema, assessLocal } from "../src/core/gate.ts";
import { MockLocalEngine, MockCloudEngine } from "../src/engines/mock.ts";
import { emptyMetrics, accumulate, localShare, costSavedPct } from "../src/core/metrics.ts";

function router() {
  return new EdgeRouter(new MockLocalEngine(), new MockCloudEngine());
}

test("classifier labels easy vs hard", () => {
  assert.equal(classify({ prompt: "Translate hello to French." }), "easy");
  assert.equal(
    classify({ prompt: "Prove step by step why this distributed algorithm is correct and analyze its complexity." }),
    "hard",
  );
});

test("easy prompt is answered on device and never leaves the machine", async () => {
  const r = await router().route({ prompt: "What is the capital of France?" });
  assert.equal(r.keptLocal, true);
  assert.equal(r.final.tier, "local");
  assert.equal(r.bytesToCloud, 0);      // privacy: nothing left the device
  assert.equal(r.costUsd, 0);
});

test("hard prompt skips local and escalates to cloud", async () => {
  const r = await router().route({
    prompt: "Design a distributed rate limiter and reason about the consistency trade-offs.",
  });
  assert.equal(r.difficulty, "hard");
  assert.equal(r.keptLocal, false);
  assert.equal(r.final.tier, "cloud");
  assert.ok(r.escalationReasons.includes("classified_hard"));
  assert.ok(r.bytesToCloud > 0);
});

test("strict JSON that the local model botches escalates and ends valid", async () => {
  const schema = { required: ["service", "root_cause"], types: { service: "string", root_cause: "string" } };
  const r = await router().route({
    prompt: "Extract the failing service and root cause from this incident log and return strict JSON.",
    jsonSchema: schema,
  });
  assert.equal(r.final.tier, "cloud");
  assert.ok(validateSchema(r.final.text, schema).ok);
});

test("local_unavailable falls back to cloud", async () => {
  const r = await new EdgeRouter(null, new MockCloudEngine()).route({ prompt: "hello there friend" });
  assert.equal(r.final.tier, "cloud");
  assert.ok(r.escalationReasons.includes("local_unavailable"));
});

test("schema validator rejects prose-wrapped broken JSON", () => {
  const v = validateSchema("Sure! Here is the JSON: { name: }", { required: ["name"] });
  assert.equal(v.ok, false);
});

test("gate flags low confidence", () => {
  const verdict = assessLocal(
    { prompt: "x" },
    { text: "meh", model: "m", tier: "local", promptTokens: 1, completionTokens: 1, confidence: 0.3, latencyMs: 1, costUsd: 0 },
  );
  assert.equal(verdict.acceptable, false);
  assert.ok(verdict.reasons.includes("low_confidence"));
});

test("metrics track privacy and cost savings", async () => {
  const rr = router();
  let m = emptyMetrics();
  const prompts = [
    "What is the capital of France?",
    "Translate hello to Spanish.",
    "Design a distributed cache and analyze the trade-offs.",
  ];
  for (const p of prompts) {
    const res = await rr.route({ prompt: p });
    m = accumulate(m, res, 0.01);
  }
  assert.equal(m.total, 3);
  assert.ok(m.keptLocal >= 2);            // the two easy ones stayed local
  assert.ok(localShare(m) >= 0.66);
  assert.ok(costSavedPct(m) > 0);         // local turns avoided cloud spend
});
