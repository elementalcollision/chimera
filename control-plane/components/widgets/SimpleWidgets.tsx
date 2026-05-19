/**
 * MLC-styled widgets — server components.
 * Each takes already-fetched data as props and renders in the
 * design language defined in app/tokens.css + canvas-styles.css.
 */
import { ApiCall, Entity, Mutation } from "@/lib/db";
import {
  AssemblyJournalEntry,
  DriftLogRecord,
  EmergenceCounts,
  GraphSnapshot,
  PeerEntry,
  PhaseTimings,
  TrustGroupRow,
} from "@/lib/graph";
import { FragmentationRow } from "@/lib/fragmentation";
import BarRow from "@/components/viz/BarRow";
import Sparkline from "@/components/viz/Sparkline";

function Empty({ children }: { children: React.ReactNode }) {
  return <div className="empty">{children}</div>;
}

// ── Phase timings ────────────────────────────────────────────

export function PhaseTimingsWidget({ timings }: { timings: PhaseTimings | null }) {
  if (!timings) return <Empty>No phase_timings.json yet.</Empty>;
  const entries = Object.entries(timings.phase_times_ms);
  const total = entries.reduce((s, [, v]) => s + v, 0);
  const max = Math.max(...entries.map(([, v]) => v));
  const actDominates = entries.some(
    ([n, v]) => n === "act" && total > 0 && v / total > 0.4,
  );
  return (
    <div style={{ display: "grid", gap: 10 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <div>
          <div className="label">Cycle {timings.cycle} · total</div>
          <div className="serif-num" style={{ fontSize: 26, marginTop: 2 }}>
            {(total / 1000).toFixed(2)}
            <span style={{ fontSize: 13, fontFamily: "var(--font-sans)", color: "var(--fg-3)", marginLeft: 4 }}>s</span>
          </div>
        </div>
        {actDominates && <span className="pill" data-tone="warn">act dominates</span>}
      </div>
      <div>
        {entries.map(([name, ms]) => (
          <BarRow key={name} name={name} value={ms} max={max} unit=" ms" tone={name === "act" ? "sand" : "mint"} />
        ))}
      </div>
    </div>
  );
}

// ── Ontology ────────────────────────────────────────────────

export function OntologyWidget({ entities }: { entities: Entity[] }) {
  if (entities.length === 0) return <Empty>No entities yet.</Empty>;
  const tone: Record<string, "ok" | "warn" | "slate" | "teal"> = {
    STABLE: "ok",
    CANDIDATE: "teal",
    EXPERIMENTAL: "warn",
    NEW: "slate",
    DEPRECATED: "warn",
  };
  return (
    <div className="row-list">
      <div className="row-list__head row-list__row" style={{ gridTemplateColumns: "100px 60px 1fr 40px" }}>
        <span>State</span><span>Kind</span><span>Name</span><span className="right">Cy</span>
      </div>
      {entities.map((e) => (
        <div key={e.id} className="row-list__row" style={{ gridTemplateColumns: "100px 60px 1fr 40px" }}>
          <span className="pill" data-tone={tone[e.kfm_state] ?? "slate"}>{e.kfm_state.toLowerCase()}</span>
          <span className="muted">{e.kind}</span>
          <span className="mono">{e.name}</span>
          <span className="right muted">{e.state_entered_at_cycle}</span>
        </div>
      ))}
    </div>
  );
}

// ── API calls ───────────────────────────────────────────────

export function ApiCallsWidget({ calls }: { calls: ApiCall[] }) {
  if (calls.length === 0) return <Empty>No api_calls yet.</Empty>;
  return (
    <div className="row-list">
      <div className="row-list__head row-list__row" style={{ gridTemplateColumns: "30px 80px 1fr 50px 50px 60px" }}>
        <span>Cy</span><span>Provider</span><span>Model</span><span className="right">in</span><span className="right">out</span><span className="right">ms</span>
      </div>
      {calls.map((c) => (
        <div key={c.id} className="row-list__row" style={{ gridTemplateColumns: "30px 80px 1fr 50px 50px 60px" }}>
          <span className="muted mono">{c.cycle}</span>
          <span className="pill" data-tone={c.provider === "anthropic" ? "teal" : "slate"} style={{ fontSize: 10 }}>{c.provider}</span>
          <span className="mono" style={{ fontSize: 11, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.model_id}</span>
          <span className="right mono">{(c.input_tokens ?? 0).toLocaleString()}</span>
          <span className="right mono">{c.output_tokens ?? "—"}</span>
          <span className="right mono">{c.latency_ms ?? "—"}</span>
        </div>
      ))}
    </div>
  );
}

// ── Mutations ───────────────────────────────────────────────

export function MutationsWidget({ mutations }: { mutations: Mutation[] }) {
  if (mutations.length === 0) return <Empty>No mutations yet.</Empty>;
  const tone: Record<string, "warn" | "ok" | "danger" | "slate"> = {
    pending: "warn", applied: "ok", rejected: "danger", failed: "danger",
  };
  const counts = mutations.reduce<Record<string, number>>((a, m) => ((a[m.status] = (a[m.status] || 0) + 1), a), {});
  return (
    <div style={{ display: "grid", gap: 12 }}>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        {counts.pending != null && <span className="pill" data-tone="warn">{counts.pending} pending</span>}
        {counts.applied != null && <span className="pill" data-tone="ok">{counts.applied} applied</span>}
        {counts.failed != null && <span className="pill" data-tone="danger">{counts.failed} failed</span>}
        {counts.rejected != null && <span className="pill" data-tone="danger">{counts.rejected} rejected</span>}
      </div>
      <div className="row-list">
        {mutations.map((m) => (
          <div key={m.id} className="row-list__row" style={{ gridTemplateColumns: "36px 110px 80px 1fr", alignItems: "start" }}>
            <span className="mono muted">#{m.id}</span>
            <span style={{ fontSize: 11 }}>{m.type}</span>
            <span className="pill" data-tone={tone[m.status] ?? "slate"}>{m.status}</span>
            <span style={{ fontSize: 11, color: "var(--fg-2)" }}>{m.reason ?? ""}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Skill assembly ──────────────────────────────────────────

export function AssemblyJournalWidget({ entries }: { entries: AssemblyJournalEntry[] }) {
  if (entries.length === 0) return <Empty>No assemblies logged.</Empty>;
  return (
    <div style={{ display: "grid", gap: 14 }}>
      {entries.map((a) => (
        <div key={`${a.mutation_id}-${a.recorded_at}`} style={{ display: "grid", gap: 6 }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
            <span className="mono muted">#{a.mutation_id}</span>
            <span className="mono" style={{ fontSize: 13, fontWeight: 600 }}>{a.skill_name}</span>
            {a.winning_tier && <span className="pill" data-tone="teal">winner: {a.winning_tier}</span>}
            <span className="muted mono" style={{ marginLeft: "auto", fontSize: 10 }}>{a.recorded_at.slice(0, 16)}</span>
          </div>
          <div style={{ display: "grid", gap: 4 }}>
            {a.attempts.map((at, i) => (
              <div key={i} style={{ display: "grid", gridTemplateColumns: "84px 1fr auto", gap: 8, alignItems: "center" }}>
                <span className="pill" data-tone={at.validation_ok ? "ok" : "slate"} style={{ fontSize: 10 }}>{at.tier}</span>
                <div style={{ display: "flex", gap: 4, alignItems: "center" }}>
                  <div style={{ height: 4, flex: 1, background: "var(--bg-2)", borderRadius: 999, overflow: "hidden", position: "relative" }}>
                    <div style={{ width: `${at.validation_score * 100}%`, height: "100%", background: "var(--mlc-slate-400)" }} />
                    {at.revised && at.revised_score != null && (
                      <div style={{ position: "absolute", left: `${at.validation_score * 100}%`, width: `${Math.max(0, at.revised_score - at.validation_score) * 100}%`, height: "100%", background: "var(--mlc-mint)" }} />
                    )}
                  </div>
                  <span className="mono" style={{ fontSize: 10, minWidth: 70, textAlign: "right" }}>
                    {Math.round(at.validation_score * 100)}%
                    {at.revised && at.revised_score != null && ` → ${Math.round(at.revised_score * 100)}%`}
                  </span>
                </div>
                <span className="muted" style={{ fontSize: 10 }}>{at.witnesses.length > 0 ? `${at.witnesses.length}w` : "—"}</span>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Graph (skill DAG) ───────────────────────────────────────

export function GraphWidget({ graph }: { graph: GraphSnapshot | null }) {
  if (!graph || graph.skills.length === 0) return <Empty>No graph snapshot yet.</Empty>;
  const tools = Array.from(new Set(graph.skills.flatMap((s) => s.tools ?? [])));
  const W = 260, H = 150, padX = 20;
  const toolX = (i: number) => padX + i * ((W - padX * 2) / Math.max(1, tools.length - 1));
  const skillX = (i: number) => padX + i * ((W - padX * 2) / Math.max(1, graph.skills.length - 1));
  const toolY = 30, skillY = 110;
  return (
    <div style={{ display: "grid", gap: 8 }}>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto" }}>
        {graph.skills.flatMap((s, si) =>
          (s.tools ?? []).map((d, di) => {
            const ti = tools.indexOf(d);
            if (ti < 0) return null;
            return (
              <line key={`${si}-${di}`} x1={toolX(ti)} y1={toolY + 8} x2={skillX(si)} y2={skillY - 8} stroke="var(--border-2)" strokeWidth="1" />
            );
          }),
        )}
        {tools.map((t, i) => (
          <g key={t} transform={`translate(${toolX(i)} ${toolY})`}>
            <rect x={-38} y={-8} width={76} height={18} rx={3} fill="var(--bg-2)" stroke="var(--border-1)" />
            <text x={0} y={3} textAnchor="middle" fontFamily="var(--font-mono)" fontSize="9.5" fill="var(--fg-2)">{t}</text>
          </g>
        ))}
        {graph.skills.map((s, i) => (
          <g key={s.name} transform={`translate(${skillX(i)} ${skillY})`}>
            <rect x={-44} y={-9} width={88} height={20} rx={3} fill="var(--mlc-mint)" />
            <text x={0} y={4} textAnchor="middle" fontFamily="var(--font-mono)" fontSize="9.5" fill="var(--mlc-mint-ink)">{s.name}</text>
          </g>
        ))}
      </svg>
      <div style={{ display: "flex", gap: 8, fontSize: 11, color: "var(--fg-3)" }}>
        <span><span style={{ display: "inline-block", width: 8, height: 8, background: "var(--mlc-mint)", marginRight: 4, borderRadius: 2 }} />active skill</span>
        <span style={{ marginLeft: "auto" }}>{graph.skills.length} skills · {tools.length} tools</span>
      </div>
    </div>
  );
}

// ── Peers ───────────────────────────────────────────────────

export function PeersWidget({ peers }: { peers: PeerEntry[] }) {
  if (peers.length === 0) return <Empty>No peers in registry.</Empty>;
  return (
    <div className="row-list">
      {peers.map((p, i) => (
        <div key={i} className="row-list__row" style={{ gridTemplateColumns: "10px 1fr 70px 80px" }}>
          <span style={{ width: 8, height: 8, borderRadius: 999, background: p.pid > 0 ? "var(--mlc-green-800)" : "var(--fg-3)" }} />
          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            <span className="mono" style={{ fontSize: 12 }}>{p.agent_id}</span>
            <span className="muted" style={{ fontSize: 10 }}>{p.host} · {p.version}</span>
          </div>
          <span className="muted mono" style={{ fontSize: 10, textAlign: "right" }}>{p.reach?.transport ?? "—"}</span>
          <span className="pill" data-tone={p.pid > 0 ? "ok" : "slate"} style={{ justifySelf: "end" }}>{p.pid > 0 ? "online" : "remote"}</span>
        </div>
      ))}
    </div>
  );
}

// ── Peer trust journal ──────────────────────────────────────

export function TrustJournalWidget({ groups }: { groups: TrustGroupRow[] }) {
  if (groups.length === 0) return <Empty>No peer-trust decisions logged.</Empty>;
  const tone: Record<string, "ok" | "warn" | "danger"> = { ALLOW: "ok", DEGRADE: "warn", REFUSE: "danger" };
  return (
    <div className="row-list">
      <div className="row-list__head row-list__row" style={{ gridTemplateColumns: "1fr 50px 80px 60px" }}>
        <span>Peer</span><span className="right">#</span><span>Latest</span><span className="right">Drift</span>
      </div>
      {groups.map((g, i) => (
        <div key={i} className="row-list__row" style={{ gridTemplateColumns: "1fr 50px 80px 60px" }}>
          <span className="mono" style={{ fontSize: 12 }}>{g.peer}</span>
          <span className="right mono muted">{g.decisions}</span>
          <span className="pill" data-tone={g.latest ? tone[g.latest.decision] ?? "slate" : "slate"}>
            {(g.latest?.decision ?? "—").toLowerCase()}
          </span>
          <span className="right mono" style={{ color: (g.latest?.drift_score ?? 0) > 0.3 ? "var(--mlc-peach-500)" : "var(--fg-2)" }}>
            {g.latest?.drift_score != null ? g.latest.drift_score.toFixed(2) : "—"}
          </span>
        </div>
      ))}
    </div>
  );
}

// ── Emergence ───────────────────────────────────────────────

export function EmergenceWidget({ counts }: { counts: EmergenceCounts }) {
  const empty = counts.localPeers.length === 0 && counts.remotePeers.length === 0;
  if (empty) return <Empty>No emergence observations yet.</Empty>;
  const maxObs = Math.max(1, ...counts.localPeers.map((x) => x.observations), ...counts.remotePeers.map((x) => x.observations));
  return (
    <div style={{ display: "grid", gap: 12 }}>
      {counts.localPeers.length > 0 && (
        <div>
          <div className="label" style={{ marginBottom: 6 }}>Local</div>
          {counts.localPeers.map((r) => (
            <BarRow key={r.name} name={r.name} value={r.observations} max={maxObs} tone="mint" />
          ))}
        </div>
      )}
      {counts.remotePeers.length > 0 && (
        <div>
          <div className="label" style={{ marginBottom: 6 }}>Remote</div>
          {counts.remotePeers.map((r, i) => (
            <BarRow key={i} name={`${r.host}/${r.peer}`} value={r.observations} max={maxObs} tone="slate" />
          ))}
        </div>
      )}
    </div>
  );
}

// ── Inbox ───────────────────────────────────────────────────

export function InboxWidget({ content }: { content: string }) {
  const lines = content.split("\n").filter((l) => /^\s*-\s*\[(x| )\]/i.test(l)).map((l) => ({
    done: /^\s*-\s*\[x\]/i.test(l),
    text: l.replace(/^\s*-\s*\[(x| )\]\s*/i, "").replace(/<!--.*?-->/g, "").trim(),
  }));
  if (lines.length === 0) return <Empty>INBOX has no tasks.</Empty>;
  const done = lines.filter((t) => t.done).length;
  return (
    <div style={{ display: "grid", gap: 10 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
        <span className="serif-num" style={{ fontSize: 28 }}>
          {done}<span style={{ color: "var(--fg-3)" }}>/{lines.length}</span>
        </span>
        <span className="muted" style={{ fontSize: 11 }}>tasks complete</span>
        <span className="pill" data-tone="warn" style={{ marginLeft: "auto" }}>{lines.length - done} open</span>
      </div>
      <div style={{ height: 4, background: "var(--bg-2)", borderRadius: 999, overflow: "hidden" }}>
        <div style={{ width: `${(done / lines.length) * 100}%`, height: "100%", background: "var(--mlc-green-600)" }} />
      </div>
      <div style={{ display: "grid", gap: 4 }}>
        {lines.map((t, i) => (
          <div key={i} style={{ display: "flex", gap: 8, fontSize: 11, lineHeight: 1.5 }}>
            <span style={{
              width: 14, height: 14, marginTop: 2, flexShrink: 0,
              border: `1.5px solid ${t.done ? "var(--mlc-green-600)" : "var(--border-2)"}`,
              background: t.done ? "var(--mlc-green-600)" : "transparent",
              borderRadius: 3, display: "inline-flex", alignItems: "center", justifyContent: "center",
            }}>
              {t.done && (
                <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="20 6 9 17 4 12" />
                </svg>
              )}
            </span>
            <span style={{ color: t.done ? "var(--fg-3)" : "var(--fg-1)", textDecoration: t.done ? "line-through" : "none" }}>{t.text}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Chronicle ───────────────────────────────────────────────

export function ChronicleWidget({ content }: { content: string }) {
  const tail = content.split("\n").slice(-200).join("\n");
  const grab = (re: RegExp): string | null => {
    const m = tail.match(re);
    return m ? m[1].trim().slice(0, 600) : null;
  };
  const morning = grab(/### Morning Discovery[^\n]*\n([\s\S]*?)(?=\n### |\n##|$)/);
  const midday = grab(/### Midday Curiosity[^\n]*\n([\s\S]*?)(?=\n### |\n##|$)/);
  const evening = grab(/### Evening Reflection[^\n]*\n([\s\S]*?)(?=\n### |\n##|$)/);
  const today = new Date().toISOString().slice(0, 10);
  return (
    <div style={{ display: "grid", gap: 10 }}>
      <div className="label">{today}</div>
      {morning && (
        <div>
          <div className="label" style={{ color: "var(--mlc-teal)" }}>Morning · discovery</div>
          <p style={{ fontSize: 12, margin: "4px 0 0", color: "var(--fg-2)" }}>{morning}</p>
        </div>
      )}
      {midday && (
        <div>
          <div className="label" style={{ color: "var(--mlc-sand-500)" }}>Midday · curiosity</div>
          <p style={{ fontSize: 12, margin: "4px 0 0", color: "var(--fg-2)" }}>{midday}</p>
        </div>
      )}
      {evening && (
        <div>
          <div className="label" style={{ color: "var(--mlc-peach-500)" }}>Evening · reflection</div>
          <p style={{ fontSize: 12, margin: "4px 0 0", color: "var(--fg-2)", fontFamily: "var(--font-serif)", fontStyle: "italic", lineHeight: 1.55 }}>{evening}</p>
        </div>
      )}
      {!morning && !midday && !evening && (
        <pre style={{ whiteSpace: "pre-wrap", fontSize: 11, color: "var(--fg-2)", background: "var(--bg-2)", padding: 8, borderRadius: 4 }}>
          {content.slice(-2000) || "(empty)"}
        </pre>
      )}
    </div>
  );
}

// ── Fragmentation log ───────────────────────────────────────

export function FragmentationWidget({ rows }: { rows: FragmentationRow[] }) {
  if (rows.length === 0) return <Empty>No fragmentations logged.</Empty>;
  return (
    <div style={{ display: "grid", gap: 10 }}>
      <div style={{ display: "flex", gap: 8, alignItems: "baseline" }}>
        <span className="serif-num" style={{ fontSize: 28 }}>{rows.length}</span>
        <span className="muted" style={{ fontSize: 11 }}>failed compound tasks</span>
      </div>
      <div style={{ display: "grid", gap: 6 }}>
        {rows.map((f, i) => (
          <div key={i} style={{ display: "grid", gridTemplateColumns: "50px 1fr auto auto", gap: 8, alignItems: "center", padding: "6px 0", borderTop: i ? "1px solid var(--border-1)" : "none" }}>
            <span className="pill" data-tone="danger" style={{ fontSize: 10 }}>cy {f.cycle}</span>
            <div>
              <div style={{ fontSize: 11, color: "var(--fg-1)", overflow: "hidden", textOverflow: "ellipsis", display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical" }}>
                {f.task_text.slice(0, 200)}
              </div>
              <div className="mono muted" style={{ fontSize: 10, marginTop: 2 }}>missing: {f.missing_artifacts.join(", ")}</div>
            </div>
            <span className="mono muted" style={{ fontSize: 10 }}>{f.rounds_used}r</span>
            <span className="mono muted" style={{ fontSize: 10 }}>{f.tool_call_count}c</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Drift sparkline ─────────────────────────────────────────

export function DriftSparklineWidget({ records }: { records: DriftLogRecord[] }) {
  if (records.length === 0) return <Empty>No drift readings yet.</Empty>;
  const latest = records[records.length - 1];
  const severityColor =
    latest.severity === "high" ? "var(--mlc-peach-500)" :
    latest.severity === "medium" ? "var(--mlc-sand-500)" :
    "var(--mlc-green-800)";
  return (
    <div style={{ display: "grid", gap: 8 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
        <span className="serif-num" style={{ fontSize: 28, color: severityColor }}>{latest.composite_score.toFixed(2)}</span>
        <span className="muted" style={{ fontSize: 11 }}>cycle {latest.cycle} · {latest.severity} · → {latest.action}</span>
      </div>
      <Sparkline values={records.map((r) => r.composite_score)} color="var(--mlc-teal)" height={56} baseline={0.3} />
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "var(--fg-3)" }}>
        <span>warning ≥ 0.20</span>
        <span>lockdown ≥ 0.30</span>
        <span>{records.length} readings</span>
      </div>
    </div>
  );
}

