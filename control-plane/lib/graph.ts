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

export interface PeerEntry {
  agent_id: string;
  version: string;
  capabilities: string[];
  pid: number;
  host: string;
  reach: { transport?: string; url?: string; command?: string[] };
  registered_at: string;
}

function peerRegistryDir(): string {
  if (process.env.CHIMERA_PEER_REGISTRY_DIR) return process.env.CHIMERA_PEER_REGISTRY_DIR;
  return path.join(process.env.HOME || ".", ".chimera", "peers");
}

export function readPeers(): PeerEntry[] {
  const d = peerRegistryDir();
  if (!fs.existsSync(d)) return [];
  const out: PeerEntry[] = [];
  for (const f of fs.readdirSync(d)) {
    if (!f.endsWith(".json")) continue;
    try {
      const obj = JSON.parse(fs.readFileSync(path.join(d, f), "utf-8"));
      out.push(obj as PeerEntry);
    } catch {
      // skip
    }
  }
  return out.sort((a, b) => (a.agent_id > b.agent_id ? 1 : -1));
}

export interface EmergenceCounts {
  localPeers: { name: string; observations: number }[];
  remotePeers: { host: string; peer: string; observations: number }[];
}

function emergenceJournalDir(): string {
  if (process.env.CHIMERA_PROTOCOL_JOURNAL_DIR) return process.env.CHIMERA_PROTOCOL_JOURNAL_DIR;
  return path.join(stateDir(), "protocol_journal");
}

function countLines(p: string): number {
  if (!fs.existsSync(p)) return 0;
  return fs.readFileSync(p, "utf-8").split("\n").filter((l) => l.trim()).length;
}

export function readEmergenceCounts(): EmergenceCounts {
  const d = emergenceJournalDir();
  const local: EmergenceCounts["localPeers"] = [];
  if (fs.existsSync(d)) {
    for (const f of fs.readdirSync(d)) {
      if (!f.endsWith(".jsonl")) continue;
      local.push({ name: f.replace(/\.jsonl$/, ""), observations: countLines(path.join(d, f)) });
    }
  }
  const remote: EmergenceCounts["remotePeers"] = [];
  const remoteRoot = path.join(d, "remote");
  if (fs.existsSync(remoteRoot)) {
    for (const host of fs.readdirSync(remoteRoot)) {
      const hostDir = path.join(remoteRoot, host);
      if (!fs.statSync(hostDir).isDirectory()) continue;
      for (const f of fs.readdirSync(hostDir)) {
        if (!f.endsWith(".jsonl")) continue;
        remote.push({
          host,
          peer: f.replace(/\.jsonl$/, ""),
          observations: countLines(path.join(hostDir, f)),
        });
      }
    }
  }
  return { localPeers: local.sort((a, b) => a.name.localeCompare(b.name)), remotePeers: remote };
}

export interface TrustGroupRow {
  peer: string;
  decisions: number;
  latest: TrustJournalRecord | null;
}

export function groupTrustJournal(records: TrustJournalRecord[]): TrustGroupRow[] {
  const groups = new Map<string, TrustJournalRecord[]>();
  for (const r of records) {
    if (!groups.has(r.peer)) groups.set(r.peer, []);
    groups.get(r.peer)!.push(r);
  }
  const out: TrustGroupRow[] = [];
  for (const [peer, rs] of groups) {
    const latest = rs.reduce<TrustJournalRecord | null>(
      (acc, r) => (!acc || r.recorded_at > acc.recorded_at ? r : acc), null,
    );
    out.push({ peer, decisions: rs.length, latest });
  }
  return out.sort((a, b) => a.peer.localeCompare(b.peer));
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
