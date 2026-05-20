// v4.68 (ADR 0087) — Hot signatures widget.
//
// Passive dashboard surface for the same data `chimera escalations
// summary` shows under the ⚠️ HOT SIGNATURES section. The CLI version
// requires the operator to remember to run the command; this widget
// makes the alarm passive — visible whenever the operator opens the
// dashboard.
//
// Empty state (no signatures with ≥ 2 failures) is the healthy state.
// Most days the widget shows "no hot signatures" and that's the
// correct signal.
import { HotSignatureRow } from "@/lib/db";

interface Props {
  rows: HotSignatureRow[];
}

export default function HotSignaturesWidget({ rows }: Props) {
  if (rows.length === 0) {
    return (
      <div>
        <p className="muted">No hot signatures.</p>
        <div className="muted" style={{ fontSize: 11, marginTop: 8, lineHeight: 1.4 }}>
          A signature becomes &ldquo;hot&rdquo; after ≥ 2 task_escalations
          failures. Empty = healthy. After 3 failures (v4.65) the
          auto-loop task splitter (if enabled) proposes a split via the
          mutation queue.
        </div>
      </div>
    );
  }
  return (
    <div style={{ display: "grid", gap: 10 }}>
      <div className="label" style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
        <span style={{ fontSize: 14, color: "var(--mlc-peach-500)" }}>⚠</span>
        <span>{rows.length} hot signature(s) — review task text, not just tier</span>
      </div>
      <div style={{ display: "grid", gap: 8 }}>
        {rows.map((r) => {
          const tiers = r.tiers.split(",").filter(Boolean).join("/") || "?";
          const cycles =
            r.first_cycle === r.last_cycle
              ? `cycle ${r.first_cycle}`
              : `cycles ${r.first_cycle}→${r.last_cycle}`;
          return (
            <div
              key={r.signature}
              style={{
                borderLeft: "3px solid var(--mlc-peach-500)",
                paddingLeft: 10,
                paddingBlock: 4,
                fontSize: 12,
              }}
            >
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "auto 1fr auto",
                  gap: 10,
                  alignItems: "baseline",
                }}
              >
                <span className="mono" style={{ fontWeight: 700 }}>
                  ×{r.total_failures}
                </span>
                <span className="muted" style={{ fontSize: 11 }}>
                  tiers={tiers} {cycles} last={r.last_finish_reason || "?"}
                </span>
              </div>
              {r.excerpt && (
                <div
                  className="mono"
                  style={{
                    fontSize: 11,
                    marginTop: 4,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                  title={r.excerpt}
                >
                  {r.excerpt}
                  {r.excerpt.length >= 120 ? "…" : ""}
                </div>
              )}
            </div>
          );
        })}
      </div>
      <div className="muted" style={{ fontSize: 10, lineHeight: 1.4 }}>
        Threshold: ≥ 2 failures. Operator actions: rewrite task text in
        mind/INBOX.md, or `chimera split &lt;task&gt;` for a model-proposed
        split (v4.63).
      </div>
    </div>
  );
}
