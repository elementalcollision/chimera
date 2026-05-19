import { effectivePrices } from "./cost";

export interface CostHistoryPoint {
  /** Hour bucket start (ISO 8601). */
  hour: string;
  /** Dollars spent in this hour, summed across all models. */
  cost: number;
}

interface Row {
  model_id: string;
  input_tokens: number | null;
  output_tokens: number | null;
  created_at: string;
}

/**
 * Bucket api_calls into hourly cost totals.
 * Returns the last `hours` buckets (default 24) including empty ones.
 */
export function costHistory(rows: Row[], hours = 24): CostHistoryPoint[] {
  const prices = effectivePrices();
  const buckets = new Map<string, number>();
  for (const r of rows) {
    const hour = r.created_at.slice(0, 13) + ":00:00Z"; // YYYY-MM-DDTHH
    const price = prices[r.model_id];
    if (!price) continue;
    const inT = r.input_tokens ?? 0;
    const outT = r.output_tokens ?? 0;
    const cost =
      (inT / 1_000_000) * price.inputCostPerMtok +
      (outT / 1_000_000) * price.outputCostPerMtok;
    buckets.set(hour, (buckets.get(hour) || 0) + cost);
  }
  // Sort + return the last N hours (oldest → newest).
  const sorted = [...buckets.entries()].sort(([a], [b]) => (a < b ? -1 : 1));
  return sorted.slice(-hours).map(([hour, cost]) => ({ hour, cost }));
}
