import fs from "node:fs";
import path from "node:path";
import { stateDir } from "./paths";

export interface GraphSnapshot {
  generated_at: string;
  entities: Array<{ id: string; kind: string; name: string; kfm_state: string }>;
  skills: Array<{ name: string; deps: string[] | null; tools: string[] | null }>;
  proposed: Array<{ id: number; type: string; status: string; entity_kind: string; entity_name: string }>;
  activated: Array<{ id: number; skill: string }>;
  trusted: Array<{ from: string; to: string; verdict: string; drift_score: number; recorded_at: string }>;
}

export interface TrustJournalRecord {
  peer: string;
  decision: string;
  reason: string;
  drift_score: number | null;
  recorded_at: string;
}

function snapshotPath(): string {
  return process.env.CHIMERA_GRAPH_SNAPSHOT ||
    path.join(stateDir(), "chimera.graph.snapshot.json");
}

export function readGraphSnapshot(): GraphSnapshot | null {
  const p = snapshotPath();
  if (!fs.existsSync(p)) return null;
  try {
    return JSON.parse(fs.readFileSync(p, "utf-8")) as GraphSnapshot;
  } catch {
    return null;
  }
}

function trustJournalDir(): string {
  return process.env.CHIMERA_PEER_TRUST_JOURNAL_DIR ||
    path.join(stateDir(), "peer_trust_journal");
}

export interface PhaseTimings {
  cycle: number;
  completed_at: string;
  phase_times_ms: Record<string, number>;
}

export function readPhaseTimings(): PhaseTimings | null {
  const p = path.join(stateDir(), "phase_timings.json");
  if (!fs.existsSync(p)) return null;
  try {
    return JSON.parse(fs.readFileSync(p, "utf-8")) as PhaseTimings;
  } catch {
    return null;
  }
}

export function readTrustJournal(limit = 50): TrustJournalRecord[] {
  const d = trustJournalDir();
  if (!fs.existsSync(d)) return [];
  const out: TrustJournalRecord[] = [];
  for (const f of fs.readdirSync(d)) {
    if (!f.endsWith(".jsonl")) continue;
    const text = fs.readFileSync(path.join(d, f), "utf-8");
    for (const line of text.split("\n")) {
      const s = line.trim();
      if (!s) continue;
      try {
        out.push(JSON.parse(s) as TrustJournalRecord);
      } catch {
        // skip malformed line
      }
    }
  }
  out.sort((a, b) => b.recorded_at.localeCompare(a.recorded_at));
  return out.slice(0, limit);
}
