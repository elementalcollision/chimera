import { DriftLogRecord } from "@/lib/graph";

/**
 * Inline-SVG sparkline of the last N drift composites.
 * Pure render — no chart lib dependency.
 *
 * The two thresholds (warning, lockdown) are drawn as horizontal
 * guides at y = 0.20 and y = 0.30 so trend interpretation is in
 * context.
 */
export default function DriftSparklineWidget({
  records,
}: {
  records: DriftLogRecord[];
}) {
  if (records.length === 0)
    return <p className="text-zinc-500 italic">No drift readings yet.</p>;

  const width = 320;
  const height = 80;
  const padding = 4;
  const maxScore = Math.max(0.4, ...records.map((r) => r.composite_score));
  const scoreY = (s: number) =>
    height - padding - (s / maxScore) * (height - 2 * padding);

  const points = records
    .map((r, i) => {
      const x = padding + (i * (width - 2 * padding)) / Math.max(1, records.length - 1);
      const y = scoreY(r.composite_score);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  const latest = records[records.length - 1];
  const severityColour = {
    high: "text-red-500",
    medium: "text-amber-500",
    low: "text-emerald-500",
  }[latest.severity] ?? "text-zinc-500";

  return (
    <div>
      <div className="flex items-center gap-3 mb-2">
        <span className={`font-mono font-semibold ${severityColour}`}>
          {latest.composite_score.toFixed(3)}
        </span>
        <span className="text-zinc-500">cycle {latest.cycle}</span>
        <span className="text-zinc-500">severity={latest.severity}</span>
        <span className="text-zinc-500">→ {latest.action}</span>
      </div>
      <svg width={width} height={height} className="block">
        <line
          x1={padding}
          y1={scoreY(0.2)}
          x2={width - padding}
          y2={scoreY(0.2)}
          stroke="currentColor"
          strokeOpacity="0.2"
          strokeDasharray="2 2"
        />
        <line
          x1={padding}
          y1={scoreY(0.3)}
          x2={width - padding}
          y2={scoreY(0.3)}
          stroke="currentColor"
          strokeOpacity="0.4"
          strokeDasharray="2 2"
        />
        <polyline
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          points={points}
        />
        {records.map((r, i) => {
          const x =
            padding + (i * (width - 2 * padding)) / Math.max(1, records.length - 1);
          const y = scoreY(r.composite_score);
          return <circle key={i} cx={x} cy={y} r="1.5" fill="currentColor" />;
        })}
      </svg>
      <div className="text-zinc-500 mt-1">
        {records.length} reading(s) · last @ {latest.recorded_at}
      </div>
    </div>
  );
}
