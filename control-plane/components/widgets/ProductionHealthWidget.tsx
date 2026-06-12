// Production-health widget (ADR 0182 dashboard consolidation).
//
// The single at-a-glance answer to "is production health trending bad?" —
// a worst-of verdict over the health signals Chimera already emits, with a
// per-dimension breakdown so the operator can see WHICH signal is amber/red
// without opening the underlying telemetry widget. The headline of the
// operator-first "Review" preset.
import { HealthStatus, HealthSummary } from "@/lib/health";

interface Props {
  health: HealthSummary;
}

const STATUS_COLOR: Record<HealthStatus, string> = {
  green: "var(--mlc-teal)",
  amber: "var(--mlc-sand-500)",
  red: "var(--mlc-peach-500)",
  unknown: "var(--mlc-slate-500)",
};

const OVERALL_LABEL: Record<HealthStatus, string> = {
  green: "HEALTHY",
  amber: "WATCH",
  red: "DEGRADED",
  unknown: "—",
};

export default function ProductionHealthWidget({ health }: Props) {
  const colour = STATUS_COLOR[health.overall];
  return (
    <div style={{ display: "grid", gap: 12 }}>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "auto 1fr",
          alignItems: "center",
          gap: 14,
        }}
      >
        <div
          style={{
            background: colour,
            color: "var(--mlc-ink)",
            padding: "10px 14px",
            borderRadius: 8,
            fontWeight: 700,
            fontSize: 14,
            letterSpacing: 0.5,
            minWidth: 96,
            textAlign: "center",
          }}
        >
          {OVERALL_LABEL[health.overall]}
        </div>
        <div className="muted" style={{ fontSize: 11, lineHeight: 1.4 }}>
          Worst-of over the signals below. Each dimension shows its raw value
          — a heuristic status never hides the number.
        </div>
      </div>

      <div style={{ display: "grid", gap: 6 }}>
        {health.dimensions.map((d) => (
          <div
            key={d.key}
            style={{
              display: "grid",
              gridTemplateColumns: "12px 120px 1fr",
              alignItems: "center",
              gap: 10,
              fontSize: 12,
            }}
          >
            <span
              aria-hidden
              style={{
                width: 10,
                height: 10,
                borderRadius: "50%",
                background: STATUS_COLOR[d.status],
              }}
            />
            <span className="label">{d.label}</span>
            <span className="mono muted">{d.detail}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
