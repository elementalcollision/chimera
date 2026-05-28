// Benchmark-history widget — passive surface for headline benchmark
// numbers from mind/benchmarks.json (LongMemEval oracle / _s, LoCoMo
// full / envelope / hybrid, etc). Source-of-truth is the curated JSON
// file; per-row links point at the research note that documents the
// methodology and per-category breakdowns.
//
// Fail-soft: missing or malformed benchmarks.json renders a placeholder
// with a pointer to the README. Never crashes the page.
import { Benchmark, BenchmarksLoadResult } from "@/lib/benchmarks";

interface Props {
  result: BenchmarksLoadResult;
}

function fmtPct(n: number): string {
  return `${n.toFixed(2)}%`;
}

function fmtEnvelope(b: Benchmark): string {
  if (!b.envelope) return "—";
  return `${b.envelope.mean_pct.toFixed(1)}% ± ${b.envelope.sigma_pp.toFixed(1)}pp`;
}

export default function BenchmarkHistoryWidget({ result }: Props) {
  if (!result.ok) {
    const msg =
      result.reason === "missing"
        ? "No benchmarks recorded yet."
        : `benchmarks.json malformed: ${result.detail ?? "unknown"}`;
    return (
      <div>
        <p className="muted">{msg}</p>
        <div className="muted" style={{ fontSize: 11, marginTop: 8, lineHeight: 1.4 }}>
          Add entries to <span className="mono">mind/benchmarks.json</span> — see
          the &ldquo;Benchmark history&rdquo; section of{" "}
          <span className="mono">control-plane/README.md</span>.
        </div>
      </div>
    );
  }
  const entries = [...result.entries].sort((a, b) => (a.date < b.date ? 1 : -1));
  if (entries.length === 0) {
    return (
      <div>
        <p className="muted">No benchmarks recorded yet.</p>
      </div>
    );
  }
  const cols = "1fr 1.2fr 60px 80px 110px 90px";
  return (
    <div style={{ display: "grid", gap: 8 }}>
      <div className="row-list">
        <div className="row-list__head row-list__row" style={{ gridTemplateColumns: cols }}>
          <span>Benchmark</span>
          <span>Config</span>
          <span className="right">n</span>
          <span className="right">Headline</span>
          <span className="right">Envelope</span>
          <span className="right">Date</span>
        </div>
        {entries.map((b) => (
          <div
            key={b.id}
            className="row-list__row"
            style={{ gridTemplateColumns: cols, alignItems: "baseline" }}
            title={b.notes ?? ""}
          >
            <span style={{ fontSize: 12, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              <a
                href={`https://github.com/elementalcollision/uberagent/blob/main/${b.source_note}`}
                target="_blank"
                rel="noreferrer"
                style={{ color: "inherit", textDecoration: "underline dotted" }}
              >
                {b.benchmark}
              </a>
            </span>
            <span className="muted mono" style={{ fontSize: 11, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {b.config}
            </span>
            <span className="right mono" style={{ fontSize: 11 }}>{b.n.toLocaleString()}</span>
            <span className="right mono" style={{ fontSize: 12, fontWeight: 600 }}>{fmtPct(b.headline_pct)}</span>
            <span className="right mono muted" style={{ fontSize: 11 }}>{fmtEnvelope(b)}</span>
            <span className="right mono muted" style={{ fontSize: 11 }}>{b.date}</span>
          </div>
        ))}
      </div>
      <div className="muted" style={{ fontSize: 10, lineHeight: 1.4 }}>
        Source: <span className="mono">mind/benchmarks.json</span>. Each row links
        to the research note that documents methodology and per-category
        breakdowns. To add: append an entry to the JSON file (see README).
      </div>
    </div>
  );
}
