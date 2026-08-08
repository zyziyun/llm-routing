// Offline eval: three strategies on the same cases, using mock engines so it
// runs anywhere with `node eval/run-eval.ts`. Compares the axes that matter
// for on-device routing: privacy (requests + bytes that leave the device),
// cost, latency, and quality (validity of the final answer).
//
//   local-only : never escalate. Cheapest + most private, but quality drops.
//   cloud-only : always escalate. Best quality, zero privacy, most expensive.
//   router     : local-first, escalate on the gate. The point of the project.

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import { EdgeRouter } from "../src/core/router.ts";
import { assessLocal, validateSchema } from "../src/core/gate.ts";
import { MockLocalEngine, MockCloudEngine } from "../src/engines/mock.ts";
import type { RouterRequest } from "../src/core/types.ts";

const here = dirname(fileURLToPath(import.meta.url));
const cases: RouterRequest[] = JSON.parse(readFileSync(join(here, "cases.json"), "utf8"));

function quality(req: RouterRequest, text: string, confidence: number): number {
  // Validity-based quality: strict JSON must validate; otherwise use the
  // acceptability signal. Same rule as the server-side gateway: for structured
  // tasks, measure validity, not preference.
  if (req.jsonSchema) return validateSchema(text, req.jsonSchema).ok ? 1 : 0;
  return confidence >= 0.6 ? 1 : 0;
}

async function run() {
  const local = new MockLocalEngine();
  const cloud = new MockCloudEngine();
  const router = new EdgeRouter(new MockLocalEngine(), new MockCloudEngine());

  const strat = {
    "local-only": { cost: 0, latency: 0, q: 0, toCloud: 0, bytes: 0 },
    "cloud-only": { cost: 0, latency: 0, q: 0, toCloud: 0, bytes: 0 },
    router: { cost: 0, latency: 0, q: 0, toCloud: 0, bytes: 0 },
  };

  for (const c of cases) {
    const lo = await local.complete(c);
    strat["local-only"].cost += lo.costUsd;
    strat["local-only"].latency += lo.latencyMs;
    strat["local-only"].q += quality(c, lo.text, lo.confidence);

    const cl = await cloud.complete(c);
    strat["cloud-only"].cost += cl.costUsd;
    strat["cloud-only"].latency += cl.latencyMs;
    strat["cloud-only"].q += quality(c, cl.text, cl.confidence);
    strat["cloud-only"].toCloud += 1;
    strat["cloud-only"].bytes += new TextEncoder().encode(c.prompt).length;

    const r = await router.route(c);
    strat.router.cost += r.costUsd;
    strat.router.latency += r.latencyMs;
    strat.router.q += quality(c, r.final.text, r.final.confidence);
    strat.router.toCloud += r.escalated ? 1 : 0;
    strat.router.bytes += r.bytesToCloud;
  }

  const n = cases.length;
  const pct = (x: number) => `${Math.round((x / n) * 100)}%`;
  const usd = (x: number) => `$${x.toFixed(5)}`;

  console.log(`cases: ${n}\n`);
  console.log(`${"strategy".padEnd(12)}${"quality".padStart(9)}${"toCloud".padStart(9)}${"bytesOut".padStart(10)}${"cost".padStart(10)}${"avg_ms".padStart(9)}`);
  console.log("-".repeat(59));
  for (const [name, s] of Object.entries(strat)) {
    console.log(
      name.padEnd(12) +
        pct(s.q).padStart(9) +
        `${s.toCloud}/${n}`.padStart(9) +
        `${s.bytes}`.padStart(10) +
        usd(s.cost).padStart(10) +
        (s.latency / n).toFixed(0).padStart(9),
    );
  }
  const saved = strat["cloud-only"].cost
    ? (1 - strat.router.cost / strat["cloud-only"].cost) * 100
    : 0;
  const privacy = strat["cloud-only"].bytes
    ? (1 - strat.router.bytes / strat["cloud-only"].bytes) * 100
    : 0;
  console.log("-".repeat(59));
  console.log(`router vs cloud-only:  cost -${saved.toFixed(0)}%,  bytes-off-device -${privacy.toFixed(0)}%`);
  console.log(
    "\nread: the router keeps most turns on device (privacy + cost), and buys\n" +
      "back the quality local-only loses by escalating only the hard/invalid ones.",
  );
}

run();
