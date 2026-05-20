/**
 * Mirror of chimera/providers/tiers.py MODEL_TIERS pricing.
 *
 * v4.14: when state/tiers.json exists (written by
 * `chimera tiers --json`), it overrides the hand-kept MODEL_PRICES
 * below. The hand-kept map remains as the fresh-install fallback.
 */
import fs from "node:fs";
import path from "node:path";
import { stateDir } from "./paths";

export interface ModelPrice {
  /** $ per million input tokens */
  inputCostPerMtok: number;
  /** $ per million output tokens */
  outputCostPerMtok: number;
}

export const MODEL_PRICES: Record<string, ModelPrice> = {
  // Anthropic direct
  "claude-haiku-4-5-20251001": { inputCostPerMtok: 0.8, outputCostPerMtok: 4.0 },
  "claude-sonnet-4-6": { inputCostPerMtok: 3.0, outputCostPerMtok: 15.0 },
  "claude-opus-4-7": { inputCostPerMtok: 15.0, outputCostPerMtok: 75.0 },
  // OpenRouter ladder rungs
  "deepseek/deepseek-v4-flash": { inputCostPerMtok: 0.14, outputCostPerMtok: 0.28 },
  "qwen/qwen3.6-flash": { inputCostPerMtok: 0.25, outputCostPerMtok: 1.5 },
  "deepseek/deepseek-v4-pro": { inputCostPerMtok: 0.435, outputCostPerMtok: 0.87 },
  "qwen/qwen3.5-plus-20260420": { inputCostPerMtok: 0.4, outputCostPerMtok: 2.4 },
  "openai/gpt-5-pro": { inputCostPerMtok: 2.5, outputCostPerMtok: 10.0 },
  "google/gemini-3-pro": { inputCostPerMtok: 1.25, outputCostPerMtok: 5.0 },
  // Anthropic-routed OpenRouter slugs
  "anthropic/claude-haiku-4-5": { inputCostPerMtok: 0.8, outputCostPerMtok: 4.0 },
  "anthropic/claude-sonnet-4-6": { inputCostPerMtok: 3.0, outputCostPerMtok: 15.0 },
  "anthropic/claude-opus-4-7": { inputCostPerMtok: 15.0, outputCostPerMtok: 75.0 },
};

interface TiersSnapshot {
  generated_at: string;
  tiers: Record<string, Array<{
    model_id: string;
    openrouter_model_id?: string;
    input_cost_per_mtok: number;
    output_cost_per_mtok: number;
  }>>;
}

function loadSnapshotPrices(): Record<string, ModelPrice> | null {
  const p = path.join(stateDir(), "tiers.json");
  if (!fs.existsSync(p)) return null;
  try {
    const snap = JSON.parse(fs.readFileSync(p, "utf-8")) as TiersSnapshot;
    const out: Record<string, ModelPrice> = {};
    for (const rungs of Object.values(snap.tiers)) {
      for (const r of rungs) {
        const price: ModelPrice = {
          inputCostPerMtok: r.input_cost_per_mtok,
          outputCostPerMtok: r.output_cost_per_mtok,
        };
        out[r.model_id] = price;
        if (r.openrouter_model_id && r.openrouter_model_id !== r.model_id) {
          out[r.openrouter_model_id] = price;
        }
      }
    }
    return out;
  } catch {
    return null;
  }
}

export function effectivePrices(): Record<string, ModelPrice> {
  return loadSnapshotPrices() ?? MODEL_PRICES;
}

export interface CostBucket {
  modelId: string;
  calls: number;
  inputTokens: number;
  outputTokens: number;
  inputCost: number;
  outputCost: number;
  totalCost: number;
}

export function costByModel(
  rows: Array<{ model_id: string; input_tokens: number | null; output_tokens: number | null }>,
): CostBucket[] {
  const prices = effectivePrices();
  const buckets = new Map<string, CostBucket>();
  for (const r of rows) {
    const model = r.model_id;
    const price = prices[model];
    if (!buckets.has(model)) {
      buckets.set(model, {
        modelId: model,
        calls: 0,
        inputTokens: 0,
        outputTokens: 0,
        inputCost: 0,
        outputCost: 0,
        totalCost: 0,
      });
    }
    const b = buckets.get(model)!;
    b.calls += 1;
    const inT = r.input_tokens ?? 0;
    const outT = r.output_tokens ?? 0;
    b.inputTokens += inT;
    b.outputTokens += outT;
    if (price) {
      b.inputCost += (inT / 1_000_000) * price.inputCostPerMtok;
      b.outputCost += (outT / 1_000_000) * price.outputCostPerMtok;
    }
    b.totalCost = b.inputCost + b.outputCost;
  }
  return [...buckets.values()].sort((a, b) => b.totalCost - a.totalCost);
}

export function totalCost(buckets: CostBucket[]): number {
  return buckets.reduce((acc, b) => acc + b.totalCost, 0);
}

// v4.37: cost per fan-out bucket.
//
// Each row is one ACT API call. ``tool_uses_count`` is how many tool
// calls that one response emitted (1=serial, 2+=parallel batch). The
// model pays for input tokens once per response regardless of fan-out,
// so a 2-fan-out response amortizes input cost over 2 actions. This
// breakdown quantifies that.
export interface FanoutCostBucket {
  bucket: "1" | "2" | "3+";
  calls: number;
  toolCalls: number;       // sum of tool_uses_count
  totalCost: number;
  costPerCall: number;
  costPerToolCall: number;
}

export function costByFanout(
  rows: Array<{
    model_id: string;
    input_tokens: number | null;
    output_tokens: number | null;
    tool_uses_count: number | null;
  }>,
): FanoutCostBucket[] {
  const prices = effectivePrices();
  const init = (label: "1" | "2" | "3+"): FanoutCostBucket => ({
    bucket: label,
    calls: 0,
    toolCalls: 0,
    totalCost: 0,
    costPerCall: 0,
    costPerToolCall: 0,
  });
  const buckets: Record<"1" | "2" | "3+", FanoutCostBucket> = {
    "1": init("1"),
    "2": init("2"),
    "3+": init("3+"),
  };
  for (const r of rows) {
    const k = r.tool_uses_count ?? 0;
    if (k < 1) continue;
    const key: "1" | "2" | "3+" = k === 1 ? "1" : k === 2 ? "2" : "3+";
    const b = buckets[key];
    b.calls += 1;
    b.toolCalls += k;
    const price = prices[r.model_id];
    if (price) {
      const inT = r.input_tokens ?? 0;
      const outT = r.output_tokens ?? 0;
      b.totalCost +=
        (inT / 1_000_000) * price.inputCostPerMtok +
        (outT / 1_000_000) * price.outputCostPerMtok;
    }
  }
  for (const key of ["1", "2", "3+"] as const) {
    const b = buckets[key];
    b.costPerCall = b.calls > 0 ? b.totalCost / b.calls : 0;
    b.costPerToolCall = b.toolCalls > 0 ? b.totalCost / b.toolCalls : 0;
  }
  return [buckets["1"], buckets["2"], buckets["3+"]];
}
