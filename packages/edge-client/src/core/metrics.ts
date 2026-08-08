// Session metrics. The three numbers that make the on-device case: how much
// stayed private (never left the device), how much money the local tier saved
// versus cloud-only, and the tier mix. A UI reads this live.

import type { RouteResult } from "./types.ts";

export interface SessionMetrics {
  total: number;
  keptLocal: number;
  escalated: number;
  bytesToCloud: number;      // total bytes that left the device this session
  costUsd: number;           // actual spend (escalated turns only)
  cloudOnlyCostUsd: number;  // counterfactual: if every turn had gone to cloud
  piiRedacted: number;       // PII entities stripped on device before escalation
}

export function emptyMetrics(): SessionMetrics {
  return { total: 0, keptLocal: 0, escalated: 0, bytesToCloud: 0, costUsd: 0, cloudOnlyCostUsd: 0, piiRedacted: 0 };
}

export function accumulate(m: SessionMetrics, r: RouteResult, cloudUnitCostUsd: number): SessionMetrics {
  const pii = r.redactedEntities.reduce((a, e) => a + e.count, 0);
  return {
    total: m.total + 1,
    keptLocal: m.keptLocal + (r.keptLocal ? 1 : 0),
    escalated: m.escalated + (r.escalated ? 1 : 0),
    bytesToCloud: m.bytesToCloud + r.bytesToCloud,
    costUsd: Number((m.costUsd + r.costUsd).toFixed(6)),
    // Counterfactual: charge every request the cloud unit cost.
    cloudOnlyCostUsd: Number((m.cloudOnlyCostUsd + cloudUnitCostUsd).toFixed(6)),
    piiRedacted: m.piiRedacted + pii,
  };
}

export function localShare(m: SessionMetrics): number {
  return m.total === 0 ? 0 : m.keptLocal / m.total;
}

export function costSavedPct(m: SessionMetrics): number {
  if (m.cloudOnlyCostUsd === 0) return 0;
  return (1 - m.costUsd / m.cloudOnlyCostUsd) * 100;
}
