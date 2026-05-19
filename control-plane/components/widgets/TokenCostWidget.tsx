import { CostBucket } from "@/lib/cost";

interface Props {
  buckets: CostBucket[];
  total: number;
}

/**
 * "Quantized" view of the api_calls table: per-model token count
 * multiplied by MODEL_PRICES to produce a $ figure. This is the
 * concrete example from the v4.11 spec — every widget should be
 * computable from data the agent already records.
 */
export default function TokenCostWidget({ buckets, total }: Props) {
  if (buckets.length === 0)
    return <p className="text-zinc-500 italic">No api_calls rows yet.</p>;
  return (
    <div>
      <div className="mb-2 text-sm">
        Total spend: <span className="font-mono font-semibold">${total.toFixed(4)}</span>
      </div>
      <table className="w-full">
        <thead className="text-left text-zinc-500">
          <tr>
            <th>model</th>
            <th className="text-right">calls</th>
            <th className="text-right">in tok</th>
            <th className="text-right">out tok</th>
            <th className="text-right">$</th>
          </tr>
        </thead>
        <tbody>
          {buckets.map((b) => (
            <tr key={b.modelId} className="border-t border-zinc-200 dark:border-zinc-800">
              <td className="py-1 pr-2 font-mono truncate max-w-[16rem]">{b.modelId}</td>
              <td className="text-right pr-2">{b.calls}</td>
              <td className="text-right pr-2">{b.inputTokens.toLocaleString()}</td>
              <td className="text-right pr-2">{b.outputTokens.toLocaleString()}</td>
              <td className="text-right font-mono">${b.totalCost.toFixed(4)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
