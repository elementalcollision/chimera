// Production-health rollup (ADR 0182 dashboard consolidation).
//
// The canvas grew to 24 telemetry widgets — a debug console, not an
// operator's window. For the daily-production loop the operator needs to
// answer "is production health trending bad?" at a glance, not by scanning
// two dozen tiles. This module folds the health signals Chimera already
// emits — cost rate, drift, proposal-queue staleness, fragmentation
// failures, repeat-failure (hot) escalation signatures, and ontology audit
// flags — into a single worst-of verdict with a per-dimension breakdown.
//
// The underlying number is ALWAYS shown in each dimension's detail, so a
// heuristic status (e.g. the drift severity mapping) can never hide the raw
// value from the operator's judgement.
import { CostRate } from "@/lib/cost";
import { QueueHealth } from "@/lib/db";
import { DriftLogRecord } from "@/lib/graph";

export type HealthStatus = "green" | "amber" | "red" | "unknown";

export interface HealthDimension {
  key: string;
  label: string;
  status: HealthStatus;
  detail: string;
}

export interface HealthSummary {
  overall: HealthStatus;
  dimensions: HealthDimension[];
}

const RANK: Record<HealthStatus, number> = {
  unknown: 0,
  green: 1,
  amber: 2,
  red: 3,
};

// Worst-of: a dimension can only raise the verdict, never lower it. An
// "unknown" dimension (no data yet) never drags a real verdict down.
function worst(a: HealthStatus, b: HealthStatus): HealthStatus {
  return RANK[b] > RANK[a] ? b : a;
}

export interface HealthInputs {
  costRate: CostRate;
  drift: DriftLogRecord | null;
  queue: QueueHealth | null;
  fragmentationCount: number;
  hotSignatureCount: number;
  auditFlagged: number; // stale_count + dead_count
}

const STALE_PENDING_SECONDS = 86_400; // 1 day — mirrors the queue widget chip.

export function computeHealth(inp: HealthInputs): HealthSummary {
  const dims: HealthDimension[] = [];

  // Cost — reuse the established band thresholds (lib/cost.ts).
  dims.push({
    key: "cost",
    label: "Cost rate",
    status:
      inp.costRate.band === "off"
        ? "unknown"
        : inp.costRate.band === "green"
          ? "green"
          : inp.costRate.band, // "amber" | "red"
    detail:
      inp.costRate.band === "off"
        ? "no calls in window"
        : `$${inp.costRate.usdPerMin.toFixed(3)}/min (15m)`,
  });

  // Drift — heuristic on the severity token; raw composite always shown.
  if (!inp.drift) {
    dims.push({
      key: "drift",
      label: "Drift",
      status: "unknown",
      detail: "no drift records",
    });
  } else {
    const sev = (inp.drift.severity || "").toLowerCase();
    const status: HealthStatus = /crit|sever|high/.test(sev)
      ? "red"
      : /med|moder|warn|elev/.test(sev)
        ? "amber"
        : "green";
    dims.push({
      key: "drift",
      label: "Drift",
      status,
      detail: `composite ${inp.drift.composite_score.toFixed(2)}${
        sev ? ` (${sev})` : ""
      }, cycle ${inp.drift.cycle}`,
    });
  }

  // Proposal-queue staleness — mirrors the queue widget's 1-day chip.
  const age = inp.queue?.pending_oldest_age_seconds ?? null;
  dims.push({
    key: "queue",
    label: "Proposal queue",
    status: age !== null && age > STALE_PENDING_SECONDS ? "amber" : "green",
    detail:
      age === null
        ? "no pending"
        : `oldest pending ${Math.floor(age / 3600)}h`,
  });

  // Fragmentation failures — any is a real failure to surface.
  dims.push({
    key: "fragmentation",
    label: "Fragmentation",
    status: inp.fragmentationCount > 0 ? "red" : "green",
    detail:
      inp.fragmentationCount > 0
        ? `${inp.fragmentationCount} failure(s)`
        : "none",
  });

  // Repeat-failure (hot) escalation signatures.
  dims.push({
    key: "escalations",
    label: "Hot signatures",
    status: inp.hotSignatureCount > 0 ? "amber" : "green",
    detail:
      inp.hotSignatureCount > 0
        ? `${inp.hotSignatureCount} repeat-failure signature(s)`
        : "none",
  });

  // Ontology audit flags (stale + dead entities).
  dims.push({
    key: "ontology",
    label: "Ontology audit",
    status: inp.auditFlagged > 0 ? "amber" : "green",
    detail: inp.auditFlagged > 0 ? `${inp.auditFlagged} stale/dead` : "clean",
  });

  const overall = dims.reduce(
    (acc, d) => worst(acc, d.status),
    "unknown" as HealthStatus,
  );
  return { overall, dimensions: dims };
}
