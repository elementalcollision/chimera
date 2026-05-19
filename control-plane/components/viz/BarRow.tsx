interface Props {
  name: string;
  value: number;
  max: number;
  tone?: "teal" | "mint" | "slate" | "sand" | "peach";
  unit?: string;
}

export default function BarRow({
  name,
  value,
  max,
  tone = "teal",
  unit = "",
}: Props) {
  const pct = Math.max(2, (value / Math.max(1, max)) * 100);
  return (
    <div className="bar-row">
      <div className="bar-row__name">{name}</div>
      <div className="bar-row__bar">
        <div
          className="bar-row__fill"
          data-tone={tone}
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="bar-row__val">
        {value.toLocaleString(undefined, { maximumFractionDigits: 2 })}
        {unit}
      </div>
    </div>
  );
}
