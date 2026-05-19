import { Heartbeat, TrustState } from "@/lib/mind";
import { DriftLogRecord } from "@/lib/graph";
import Sparkline from "@/components/viz/Sparkline";
import TierLadder from "@/components/viz/TierLadder";

interface Props {
  hb: Heartbeat | null;
  trust: TrustState | null;
  driftHistory: DriftLogRecord[];
}

const TIER_NAMES = ["isolate", "seed", "probe", "steward", "autonomous", "trusted"];

export default function StatusWidget({ hb, trust, driftHistory }: Props) {
  if (!hb) return <p className="muted">HEARTBEAT.md not found.</p>;
  const t = trust?.current_tier ?? 0;
  const driftValues = driftHistory.map((r) => r.composite_score);
  const latestDrift =
    driftValues.length > 0
      ? driftValues[driftValues.length - 1]
      : hb.last_drift_score ?? 0;
  return (
    <div style={{ display: "grid", gap: 14 }}>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "auto 1fr",
          gap: 16,
          alignItems: "center",
        }}
      >
        <div>
          <div className="label">Readiness</div>
          <div className="serif-num" style={{ fontSize: 44, marginTop: 4 }}>
            {(trust?.last_readiness ?? 0).toFixed(2)}
          </div>
        </div>
        <div style={{ display: "grid", gap: 8 }}>
          <div className="label">
            Trust tier · T{t} {TIER_NAMES[t] ?? "?"}
          </div>
          <TierLadder current={t} recent={null} />
          {trust?.tier_entered_at && (
            <div className="muted" style={{ fontSize: 11 }}>
              entered T{t} · {trust.tier_entered_at.slice(0, 16)}
            </div>
          )}
        </div>
      </div>

      <div className="kv-grid" style={{ gridTemplateColumns: "1fr 1fr 1fr" }}>
        <div className="kv">
          <div className="kv__label">Cycle</div>
          <div className="kv__value">{hb.cycle}</div>
        </div>
        <div className="kv">
          <div className="kv__label">Status</div>
          <div
            className="kv__value"
            style={{ display: "flex", alignItems: "center", gap: 6 }}
          >
            <span
              style={{
                width: 8,
                height: 8,
                borderRadius: 999,
                background: "var(--mlc-green-800)",
              }}
            />
            {hb.status}
          </div>
        </div>
        <div className="kv">
          <div className="kv__label">Drift</div>
          <div className="kv__value">{(latestDrift ?? 0).toFixed(2)}</div>
        </div>
      </div>

      {driftValues.length > 0 && (
        <div>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "baseline",
              marginBottom: 4,
            }}
          >
            <span className="label">
              Drift score · last {driftValues.length} readings
            </span>
            <span className="muted" style={{ fontSize: 11 }}>
              lockdown ≥ 0.30
            </span>
          </div>
          <Sparkline
            values={driftValues}
            color="var(--mlc-teal)"
            height={44}
            baseline={0.3}
          />
        </div>
      )}
    </div>
  );
}
