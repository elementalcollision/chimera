interface Props {
  values: number[];
  color?: string;
  height?: number;
  fill?: boolean;
  baseline?: number | null;
}

export default function Sparkline({
  values,
  color = "var(--mlc-teal)",
  height = 36,
  fill = true,
  baseline = null,
}: Props) {
  if (!values || values.length === 0) return null;
  const w = 200;
  const h = height;
  const pad = 2;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const step = (w - pad * 2) / (values.length - 1 || 1);
  const points = values.map((v, i) => {
    const x = pad + i * step;
    const y = pad + (h - pad * 2) * (1 - (v - min) / range);
    return [x, y] as const;
  });
  const path = points
    .map(([x, y], i) => (i === 0 ? `M${x},${y}` : `L${x},${y}`))
    .join(" ");
  const last = points[points.length - 1];
  const first = points[0];
  const area = `${path} L${last[0]},${h} L${first[0]},${h} Z`;
  let baselineY: number | null = null;
  if (baseline != null) {
    baselineY = pad + (h - pad * 2) * (1 - (baseline - min) / range);
  }
  return (
    <svg className="spark" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none">
      {fill && <path d={area} fill={color} opacity="0.12" />}
      {baselineY != null && (
        <line
          x1={pad}
          x2={w - pad}
          y1={baselineY}
          y2={baselineY}
          stroke={color}
          strokeWidth="1"
          strokeDasharray="3 3"
          opacity="0.5"
        />
      )}
      <path
        d={path}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx={last[0]} cy={last[1]} r="3" fill={color} />
      <circle cx={last[0]} cy={last[1]} r="6" fill={color} opacity="0.2" />
    </svg>
  );
}
