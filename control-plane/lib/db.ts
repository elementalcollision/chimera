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
