import fs from "node:fs";
import path from "node:path";
import { stateDir } from "./paths";

export interface FragmentationRow {
  cycle: number;
  task_text: string;
  rounds_used: number;
  tool_call_count: number;
  missing_artifacts: string[];
  recorded_at: string;
}

export function readFragmentation(limit = 20): FragmentationRow[] {
  const p = path.join(stateDir(), "fragmentation_log.jsonl");
  if (!fs.existsSync(p)) return [];
  const out: FragmentationRow[] = [];
  for (const line of fs.readFileSync(p, "utf-8").split("\n")) {
    const s = line.trim();
    if (!s) continue;
    try {
      out.push(JSON.parse(s) as FragmentationRow);
    } catch {
      // skip
    }
  }
  return out.slice(-limit).reverse();
}
