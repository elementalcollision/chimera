import { CostHistoryPoint } from "@/lib/cost-history";
import Sparkline from "@/components/viz/Sparkline";

interface Props {
  points: CostHistoryPoint[];
}

export default function CostOverTimeWidget({ points }: Props) {
  if (points.length === 0)
    return <p className="muted">No cost history yet.</p>;
  const values = points.map((p) => p.cost);
  const total = values.reduce((s, v) => s + v, 0);
  const peak = Math.max(...values);
  const last = values[values.length - 1];
  const firstHour = points[0].hour.slice(0, 16);
  const lastHour = points[points.length - 1].hour.slice(0, 16);
  return (
    <div style={{ display: "grid", gap: 10 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
        <div>
          <div className="label">total · {points.length}h</div>
          <div className="serif-num" style={{ fontSize: 28, marginTop: 2 }}>
            ${total.toFixed(2)}
          </div>
        </div>
        <div>
          <div className="label">peak hr</div>
          <div className="mono" style={{ fontSize: 13, marginTop: 4 }}>
            ${peak.toFixed(2)}
          </div>
        </div>
        <div>
          <div className="label">last hr</div>
          <div className="mono" style={{ fontSize: 13, marginTop: 4 }}>
            ${last.toFixed(2)}
          </div>
        </div>
      </div>
      <Sparkline values={values} color="var(--mlc-teal)" height={64} />
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          fontSize: 11,
          color: "var(--fg-3)",
        }}
      >
        <span>{firstHour}</span>
        <span>{lastHour}</span>
      </div>
    </div>
  );
}
