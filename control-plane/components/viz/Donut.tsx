interface Segment {
  value: number;
  color: string;
}
interface Props {
  segments: Segment[];
  size?: number;
  thickness?: number;
  label?: string | null;
  sub?: string | null;
}

export default function Donut({
  segments,
  size = 110,
  thickness = 18,
  label = null,
  sub = null,
}: Props) {
  const total = segments.reduce((s, x) => s + x.value, 0) || 1;
  const r = size / 2 - thickness / 2;
  const c = size / 2;
  const circ = 2 * Math.PI * r;
  let offset = 0;
  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      style={{ display: "block" }}
    >
      <circle
        cx={c}
        cy={c}
        r={r}
        stroke="var(--border-1)"
        strokeWidth={thickness}
        fill="none"
      />
      {segments.map((seg, i) => {
        const len = (seg.value / total) * circ;
        const dash = `${len} ${circ - len}`;
        const el = (
          <circle
            key={i}
            cx={c}
            cy={c}
            r={r}
            stroke={seg.color}
            strokeWidth={thickness}
            fill="none"
            strokeDasharray={dash}
            strokeDashoffset={-offset}
            transform={`rotate(-90 ${c} ${c})`}
            strokeLinecap="butt"
          />
        );
        offset += len;
        return el;
      })}
      {label != null && (
        <g>
          <text
            x={c}
            y={c - 2}
            textAnchor="middle"
            dominantBaseline="middle"
            fontFamily="var(--font-serif)"
            fontSize="22"
            fill="var(--fg-1)"
            letterSpacing="-0.02em"
          >
            {label}
          </text>
          {sub != null && (
            <text
              x={c}
              y={c + 16}
              textAnchor="middle"
              dominantBaseline="middle"
              fontFamily="var(--font-sans)"
              fontSize="10"
              fill="var(--fg-3)"
              letterSpacing="0.12em"
            >
              {sub}
            </text>
          )}
        </g>
      )}
    </svg>
  );
}
