import Database from "better-sqlite3";
import fs from "node:fs";
import { dbPath } from "./paths";

let _db: Database.Database | null = null;

export function getDb(): Database.Database | null {
  if (_db) return _db;
  const p = dbPath();
  if (!fs.existsSync(p)) return null;
  _db = new Database(p, { readonly: true, fileMustExist: true });
  _db.pragma("query_only = ON");
  return _db;
}

export type Entity = {
  id: string;
  kind: string;
  name: string;
  kfm_state: string;
  state_entered_at_cycle: number;
  created_at: string;
};

export type ApiCall = {
  id: number;
  cycle: number;
  provider: string;
  model_id: string;
  input_tokens: number | null;
  output_tokens: number | null;
  latency_ms: number | null;
  finish_reason: string | null;
  error: string | null;
  created_at: string;
};

export type Mutation = {
  id: number;
  type: string;
  payload: string;
  status: string;
  reason: string | null;
  created_at: string;
};

export type ActivityRow = {
  cycle: number;
  cell_id: string;
  agent_id: string;
  activity_type: string;
  created_at: string;
};

export function listEntities(): Entity[] {
  const db = getDb();
  if (!db) return [];
  return db
    .prepare(
      "SELECT id, kind, name, kfm_state, state_entered_at_cycle, created_at FROM entities ORDER BY created_at DESC"
    )
    .all() as Entity[];
}

export function recentApiCalls(limit = 25): ApiCall[] {
  const db = getDb();
  if (!db) return [];
  return db
    .prepare(
      "SELECT id, cycle, provider, model_id, input_tokens, output_tokens, latency_ms, finish_reason, error, created_at FROM api_calls ORDER BY id DESC LIMIT ?"
    )
    .all(limit) as ApiCall[];
}

export function allApiCallCostHistoryRows(): Array<{
  model_id: string;
  input_tokens: number | null;
  output_tokens: number | null;
  created_at: string;
}> {
  const db = getDb();
  if (!db) return [];
  return db
    .prepare(
      "SELECT model_id, input_tokens, output_tokens, created_at FROM api_calls WHERE error IS NULL ORDER BY created_at ASC"
    )
    .all() as Array<{
      model_id: string;
      input_tokens: number | null;
      output_tokens: number | null;
      created_at: string;
    }>;
}

export function allApiCallTokenRows(): Array<{
  model_id: string;
  input_tokens: number | null;
  output_tokens: number | null;
}> {
  const db = getDb();
  if (!db) return [];
  return db
    .prepare(
      "SELECT model_id, input_tokens, output_tokens FROM api_calls WHERE error IS NULL"
    )
    .all() as Array<{
      model_id: string;
      input_tokens: number | null;
      output_tokens: number | null;
    }>;
}

// v4.54 (ADR 0073): rows from the last N minutes for cost-rate alarm.
// Same shape as allApiCallTokenRows but time-bounded; the caller passes
// to costByModel + totalCost from lib/cost.ts and divides by the window
// to get $/min. NULL-error filter mirrors the other readers.
export function apiCallTokenRowsLastMinutes(minutes: number): Array<{
  model_id: string;
  input_tokens: number | null;
  output_tokens: number | null;
}> {
  const db = getDb();
  if (!db) return [];
  // Bind as a string fragment because sqlite's datetime modifier doesn't
  // parametrize cleanly with bound integers — clamp to a safe range.
  // v4.57: wrap created_at in datetime() so the T-separator + +00:00 tz
  // that record_api_call writes normalizes to SQLite's expected shape.
  // Raw string compare would silently overcount; see ADR 0076.
  const m = Math.max(1, Math.min(1440, Math.floor(minutes)));
  return db
    .prepare(
      `SELECT model_id, input_tokens, output_tokens FROM api_calls ` +
      `WHERE error IS NULL AND datetime(created_at) >= datetime('now', '-${m} minutes')`
    )
    .all() as Array<{
      model_id: string;
      input_tokens: number | null;
      output_tokens: number | null;
    }>;
}

// v4.68 (ADR 0087): hot signatures — task_escalations grouped by
// signature with ≥ threshold failures. Mirrors the Python
// chimera.core.escalation.hot_signatures helper. The Python suite
// is the source of truth for the SQL shape; this TS query is the
// dashboard's mirror and the Python tests pin both.
export interface HotSignatureRow {
  signature: string;
  total_failures: number;
  tiers: string;       // comma-separated unique tier names
  first_cycle: number;
  last_cycle: number;
  last_finish_reason: string;
  excerpt: string;     // up to 120 chars of the most-recent task_text
}

export function hotSignatures(opts?: { threshold?: number; limit?: number }): HotSignatureRow[] {
  const db = getDb();
  if (!db) return [];
  const threshold = Math.max(1, opts?.threshold ?? 2);
  const limit = Math.max(1, Math.min(50, opts?.limit ?? 10));
  // Defensive: task_escalations exists from v4.46 onward; on older
  // DBs the query throws OperationalError, caught and returned [].
  try {
    const rows = db
      .prepare(
        `SELECT
            signature,
            COUNT(*) AS total_failures,
            GROUP_CONCAT(DISTINCT tier) AS tiers,
            MIN(cycle) AS first_cycle,
            MAX(cycle) AS last_cycle
         FROM task_escalations
         GROUP BY signature
         HAVING total_failures >= ?
         ORDER BY total_failures DESC, last_cycle DESC
         LIMIT ?`
      )
      .all(threshold, limit) as Array<{
        signature: string;
        total_failures: number;
        tiers: string | null;
        first_cycle: number;
        last_cycle: number;
      }>;
    if (rows.length === 0) return [];
    // For each signature, fetch the most-recent excerpt + finish_reason.
    const detailStmt = db.prepare(
      "SELECT finish_reason, task_text FROM task_escalations " +
      "WHERE signature = ? ORDER BY cycle DESC LIMIT 1"
    );
    return rows.map((r) => {
      const detail = detailStmt.get(r.signature) as
        | { finish_reason: string | null; task_text: string | null }
        | undefined;
      const text = (detail?.task_text ?? "").replace(/\n/g, " ");
      return {
        signature: r.signature,
        total_failures: r.total_failures,
        tiers: r.tiers ?? "",
        first_cycle: r.first_cycle,
        last_cycle: r.last_cycle,
        last_finish_reason: detail?.finish_reason ?? "",
        excerpt: text.slice(0, 120),
      };
    });
  } catch {
    return [];
  }
}

export function pendingMutations(): Mutation[] {
  const db = getDb();
  if (!db) return [];
  return db
    .prepare(
      "SELECT id, type, payload, status, reason, created_at FROM mutations WHERE status = 'pending' ORDER BY id DESC"
    )
    .all() as Mutation[];
}

export function allMutations(limit = 50): Mutation[] {
  const db = getDb();
  if (!db) return [];
  return db
    .prepare(
      "SELECT id, type, payload, status, reason, created_at FROM mutations ORDER BY id DESC LIMIT ?"
    )
    .all(limit) as Mutation[];
}

export function recentActivity(limit = 16): ActivityRow[] {
  const db = getDb();
  if (!db) return [];
  return db
    .prepare(
      "SELECT cycle, cell_id, agent_id, activity_type, created_at FROM agent_activity_log ORDER BY cycle DESC, cell_id LIMIT ?"
    )
    .all(limit) as ActivityRow[];
}

export type LadderOutcome = {
  cycle: number;
  tier: string;
  rung_model_id: string;
  outcome: string;
  task_type: string | null;
};

// ── v4.19: mutation queue health ────────────────────────────

export type QueueHealth = {
  counts: Record<string, number>;
  pending_oldest_age_seconds: number | null;
  pending_recurrence_max: number;
  pending_recurrence_total: number;
  approved_ratio: number | null;
};

export function queueHealth(): QueueHealth | null {
  const db = getDb();
  if (!db) return null;
  const countRows = db
    .prepare("SELECT status, COUNT(*) AS n FROM mutations GROUP BY status")
    .all() as { status: string; n: number }[];
  const counts: Record<string, number> = {};
  for (const r of countRows) counts[r.status] = r.n;

  // recurrence_count column added in v4.19 via additive migration; older DBs
  // may lack it, so be defensive.
  let recMax = 0;
  let recSum = 0;
  try {
    const r = db
      .prepare(
        "SELECT COALESCE(MAX(recurrence_count), 0) AS rmax, " +
          "COALESCE(SUM(recurrence_count), 0) AS rsum " +
          "FROM mutations WHERE status = 'pending'"
      )
      .get() as { rmax: number; rsum: number };
    recMax = r.rmax;
    recSum = r.rsum;
  } catch {
    /* column missing — leave zeros */
  }

  const oldest = db
    .prepare(
      "SELECT MIN(created_at) AS oldest FROM mutations WHERE status = 'pending'"
    )
    .get() as { oldest: string | null };
  let pending_oldest_age_seconds: number | null = null;
  if (oldest?.oldest) {
    const t0 = Date.parse(oldest.oldest);
    if (!Number.isNaN(t0)) {
      pending_oldest_age_seconds = Math.floor((Date.now() - t0) / 1000);
    }
  }

  const decided =
    (counts["approved"] || 0) +
    (counts["applied"] || 0) +
    (counts["rejected"] || 0) +
    (counts["failed"] || 0);
  const approved_ratio = decided > 0 ? (counts["applied"] || 0) / decided : null;

  return {
    counts,
    pending_oldest_age_seconds,
    pending_recurrence_max: recMax,
    pending_recurrence_total: recSum,
    approved_ratio,
  };
}

// ── v4.21: ontology audit ──────────────────────────────────

export type OntologyAudit = {
  current_cycle: number;
  total_entities: number;
  by_kind: Record<string, number>;
  by_state: Record<string, number>;
  stale_count: number;
  dead_count: number;
  deprecated_unarchived: number;
  reanchor_events_in_window: number;
  reanchor_window_cycles: number;
  stale_after_cycles: number;
  activity_window_cycles: number;
};

const _TERMINAL_STATES = ["ARCHIVED", "KILLED"];

export function ontologyAudit(opts?: {
  stale_after_cycles?: number;
  activity_window_cycles?: number;
  reanchor_window_cycles?: number;
}): OntologyAudit | null {
  const db = getDb();
  if (!db) return null;
  const stale_after_cycles = opts?.stale_after_cycles ?? 20;
  const activity_window_cycles = opts?.activity_window_cycles ?? 10;
  const reanchor_window_cycles = opts?.reanchor_window_cycles ?? 50;

  const cycRow = db
    .prepare("SELECT COALESCE(MAX(cycle), 0) AS c FROM agent_activity_log")
    .get() as { c: number };
  const current_cycle = cycRow.c;

  const total = (
    db.prepare("SELECT COUNT(*) AS n FROM entities").get() as { n: number }
  ).n;

  const by_kind: Record<string, number> = {};
  for (const r of db
    .prepare("SELECT kind, COUNT(*) AS n FROM entities GROUP BY kind")
    .all() as { kind: string; n: number }[]) {
    by_kind[r.kind] = r.n;
  }

  const by_state: Record<string, number> = {};
  for (const r of db
    .prepare("SELECT kfm_state, COUNT(*) AS n FROM entities GROUP BY kfm_state")
    .all() as { kfm_state: string; n: number }[]) {
    by_state[r.kfm_state] = r.n;
  }

  const stale_cutoff = current_cycle - stale_after_cycles;
  const placeholders = _TERMINAL_STATES.map(() => "?").join(",");
  const stale_count = (
    db
      .prepare(
        `SELECT COUNT(*) AS n FROM entities
         WHERE kfm_state NOT IN (${placeholders})
           AND state_entered_at_cycle <= ?`
      )
      .get(..._TERMINAL_STATES, stale_cutoff) as { n: number }
  ).n;

  const activity_cutoff = current_cycle - activity_window_cycles;
  const dead_count = (
    db
      .prepare(
        `SELECT COUNT(*) AS n FROM entities AS e
         WHERE e.kfm_state NOT IN (${placeholders})
           AND NOT EXISTS (
             SELECT 1 FROM agent_activity_log AS a
             WHERE a.cell_ref = e.id AND a.cycle > ?
           )`
      )
      .get(..._TERMINAL_STATES, activity_cutoff) as { n: number }
  ).n;

  const reanchor_cutoff = current_cycle - reanchor_window_cycles;
  const reanchor_events_in_window = (
    db
      .prepare(
        `SELECT COUNT(*) AS n FROM entity_transitions
         WHERE from_state = 'STABLE' AND to_state = 'DEPRECATED'
           AND operator_type = 'k' AND cycle > ?`
      )
      .get(reanchor_cutoff) as { n: number }
  ).n;

  return {
    current_cycle,
    total_entities: total,
    by_kind,
    by_state,
    stale_count,
    dead_count,
    deprecated_unarchived: by_state["DEPRECATED"] || 0,
    reanchor_events_in_window,
    reanchor_window_cycles,
    stale_after_cycles,
    activity_window_cycles,
  };
}

// ── v4.33: tool-fanout telemetry ────────────────────────────

export type ToolFanout = {
  total_calls_with_tools: number;
  serial: number;       // tool_uses_count == 1
  parallel_2: number;   // == 2
  parallel_3_plus: number; // >= 3
  max_fanout: number;
  parallel_share: number | null; // (parallel_2 + parallel_3_plus) / total, or null if empty
};

export type ToolFanoutByModel = {
  model_id: string;
  total: number;
  parallel: number;     // tool_uses_count >= 2
  parallel_share: number;
  avg_fanout: number;   // mean of tool_uses_count over rows with tool_uses_count > 0
};

export type ToolFanoutBucket = {
  cycle_bucket_start: number;
  cycle_bucket_end: number;
  total: number;
  parallel: number;
};

export function toolFanout(): ToolFanout | null {
  const db = getDb();
  if (!db) return null;
  let rows: Array<{ tool_uses_count: number | null; n: number }> = [];
  try {
    rows = db
      .prepare(
        "SELECT tool_uses_count, COUNT(*) AS n FROM api_calls " +
          "WHERE tool_uses_count IS NOT NULL AND tool_uses_count > 0 " +
          "GROUP BY tool_uses_count"
      )
      .all() as { tool_uses_count: number | null; n: number }[];
  } catch {
    return null;
  }
  let serial = 0;
  let parallel_2 = 0;
  let parallel_3_plus = 0;
  let max_fanout = 0;
  for (const r of rows) {
    const k = r.tool_uses_count ?? 0;
    if (k > max_fanout) max_fanout = k;
    if (k === 1) serial += r.n;
    else if (k === 2) parallel_2 += r.n;
    else if (k >= 3) parallel_3_plus += r.n;
  }
  const total = serial + parallel_2 + parallel_3_plus;
  const parallel_share =
    total > 0 ? (parallel_2 + parallel_3_plus) / total : null;
  return {
    total_calls_with_tools: total,
    serial,
    parallel_2,
    parallel_3_plus,
    max_fanout,
    parallel_share,
  };
}

// v4.37: rows for cost-per-fanout aggregation.
export function fanoutCostRows(): Array<{
  model_id: string;
  input_tokens: number | null;
  output_tokens: number | null;
  tool_uses_count: number | null;
}> {
  const db = getDb();
  if (!db) return [];
  try {
    return db
      .prepare(
        "SELECT model_id, input_tokens, output_tokens, tool_uses_count " +
          "FROM api_calls " +
          "WHERE error IS NULL " +
          "  AND tool_uses_count IS NOT NULL " +
          "  AND tool_uses_count > 0"
      )
      .all() as Array<{
      model_id: string;
      input_tokens: number | null;
      output_tokens: number | null;
      tool_uses_count: number | null;
    }>;
  } catch {
    return [];
  }
}

// v4.34: per-model fan-out breakdown.
export function toolFanoutByModel(limit = 8): ToolFanoutByModel[] {
  const db = getDb();
  if (!db) return [];
  let rows: Array<{
    model_id: string;
    total: number;
    parallel: number;
    sum_fanout: number;
  }>;
  try {
    rows = db
      .prepare(
        "SELECT model_id, " +
          "  COUNT(*) AS total, " +
          "  SUM(CASE WHEN tool_uses_count >= 2 THEN 1 ELSE 0 END) AS parallel, " +
          "  SUM(tool_uses_count) AS sum_fanout " +
          "FROM api_calls " +
          "WHERE tool_uses_count IS NOT NULL AND tool_uses_count > 0 " +
          "GROUP BY model_id " +
          "ORDER BY total DESC " +
          "LIMIT ?"
      )
      .all(limit) as typeof rows;
  } catch {
    return [];
  }
  return rows.map((r) => ({
    model_id: r.model_id,
    total: r.total,
    parallel: r.parallel,
    parallel_share: r.total > 0 ? r.parallel / r.total : 0,
    avg_fanout: r.total > 0 ? r.sum_fanout / r.total : 0,
  }));
}

// v4.34: fan-out trend bucketed by cycle.
export function toolFanoutHistory(opts?: {
  bucket_size?: number;
  n_buckets?: number;
}): ToolFanoutBucket[] {
  const db = getDb();
  if (!db) return [];
  const bucket_size = opts?.bucket_size ?? 5;
  const n_buckets = opts?.n_buckets ?? 12;
  if (bucket_size < 1 || n_buckets < 1) return [];

  let cycRow: { c: number };
  try {
    cycRow = db
      .prepare(
        "SELECT COALESCE(MAX(cycle), 0) AS c FROM api_calls " +
          "WHERE tool_uses_count IS NOT NULL AND tool_uses_count > 0"
      )
      .get() as { c: number };
  } catch {
    return [];
  }
  const end = cycRow.c + 1;
  const boundaries: Array<[number, number]> = [];
  for (let i = 0; i < n_buckets; i++) {
    const bend = end - i * bucket_size;
    boundaries.push([bend - bucket_size, bend]);
  }
  boundaries.reverse();

  const start = boundaries[0][0];
  const stop = boundaries[boundaries.length - 1][1];
  let rows: Array<{ cycle: number; tool_uses_count: number }>;
  try {
    rows = db
      .prepare(
        "SELECT cycle, tool_uses_count FROM api_calls " +
          "WHERE tool_uses_count IS NOT NULL AND tool_uses_count > 0 " +
          "AND cycle >= ? AND cycle < ?"
      )
      .all(start, stop) as typeof rows;
  } catch {
    return [];
  }
  return boundaries.map(([bstart, bend]) => {
    const inBucket = rows.filter((r) => r.cycle >= bstart && r.cycle < bend);
    return {
      cycle_bucket_start: bstart,
      cycle_bucket_end: bend,
      total: inBucket.length,
      parallel: inBucket.filter((r) => r.tool_uses_count >= 2).length,
    };
  });
}

// v4.51: per-model utilization for the engine-pressure widget.
export type ModelUtilization = {
  model_id: string;
  total: number;
  last_24h: number;
  last_hour: number;
  peak_per_cycle: number;
  // Per-cycle counts for the last N cycles, oldest first (sparkline data).
  series: number[];
};

export function modelUtilization(opts?: {
  series_cycles?: number;
  limit?: number;
}): ModelUtilization[] {
  const db = getDb();
  if (!db) return [];
  const series_cycles = opts?.series_cycles ?? 24;
  const limit = opts?.limit ?? 6;

  const cycRow = db
    .prepare("SELECT COALESCE(MAX(cycle), 0) AS c FROM api_calls")
    .get() as { c: number };
  const current_cycle = cycRow.c;
  const start_cycle = Math.max(0, current_cycle - series_cycles + 1);

  let rows: Array<{
    model_id: string;
    total: number;
    last_24h: number;
    last_hour: number;
    peak_per_cycle: number;
  }>;
  try {
    rows = db
      .prepare(
        "WITH per_cycle AS ( " +
          "  SELECT model_id, cycle, COUNT(*) AS n " +
          "  FROM api_calls GROUP BY model_id, cycle " +
          ") " +
          "SELECT a.model_id, " +
          "  COUNT(*) AS total, " +
          // v4.64: wrap created_at in datetime() — same fix as
          // apiCallTokenRowsLastMinutes (ADR 0076). Raw string compare
          // against datetime('now', ...) silently overcounts because
          // 'T' (84) > space (32) at position 10 of the ISO timestamp.
          "  SUM(CASE WHEN datetime(a.created_at) >= datetime('now', '-1 day')  THEN 1 ELSE 0 END) AS last_24h, " +
          "  SUM(CASE WHEN datetime(a.created_at) >= datetime('now', '-1 hour') THEN 1 ELSE 0 END) AS last_hour, " +
          "  COALESCE((SELECT MAX(n) FROM per_cycle p WHERE p.model_id = a.model_id), 0) AS peak_per_cycle " +
          "FROM api_calls a " +
          "GROUP BY a.model_id " +
          "ORDER BY total DESC " +
          "LIMIT ?"
      )
      .all(limit) as typeof rows;
  } catch {
    return [];
  }

  return rows.map((r) => {
    const seriesRows = db
      .prepare(
        "SELECT cycle, COUNT(*) AS n FROM api_calls " +
          "WHERE model_id = ? AND cycle >= ? GROUP BY cycle"
      )
      .all(r.model_id, start_cycle) as { cycle: number; n: number }[];
    const byCycle = new Map<number, number>();
    for (const row of seriesRows) byCycle.set(row.cycle, row.n);
    const series: number[] = [];
    for (let c = start_cycle; c <= current_cycle; c++) {
      series.push(byCycle.get(c) ?? 0);
    }
    return {
      model_id: r.model_id,
      total: r.total,
      last_24h: r.last_24h,
      last_hour: r.last_hour,
      peak_per_cycle: r.peak_per_cycle,
      series,
    };
  });
}

// v4.50: round-boundary latency snapshot.
export type RoundBoundaryStats = {
  samples: number;
  p50_ms: number;
  p95_ms: number;
  mean_ms: number;
  max_ms: number;
};

export function roundBoundaryStats(): RoundBoundaryStats | null {
  const db = getDb();
  if (!db) return null;
  let rows: Array<{ round_boundary_latency_ms: number }>;
  try {
    rows = db
      .prepare(
        "SELECT round_boundary_latency_ms FROM api_calls " +
          "WHERE round_boundary_latency_ms IS NOT NULL " +
          "ORDER BY round_boundary_latency_ms ASC"
      )
      .all() as typeof rows;
  } catch {
    return null;
  }
  if (rows.length === 0) return null;
  const ms = rows.map((r) => r.round_boundary_latency_ms);
  const sum = ms.reduce((a, b) => a + b, 0);
  const p50 = ms[Math.floor(ms.length * 0.5)];
  const p95 = ms[Math.min(ms.length - 1, Math.floor(ms.length * 0.95))];
  return {
    samples: ms.length,
    p50_ms: p50,
    p95_ms: p95,
    mean_ms: sum / ms.length,
    max_ms: ms[ms.length - 1],
  };
}

// ── v4.30: re-anchor history ────────────────────────────────

export type ReanchorBucket = {
  start_cycle: number;
  end_cycle: number;
  count: number;
};

export function reanchorHistory(opts?: {
  bucket_size?: number;
  n_buckets?: number;
}): ReanchorBucket[] {
  const db = getDb();
  if (!db) return [];
  const bucket_size = opts?.bucket_size ?? 10;
  const n_buckets = opts?.n_buckets ?? 12;
  if (bucket_size < 1 || n_buckets < 1) return [];

  // current_cycle = MAX(cycle) from agent_activity_log (matches Python audit).
  const cycRow = db
    .prepare("SELECT COALESCE(MAX(cycle), 0) AS c FROM agent_activity_log")
    .get() as { c: number };
  const current_cycle = cycRow.c;

  const end = current_cycle + 1;
  const boundaries: Array<[number, number]> = [];
  for (let i = 0; i < n_buckets; i++) {
    const bend = end - i * bucket_size;
    boundaries.push([bend - bucket_size, bend]);
  }
  boundaries.reverse(); // oldest first

  const start = boundaries[0][0];
  const stop = boundaries[boundaries.length - 1][1];
  const rows = db
    .prepare(
      `SELECT cycle FROM entity_transitions
       WHERE from_state = 'STABLE' AND to_state = 'DEPRECATED'
         AND operator_type = 'k'
         AND cycle >= ? AND cycle < ?`
    )
    .all(start, stop) as { cycle: number }[];
  const cycles = rows.map((r) => r.cycle);

  return boundaries.map(([bstart, bend]) => ({
    start_cycle: bstart,
    end_cycle: bend,
    count: cycles.filter((c) => c >= bstart && c < bend).length,
  }));
}

export function ladderOutcomesByTier(): Record<string, Record<string, number>> {
  const db = getDb();
  if (!db) return {};
  const rows = db
    .prepare("SELECT tier, outcome, COUNT(*) AS n FROM ladder_outcomes GROUP BY tier, outcome")
    .all() as { tier: string; outcome: string; n: number }[];
  const out: Record<string, Record<string, number>> = {};
  for (const r of rows) {
    out[r.tier] = out[r.tier] || {};
    out[r.tier][r.outcome] = r.n;
  }
  return out;
}
