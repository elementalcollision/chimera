// v4.54 (ADR 0073) — Cost-rate alarm widget.
//
// Reads the last-15-minute rolling spend computed by lib/cost.ts and
// renders a band-coloured headline. The 2026-05-19 overnight burn
// would have shown SOLID RED at cycle 18 (90 minutes in, ~$1.70/min);
// the absence of this widget is why the operator only noticed at the
// $90 billing email two hours later.
import { CostRate } from "@/lib/cost";

interface Props {
  rate: CostRate;
}

const BAND_LABEL: Record<CostRate["band"], string> = {
  off: "—",
  green: "OK",
  amber: "WATCH",
  red: "ALARM",
};

const BAND_COLOR: Record<CostRate["band"], string> = {
  off: "var(--mlc-slate-500)",
  green: "var(--mlc-teal)",
  amber: "var(--mlc-sand-500)",
  red: "var(--mlc-peach-500)",
};

const BAND_HINT: Record<CostRate["band"], string> = {
  off: "no calls in window",
  green: "< $0.10/min — normal",
  amber: "$0.10–0.50/min — review",
  red: "> $0.50/min — investigate",
};

export default function CostAlarmWidget({ rate }: Props) {
  const colour = BAND_COLOR[rate.band];
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
            minWidth: 80,
            textAlign: "center",
          }}
        >
          {BAND_LABEL[rate.band]}
        </div>
        <div>
          <div className="mono" style={{ fontSize: 22, fontWeight: 600 }}>
            ${rate.usdPerMin.toFixed(3)}
            <span className="muted" style={{ fontSize: 12, marginLeft: 6 }}>
              /min
            </span>
          </div>
          <div className="muted" style={{ fontSize: 11, marginTop: 2 }}>
            {BAND_HINT[rate.band]}
          </div>
        </div>
      </div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          gap: 10,
          fontSize: 12,
        }}
      >
        <div>
          <div className="label">Window</div>
          <div className="mono">{rate.minutesWindow}m</div>
        </div>
        <div>
          <div className="label">Spent</div>
          <div className="mono">${rate.totalUsd.toFixed(2)}</div>
        </div>
      </div>
      {rate.topModel && (
        <div style={{ fontSize: 11 }}>
          <span className="label">Top contributor</span>{" "}
          <span className="mono">
            {rate.topModel.split("/").pop()}
          </span>{" "}
          <span className="muted">(${rate.topUsd.toFixed(2)})</span>
        </div>
      )}
      <div className="muted" style={{ fontSize: 10, lineHeight: 1.4 }}>
        Thresholds: green &lt; $0.10/min, amber $0.10–0.50/min, red &gt; $0.50/min.
        2026-05-19 burn averaged $1.70/min — this widget would have shown
        red within 15m.
      </div>
    </div>
  );
}
