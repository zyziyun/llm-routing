// On-device PII redaction tests. No browser, no network. Run: node --test

import { test } from "node:test";
import assert from "node:assert/strict";

import { redact, hasPii } from "../src/core/redact.ts";
import { EdgeRouter } from "../src/core/router.ts";
import { MockLocalEngine } from "../src/engines/mock.ts";
import type { Engine } from "../src/engines/types.ts";
import type { EngineReply, RouterRequest } from "../src/core/types.ts";

test("detects and redacts common PII", () => {
  const r = redact("email me at jane.doe@acme.com or call (415) 555-0199");
  assert.equal(r.entities.find((e) => e.type === "email")?.count, 1);
  assert.equal(r.entities.find((e) => e.type === "phone")?.count, 1);
  assert.ok(!r.redacted.includes("jane.doe@acme.com"));
  assert.ok(r.redacted.includes("[EMAIL]"));
  assert.ok(r.redactedChars > 0);
});

test("credit card is Luhn-validated, random digits are not flagged", () => {
  assert.ok(hasPii("card 4242 4242 4242 4242"));      // valid Luhn
  assert.ok(!hasPii("order 1234 5678 9012 3456 xyz")); // fails Luhn
});

test("clean text yields no entities", () => {
  assert.equal(redact("what is the capital of france").entities.length, 0);
});

// Spy cloud engine that records exactly what prompt it received.
class SpyCloud implements Engine {
  tier = "cloud" as const;
  model = "spy";
  received = "";
  async ready() { return true; }
  async complete(req: RouterRequest): Promise<EngineReply> {
    this.received = req.prompt;
    return { text: "[cloud] ok", model: this.model, tier: "cloud",
      promptTokens: 1, completionTokens: 1, confidence: 0.95, latencyMs: 1, costUsd: 0.001 };
  }
}

test("PII is stripped on device before the prompt escalates", async () => {
  const spy = new SpyCloud();
  const router = new EdgeRouter(new MockLocalEngine(), spy);
  // A hard prompt escalates; it also carries an email that must not leave raw.
  const res = await router.route({
    prompt: "Design a distributed system and email the spec to bob@corp.com with reasoning.",
  });
  assert.equal(res.escalated, true);
  assert.ok(!spy.received.includes("bob@corp.com"), "raw email must not reach the cloud");
  assert.ok(spy.received.includes("[EMAIL]"));
  assert.equal(res.redactedEntities.find((e) => e.type === "email")?.count, 1);
});

test("locally answered turns need no redaction and leak nothing", async () => {
  const spy = new SpyCloud();
  const res = await new EdgeRouter(new MockLocalEngine(), spy).route({
    prompt: "Translate hello to Spanish.",
  });
  assert.equal(res.keptLocal, true);
  assert.equal(res.bytesToCloud, 0);
  assert.equal(res.redactedEntities.length, 0);
  assert.equal(spy.received, "");   // cloud never called
});
