import fs from "node:fs";
import path from "node:path";
import matter from "gray-matter";
import { mindDir, trustStatePath } from "./paths";

export type Heartbeat = {
  cycle: number;
  session_started_at: string | null;
  trust_tier: string;
  status: string;
  model_usage: Record<string, number>;
  last_drift_score: number | null;
  body: string;
};

export function readHeartbeat(): Heartbeat | null {
  const p = path.join(mindDir(), "HEARTBEAT.md");
  if (!fs.existsSync(p)) return null;
  const raw = fs.readFileSync(p, "utf8");
  const parsed = matter(raw);
  const fm = parsed.data || {};
  return {
    cycle: Number(fm.cycle ?? 0),
    session_started_at: (fm.session_started_at ?? null) as string | null,
    trust_tier: String(fm.trust_tier ?? "T0"),
    status: String(fm.status ?? "dormant"),
    model_usage: (fm.model_usage ?? {}) as Record<string, number>,
    last_drift_score: (fm.last_drift_score ?? null) as number | null,
    body: parsed.content,
  };
}

export function readMindFile(name: string): string | null {
  const p = path.join(mindDir(), name);
  if (!fs.existsSync(p)) return null;
  return fs.readFileSync(p, "utf8");
}

export type TrustState = {
  current_tier: number;
  tier_entered_at: string;
  last_readiness: number;
  history: { timestamp: string; kind: string; from_tier: number; to_tier: number; reason: string }[];
};

export function readTrustState(): TrustState | null {
  const p = trustStatePath();
  if (!fs.existsSync(p)) return null;
  try {
    return JSON.parse(fs.readFileSync(p, "utf8")) as TrustState;
  } catch {
    return null;
  }
}

const TIER_LABELS = ["LOCKED", "SUPERVISED", "UNLOCKED", "TRUSTED", "ADAPTIVE", "AUTONOMOUS"];

export function tierLabel(n: number): string {
  return TIER_LABELS[n] ?? `T${n}`;
}
