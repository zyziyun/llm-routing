// The on-device router. This is topology 2 from the gateway project: the
// routing decision AND the local model run on the client. The cloud is only
// touched when the local answer is rejected.
//
//   classify -> (hard? -> cloud) : (try local -> gate -> ok? keep : escalate)
//
// The headline property is privacy: for every request kept local, ZERO bytes
// leave the device. Only escalated turns reach the cloud. The router reports
// bytesToCloud so a UI can show exactly what left the machine.

import type { Engine } from "../engines/types.ts";
import { classify } from "./classifier.ts";
import { assessLocal, DEFAULT_GATE, estimateTokens, type GateConfig } from "./gate.ts";
import { redact } from "./redact.ts";
import type { RedactionEntity } from "./redact.ts";
import type {
  Attempt,
  EscalationReason,
  RouterRequest,
  RouteResult,
} from "./types.ts";

export interface RouterConfig {
  gate: GateConfig;
  // Skip the local attempt entirely when the classifier says "hard": it wastes
  // on-device compute and battery to run a model that will just be escalated.
  skipLocalOnHard: boolean;
  // Strip PII on device before a request is allowed to escalate to the cloud.
  redactBeforeEscalation: boolean;
}

export const DEFAULT_ROUTER: RouterConfig = {
  gate: DEFAULT_GATE,
  skipLocalOnHard: true,
  redactBeforeEscalation: true,
};

export class EdgeRouter {
  private local: Engine | null;
  private cloud: Engine;
  private cfg: RouterConfig;

  constructor(local: Engine | null, cloud: Engine, cfg: RouterConfig = DEFAULT_ROUTER) {
    this.local = local;
    this.cloud = cloud;
    this.cfg = cfg;
  }

  async route(req: RouterRequest): Promise<RouteResult> {
    const difficulty = classify(req);
    const attempts: Attempt[] = [];
    const escalationReasons: EscalationReason[] = [];
    let cost = 0;
    let latency = 0;

    const localUsable = this.local !== null && (await this.local.ready());
    const goStraightToCloud =
      !localUsable ||
      (this.cfg.skipLocalOnHard && difficulty === "hard");

    // ---- local attempt ----
    if (!goStraightToCloud && this.local) {
      try {
        const reply = await this.local.complete(req);
        const verdict = assessLocal(req, reply, this.cfg.gate);
        attempts.push({ tier: "local", reply, verdict });
        cost += reply.costUsd;
        latency += reply.latencyMs;
        if (verdict.acceptable) {
          return this.result(req, difficulty, attempts, [], cost, latency, 0, []);
        }
        escalationReasons.push(...verdict.reasons);
      } catch {
        escalationReasons.push("local_unavailable");
      }
    } else if (difficulty === "hard") {
      escalationReasons.push("classified_hard");
    } else {
      escalationReasons.push("local_unavailable");
    }

    // ---- cloud escalation ----
    // Redact PII on device first: the cloud only ever sees the stripped prompt.
    let cloudReq = req;
    let redactedEntities: RedactionEntity[] = [];
    if (this.cfg.redactBeforeEscalation) {
      const r = redact(req.prompt);
      if (r.entities.length) {
        cloudReq = { ...req, prompt: r.redacted };
        redactedEntities = r.entities;
      }
    }

    const cloudReply = await this.cloud.complete(cloudReq);
    const cloudVerdict = assessLocal(cloudReq, cloudReply, this.cfg.gate);
    attempts.push({ tier: "cloud", reply: cloudReply, verdict: cloudVerdict });
    cost += cloudReply.costUsd;
    latency += cloudReply.latencyMs;

    // Privacy accounting: only the escalated, redacted prompt left the box.
    const bytesToCloud = new TextEncoder().encode(cloudReq.prompt).length;

    return this.result(req, difficulty, attempts, escalationReasons, cost, latency, bytesToCloud, redactedEntities);
  }

  private result(
    req: RouterRequest,
    difficulty: RouteResult["difficulty"],
    attempts: Attempt[],
    escalationReasons: EscalationReason[],
    cost: number,
    latency: number,
    bytesToCloud: number,
    redactedEntities: RedactionEntity[],
  ): RouteResult {
    const final = attempts[attempts.length - 1].reply;
    const keptLocal = final.tier === "local";
    return {
      request: req,
      final,
      attempts,
      difficulty,
      keptLocal,
      escalated: !keptLocal,
      escalationReasons,
      costUsd: Number(cost.toFixed(6)),
      latencyMs: Number(latency.toFixed(1)),
      bytesToCloud,
      redactedEntities,
    };
  }
}

export { estimateTokens };
