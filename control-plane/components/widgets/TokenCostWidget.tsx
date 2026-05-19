import { CostBucket } from "@/lib/cost";
import BarRow from "@/components/viz/BarRow";
import Donut from "@/components/viz/Donut";

interface Props {
  buckets: CostBucket[];
  total: number;
}

const PALETTE = [
  "var(--mlc-teal)",
  "var(--mlc-slate-500)",
  "var(--mlc-indigo-700)",
  "var(--mlc-sand-500)",
  "var(--mlc-peach-500)",
];
const BAR_TONES = ["mint", "slate", "peach", "sand", "mint"] as const;

export default function TokenCostWidget({ buckets, total }: Props) {
  if (buckets.length === 0)
    return <p className="muted">No api_calls rows yet.</p>;
  const segments = buckets.map((b, i) => ({
    value: b.totalCost,
    color: PALETTE[i % PALETTE.length],
  }));
  const maxCalls = Math.max(...buckets.map((b) => b.calls));
  return (
    <div style={{ display: "grid", gap: 14 }}>
      <div className="donut-row">
        <Donut
          segments={segments}
          size={120}
          thickness={20}
          label={`$${total.toFixed(2)}`}
          sub="TOTAL"
        />
        <div>
          <div className="label">Spend by model</div>
          <div style={{ marginTop: 8, display: "grid", gap: 5 }}>
            {buckets.map((b, i) => (
              <div
                key={b.modelId}
                style={{
                  display: "grid",
                  gridTemplateColumns: "10px 1fr auto",
                  alignItems: "center",
                  gap: 8,
                }}
              >
                <span
                  style={{
                    width: 8,
                    height: 8,
                    borderRadius: 2,
                    background: PALETTE[i % PALETTE.length],
                  }}
                />
                <span
                  className="mono muted"
                  style={{
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {b.modelId.split("/").pop()}
                </span>
                <span className="mono">${b.totalCost.toFixed(2)}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
      <div>
        <div className="label" style={{ marginBottom: 6 }}>
          Calls
        </div>
        {buckets.map((b, i) => (
          <BarRow
            key={b.modelId}
            name={b.modelId.split("/").pop() ?? b.modelId}
            value={b.calls}
            max={maxCalls}
            tone={BAR_TONES[i % BAR_TONES.length]}
          />
        ))}
      </div>
    </div>
  );
}
