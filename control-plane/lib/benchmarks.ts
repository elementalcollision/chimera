import fs from "node:fs";
import path from "node:path";
import { mindDir } from "./paths";

export type BenchmarkEnvelope = {
  mean_pct: number;
  sigma_pp: number;
  gate_pct: number;
};

export type Benchmark = {
  id: string;
  benchmark: string;
  config: string;
  n: number;
  headline_pct: number;
  envelope?: BenchmarkEnvelope;
  date: string;
  source_note: string;
  notes?: string;
};

export type BenchmarksLoadResult =
  | { ok: true; entries: Benchmark[] }
  | { ok: false; reason: "missing" | "malformed"; detail?: string };

function benchmarksPath(): string {
  return path.join(mindDir(), "benchmarks.json");
}

export function getBenchmarks(): BenchmarksLoadResult {
  const p = benchmarksPath();
  if (!fs.existsSync(p)) return { ok: false, reason: "missing" };
  try {
    const raw = fs.readFileSync(p, "utf8");
    const parsed = JSON.parse(raw);
    const entries = Array.isArray(parsed?.entries) ? parsed.entries : null;
    if (!entries) return { ok: false, reason: "malformed", detail: "missing entries[]" };
    return { ok: true, entries: entries as Benchmark[] };
  } catch (e) {
    return { ok: false, reason: "malformed", detail: e instanceof Error ? e.message : String(e) };
  }
}
