/**
 * MLC-styled widgets — server components.
 * Each takes already-fetched data as props and renders in the
 * design language defined in app/tokens.css + canvas-styles.css.
 */
import {
  ApiCall,
  Entity,
  ModelUtilization,
  Mutation,
  OntologyAudit,
  QueueHealth,
  ReanchorBucket,
  RoundBoundaryStats,
  ToolFanout,
  ToolFanoutBucket,
  ToolFanoutByModel,
} from "@/lib/db";
import type { FanoutCostBucket } from "@/lib/cost";
import {
  AssemblyJournalEntry,
  DriftLogRecord,
  EmergenceCounts,
  FederationConnectivity,
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

// ── Federation connectivity (ADR 0168) ──────────────────────

export function FederationConnectivityWidget({
  fed,
}: {
  fed: FederationConnectivity | null;
}) {
  if (!fed) {
    return (
      <Empty>
        No federation gauge. Enable CHIMERA_FEDERATION_METRICS and re-export the
        graph snapshot.
      </Empty>
    );
  }
  // Below ⟨k⟩ = 1 the giant component is gone (ER percolation threshold);
  // a connectivity < 1 means the swarm has fragmented into islands.
  const fragmented = fed.connectivity < 1;
  const subcritical = fed.n_nodes > 1 && fed.mean_degree < 1;
  const hubRisk = fed.hub_concentration >= 0.5 && fed.n_nodes > 2;
  const pct = (fed.connectivity * 100).toFixed(0);
  return (
    <div style={{ display: "grid", gap: 14 }}>
      <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: 16, alignItems: "center" }}>
        <div>
          <div className="label">Connectivity</div>
          <div
            className="serif-num"
            style={{ fontSize: 44, marginTop: 4, color: fragmented ? "var(--mlc-peach-500)" : "var(--fg-1)" }}
          >
            {pct}%
          </div>
        </div>
        <div style={{ display: "grid", gap: 6 }}>
          <div className="muted" style={{ fontSize: 11 }}>
            largest trust-reachable component {fed.largest_component} / {fed.n_nodes} peers
          </div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {fragmented && <span className="pill" data-tone="warn">fragmented</span>}
            {subcritical && <span className="pill" data-tone="danger">⟨k⟩ &lt; 1</span>}
            {hubRisk && <span className="pill" data-tone="warn">hub risk</span>}
            {!fragmented && !hubRisk && <span className="pill" data-tone="ok">cohesive</span>}
          </div>
        </div>
      </div>
      <div className="kv-grid" style={{ gridTemplateColumns: "1fr 1fr 1fr" }}>
        <div className="kv">
          <div className="kv__label">Mean degree ⟨k⟩</div>
          <div className="kv__value">{fed.mean_degree.toFixed(2)}</div>
        </div>
        <div className="kv">
          <div className="kv__label">Hub share</div>
          <div className="kv__value" style={{ color: hubRisk ? "var(--mlc-peach-500)" : "var(--fg-1)" }}>
            {(fed.hub_concentration * 100).toFixed(0)}%
          </div>
        </div>
        <div className="kv">
          <div className="kv__label">Isolated</div>
          <div className="kv__value">{fed.isolated_nodes}</div>
        </div>
      </div>
      {fed.hub_node && hubRisk && (
        <div className="muted" style={{ fontSize: 11 }}>
          single-point-of-trust-failure: <span className="mono">{fed.hub_node}</span> carries{" "}
          {fed.hub_degree} of {fed.n_edges} trust edges
        </div>
      )}
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

// ── v4.25: queue health (ADR 0041) ───────────────────────────

function _humanizeAge(s: number | null): string {
  if (s == null) return "—";
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}

export function QueueHealthWidget({ health }: { health: QueueHealth | null }) {
  if (!health) return <Empty>No mutation queue yet.</Empty>;
  const counts = health.counts;
  const pending = counts["pending"] || 0;
  const applied = counts["applied"] || 0;
  const decided =
    applied +
    (counts["approved"] || 0) +
    (counts["rejected"] || 0) +
    (counts["failed"] || 0);
  const ageS = health.pending_oldest_age_seconds;
  const ageTone: "ok" | "warn" | "danger" =
    ageS == null ? "ok" : ageS > 86400 ? "danger" : ageS > 3600 ? "warn" : "ok";
  const ratio = health.approved_ratio;
  const pillEntries: Array<[string, number, "warn" | "ok" | "danger" | "slate"]> = [
    ["pending", pending, pending > 0 ? "warn" : "slate"],
    ["applied", applied, "ok"],
    ["rejected", counts["rejected"] || 0, "slate"],
    ["failed", counts["failed"] || 0, "danger"],
    ["expired", counts["expired"] || 0, "slate"],
  ];
  const anyVisible = pillEntries.some(([, n]) => n > 0);
  return (
    <div style={{ display: "grid", gap: 12 }}>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        {pillEntries.map(([label, n, tone]) =>
          n > 0 ? (
            <span key={label} className="pill" data-tone={tone}>
              {label} {n}
            </span>
          ) : null,
        )}
        {!anyVisible && (
          <span className="muted" style={{ fontSize: 12 }}>queue is empty</span>
        )}
      </div>
      <div className="kv">
        <div>
          <div className="label">Oldest pending</div>
          <div className="serif-num" style={{ fontSize: 20 }} data-tone={ageTone}>
            {_humanizeAge(ageS)}
          </div>
        </div>
        <div>
          <div className="label">Recurrence (max / total)</div>
          <div className="serif-num" style={{ fontSize: 20 }}>
            {health.pending_recurrence_max} / {health.pending_recurrence_total}
          </div>
        </div>
        <div>
          <div className="label">Applied / decided</div>
          <div className="serif-num" style={{ fontSize: 20 }}>
            {decided > 0 && ratio !== null ? `${Math.round(ratio * 100)}%` : "—"}
          </div>
        </div>
      </div>
      {(health.pending_recurrence_max > 1 ||
        (ageS !== null && ageS > 3600)) && (
        <div className="muted" style={{ fontSize: 11 }}>
          Duplicates absorbed in-place via recurrence_count.
        </div>
      )}
    </div>
  );
}

// ── v4.25: ontology audit (ADR 0043) ─────────────────────────

export function OntologyAuditWidget({ audit }: { audit: OntologyAudit | null }) {
  if (!audit) return <Empty>No ontology yet.</Empty>;
  const stale = audit.stale_count;
  const dead = audit.dead_count;
  const dep = audit.deprecated_unarchived;
  const reanchor = audit.reanchor_events_in_window;
  const stateOrder = [
    "NEW",
    "EXPERIMENTAL",
    "CANDIDATE",
    "STABLE",
    "DEPRECATED",
    "ARCHIVED",
    "KILLED",
  ];
  return (
    <div style={{ display: "grid", gap: 12 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
        <span className="serif-num" style={{ fontSize: 28 }}>
          {audit.total_entities}
        </span>
        <span className="muted" style={{ fontSize: 11 }}>
          entities · cycle {audit.current_cycle}
        </span>
      </div>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
        {stateOrder.map((s) => {
          const n = audit.by_state[s] || 0;
          if (n === 0) return null;
          const tone =
            s === "DEPRECATED"
              ? "warn"
              : s === "STABLE" || s === "ARCHIVED"
              ? "ok"
              : "slate";
          return (
            <span key={s} className="pill" data-tone={tone}>
              {s.toLowerCase()} {n}
            </span>
          );
        })}
      </div>
      <div className="kv">
        <div>
          <div className="label">Stale (≥{audit.stale_after_cycles} cycles)</div>
          <div
            className="serif-num"
            style={{ fontSize: 20 }}
            data-tone={stale > 0 ? "warn" : "ok"}
          >
            {stale}
          </div>
        </div>
        <div>
          <div className="label">Dead (≥{audit.activity_window_cycles}c idle)</div>
          <div
            className="serif-num"
            style={{ fontSize: 20 }}
            data-tone={dead > 0 ? "warn" : "ok"}
          >
            {dead}
          </div>
        </div>
        <div>
          <div className="label">
            Re-anchors (last {audit.reanchor_window_cycles}c)
          </div>
          <div className="serif-num" style={{ fontSize: 20 }}>
            {reanchor}
          </div>
        </div>
        <div>
          <div className="label">DEPRECATED·unarchived</div>
          <div
            className="serif-num"
            style={{ fontSize: 20 }}
            data-tone={dep > 5 ? "warn" : "ok"}
          >
            {dep}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── v4.30: re-anchor history (ADR 0043 + 0046 follow-up) ────

export function ReanchorHistoryWidget({
  buckets,
}: {
  buckets: ReanchorBucket[];
}) {
  if (!buckets || buckets.length === 0) {
    return <Empty>No transition history yet.</Empty>;
  }
  const total = buckets.reduce((s, b) => s + b.count, 0);
  const peak = buckets.reduce((m, b) => Math.max(m, b.count), 0);
  const last = buckets[buckets.length - 1];
  const first = buckets[0];
  const window = last.end_cycle - first.start_cycle;
  // Trend hint: compare last 1/3 vs first 1/3 by count sum.
  const third = Math.max(1, Math.floor(buckets.length / 3));
  const recent = buckets.slice(-third).reduce((s, b) => s + b.count, 0);
  const oldest = buckets.slice(0, third).reduce((s, b) => s + b.count, 0);
  let trend: { tone: "ok" | "warn"; text: string } | null = null;
  if (recent > oldest * 1.5 && recent > 1) {
    trend = { tone: "warn", text: "trending up" };
  } else if (oldest > recent * 1.5 && oldest > 1) {
    trend = { tone: "ok", text: "trending down" };
  }
  return (
    <div style={{ display: "grid", gap: 10 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
        <span className="serif-num" style={{ fontSize: 28 }}>
          {total}
        </span>
        <span className="muted" style={{ fontSize: 11 }}>
          re-anchors across last {window} cycles
        </span>
        {trend && (
          <span className="pill" data-tone={trend.tone} style={{ marginLeft: "auto" }}>
            {trend.text}
          </span>
        )}
      </div>
      <Sparkline
        values={buckets.map((b) => b.count)}
        color="var(--mlc-amber)"
        height={56}
      />
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          fontSize: 11,
          color: "var(--fg-3)",
        }}
      >
        <span>cycle {first.start_cycle}</span>
        <span>peak {peak}/bucket</span>
        <span>cycle {last.end_cycle - 1}</span>
      </div>
    </div>
  );
}

// ── v4.33: tool-fanout telemetry (ADR 0040 follow-up) ───────

export function ToolFanoutWidget({
  fanout,
  byModel,
  history,
  costByFanout,
}: {
  fanout: ToolFanout | null;
  byModel?: ToolFanoutByModel[];
  history?: ToolFanoutBucket[];
  costByFanout?: FanoutCostBucket[];
}) {
  if (!fanout || fanout.total_calls_with_tools === 0) {
    return <Empty>No tool-use calls yet.</Empty>;
  }
  const total = fanout.total_calls_with_tools;
  const share = fanout.parallel_share;
  const dist: Array<{ label: string; n: number; tone: "slate" | "ok" | "mint" }> = [
    { label: "1 (serial)", n: fanout.serial, tone: "slate" },
    { label: "2", n: fanout.parallel_2, tone: "ok" },
    { label: "3+", n: fanout.parallel_3_plus, tone: "mint" },
  ];
  const distMax = Math.max(1, ...dist.map((b) => b.n));
  const showHistory = !!(history && history.length > 0 && history.some((b) => b.total > 0));
  const showByModel = !!(byModel && byModel.length > 0);
  return (
    <div style={{ display: "grid", gap: 10 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
        <span className="serif-num" style={{ fontSize: 28 }}>
          {share !== null ? Math.round(share * 100) + "%" : "—"}
        </span>
        <span className="muted" style={{ fontSize: 11 }}>
          parallel · {total} tool-use call{total === 1 ? "" : "s"} · max fan-out{" "}
          {fanout.max_fanout}
        </span>
      </div>
      <div>
        {dist.map((b) => (
          <BarRow
            key={b.label}
            name={b.label}
            value={b.n}
            max={distMax}
            unit=""
            tone={b.tone === "ok" ? "mint" : b.tone === "mint" ? "peach" : "sand"}
          />
        ))}
      </div>
      {showHistory && (
        <div style={{ display: "grid", gap: 4 }}>
          <div className="label" style={{ fontSize: 10 }}>Per-cycle parallel share</div>
          <Sparkline
            values={history!.map((b) =>
              b.total > 0 ? b.parallel / b.total : 0,
            )}
            color="var(--mlc-mint)"
            height={36}
            baseline={0.25}
          />
        </div>
      )}
      {costByFanout && costByFanout.some((b) => b.calls > 0) && (
        <div style={{ display: "grid", gap: 2 }}>
          <div className="label" style={{ fontSize: 10 }}>
            $/call vs $/tool-call (fan-out amortizes input)
          </div>
          {costByFanout
            .filter((b) => b.calls > 0)
            .map((b) => {
              const savings =
                b.bucket === "1"
                  ? null
                  : b.costPerCall > 0
                  ? 1 - b.costPerToolCall / b.costPerCall
                  : null;
              return (
                <div
                  key={b.bucket}
                  style={{
                    display: "flex",
                    alignItems: "baseline",
                    gap: 8,
                    fontSize: 11,
                    padding: "2px 0",
                  }}
                >
                  <span style={{ minWidth: 36, color: "var(--fg-2)" }}>
                    {b.bucket}
                  </span>
                  <span className="muted" style={{ minWidth: 84 }}>
                    {b.calls} call{b.calls === 1 ? "" : "s"}
                  </span>
                  <span
                    style={{
                      flex: 1,
                      fontVariantNumeric: "tabular-nums",
                      color: "var(--fg-2)",
                    }}
                  >
                    ${b.costPerCall.toFixed(4)} / ${b.costPerToolCall.toFixed(4)}
                  </span>
                  {savings !== null && (
                    <span
                      style={{
                        color:
                          savings >= 0.3
                            ? "var(--mlc-mint-ink)"
                            : "var(--fg-3)",
                        minWidth: 40,
                        textAlign: "right",
                      }}
                    >
                      -{Math.round(savings * 100)}%
                    </span>
                  )}
                </div>
              );
            })}
        </div>
      )}
      {showByModel && (
        <div className="row-list" style={{ marginTop: 2 }}>
          {byModel!.map((m) => (
            <div
              key={m.model_id}
              style={{
                display: "flex",
                alignItems: "baseline",
                gap: 8,
                fontSize: 11,
                padding: "3px 0",
              }}
            >
              <span style={{ flex: 1, color: "var(--fg-2)" }}>{m.model_id}</span>
              <span className="muted">avg {m.avg_fanout.toFixed(2)}</span>
              <span
                style={{
                  color:
                    m.parallel_share >= 0.5
                      ? "var(--mlc-mint-ink)"
                      : m.parallel_share >= 0.25
                      ? "var(--fg-2)"
                      : "var(--fg-3)",
                  fontVariantNumeric: "tabular-nums",
                  minWidth: 38,
                  textAlign: "right",
                }}
              >
                {Math.round(m.parallel_share * 100)}%
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── v4.51: model-utilization (engine pressure) ──────────────

export function ModelUtilizationWidget({
  rows,
  boundary,
}: {
  rows: ModelUtilization[];
  boundary?: RoundBoundaryStats | null;
}) {
  if (!rows || rows.length === 0) {
    return <Empty>No model activity yet.</Empty>;
  }
  const topPeak = Math.max(...rows.map((r) => r.peak_per_cycle));
  return (
    <div style={{ display: "grid", gap: 10 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
        <span className="serif-num" style={{ fontSize: 28 }}>
          {rows.reduce((s, r) => s + r.total, 0)}
        </span>
        <span className="muted" style={{ fontSize: 11 }}>
          api calls · top peak {topPeak}/cycle
        </span>
        {boundary && boundary.samples > 0 && (
          <span className="pill" data-tone="slate" style={{ marginLeft: "auto" }}>
            round-boundary p50 {Math.round(boundary.p50_ms)}ms · p95{" "}
            {Math.round(boundary.p95_ms)}ms
          </span>
        )}
      </div>
      <div className="row-list" style={{ gap: 2 }}>
        {rows.map((r) => {
          const tone =
            r.peak_per_cycle >= 100
              ? "var(--mlc-peach)"
              : r.peak_per_cycle >= 30
              ? "var(--mlc-amber)"
              : "var(--mlc-mint)";
          return (
            <div
              key={r.model_id}
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 70px 70px 70px 1fr",
                alignItems: "center",
                gap: 8,
                fontSize: 11,
                padding: "3px 0",
              }}
            >
              <span style={{ color: "var(--fg-2)" }}>{r.model_id}</span>
              <span className="muted" style={{ textAlign: "right" }}>
                {r.total} total
              </span>
              <span
                className="muted"
                style={{ textAlign: "right" }}
                title="calls in the last hour"
              >
                {r.last_hour}/h
              </span>
              <span
                style={{
                  textAlign: "right",
                  fontVariantNumeric: "tabular-nums",
                  color: tone,
                }}
                title="peak calls in any single cycle"
              >
                peak {r.peak_per_cycle}
              </span>
              <div style={{ minWidth: 0 }}>
                <Sparkline
                  values={r.series}
                  color={tone}
                  height={18}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
