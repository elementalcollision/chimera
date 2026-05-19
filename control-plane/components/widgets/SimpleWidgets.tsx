/**
 * Six small widgets ported from the v3.x dashboard's Section blocks.
 * Each takes already-fetched data as props so the canvas page stays
 * the single SSR boundary.
 */

import { Entity, ApiCall, Mutation } from "@/lib/db";
import {
  AssemblyJournalEntry,
  EmergenceCounts,
  GraphSnapshot,
  PeerEntry,
  PhaseTimings,
  TrustGroupRow,
  TrustJournalRecord,
} from "@/lib/graph";

function Empty({ children }: { children: React.ReactNode }) {
  return <p className="text-zinc-500 italic">{children}</p>;
}

// ── Phase timings ────────────────────────────────────────────

export function PhaseTimingsWidget({ timings }: { timings: PhaseTimings | null }) {
  if (!timings) return <Empty>No phase_timings.json yet.</Empty>;
  return (
    <div>
      <div className="text-zinc-500 mb-2">cycle {timings.cycle}</div>
      <div className="grid grid-cols-3 gap-2">
        {Object.entries(timings.phase_times_ms).map(([k, v]) => (
          <div key={k} className="border border-zinc-200 dark:border-zinc-800 rounded px-2 py-1">
            <div className="text-zinc-500">{k}</div>
            <div className="font-mono">{v.toFixed(0)} ms</div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Ontology ────────────────────────────────────────────────

export function OntologyWidget({ entities }: { entities: Entity[] }) {
  if (entities.length === 0) return <Empty>No entities yet.</Empty>;
  return (
    <table className="w-full">
      <thead className="text-left text-zinc-500">
        <tr><th>state</th><th>kind</th><th>name</th><th>cycle</th></tr>
      </thead>
      <tbody>
        {entities.map((e) => (
          <tr key={e.id} className="border-t border-zinc-200 dark:border-zinc-800">
            <td className="py-1 pr-2 font-mono">{e.kfm_state}</td>
            <td className="pr-2">{e.kind}</td>
            <td className="pr-2">{e.name}</td>
            <td>{e.state_entered_at_cycle}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// ── Recent API calls ────────────────────────────────────────

export function ApiCallsWidget({ calls }: { calls: ApiCall[] }) {
  if (calls.length === 0) return <Empty>No api_calls yet.</Empty>;
  return (
    <table className="w-full">
      <thead className="text-left text-zinc-500">
        <tr><th>cycle</th><th>provider</th><th>model</th><th>in</th><th>out</th><th>ms</th></tr>
      </thead>
      <tbody>
        {calls.map((c) => (
          <tr key={c.id} className="border-t border-zinc-200 dark:border-zinc-800">
            <td className="py-1 pr-2">{c.cycle}</td>
            <td className="pr-2">{c.provider}</td>
            <td className="pr-2 truncate max-w-[14rem]">{c.model_id}</td>
            <td className="pr-2">{c.input_tokens ?? "—"}</td>
            <td className="pr-2">{c.output_tokens ?? "—"}</td>
            <td>{c.latency_ms ?? "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// ── Mutations ───────────────────────────────────────────────

export function MutationsWidget({ mutations }: { mutations: Mutation[] }) {
  if (mutations.length === 0) return <Empty>No mutations yet.</Empty>;
  return (
    <table className="w-full">
      <thead className="text-left text-zinc-500">
        <tr><th>id</th><th>type</th><th>status</th><th>reason</th></tr>
      </thead>
      <tbody>
        {mutations.map((m) => (
          <tr key={m.id} className="border-t border-zinc-200 dark:border-zinc-800">
            <td className="py-1 pr-2">#{m.id}</td>
            <td className="pr-2">{m.type}</td>
            <td className="pr-2">{m.status}</td>
            <td className="pr-2 truncate max-w-[20rem]">{m.reason ?? ""}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// ── Peers ───────────────────────────────────────────────────

export function PeersWidget({ peers }: { peers: PeerEntry[] }) {
  if (peers.length === 0) return <Empty>No peers in registry.</Empty>;
  return (
    <table className="w-full">
      <thead className="text-left text-zinc-500">
        <tr><th>agent_id</th><th>version</th><th>host</th><th>transport</th></tr>
      </thead>
      <tbody>
        {peers.map((p, i) => (
          <tr key={i} className="border-t border-zinc-200 dark:border-zinc-800">
            <td className="py-1 pr-2 font-mono">{p.agent_id}</td>
            <td className="pr-2">{p.version}</td>
            <td className="pr-2">{p.host}</td>
            <td>{p.reach?.transport ?? "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// ── Peer trust journal ──────────────────────────────────────

export function TrustJournalWidget({ groups }: { groups: TrustGroupRow[] }) {
  if (groups.length === 0) return <Empty>No peer-trust decisions logged.</Empty>;
  return (
    <table className="w-full">
      <thead className="text-left text-zinc-500">
        <tr><th>peer</th><th>decisions</th><th>latest</th><th>drift</th></tr>
      </thead>
      <tbody>
        {groups.map((g, i) => (
          <tr key={i} className="border-t border-zinc-200 dark:border-zinc-800">
            <td className="py-1 pr-2 font-mono">{g.peer}</td>
            <td className="pr-2">{g.decisions}</td>
            <td className="pr-2">{g.latest?.decision ?? "—"}</td>
            <td>{g.latest?.drift_score ?? "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// ── Graph snapshot (skill DAG) ──────────────────────────────

export function GraphWidget({ graph }: { graph: GraphSnapshot | null }) {
  if (!graph) return <Empty>No graph snapshot yet.</Empty>;
  return (
    <div className="space-y-3">
      <div>
        <div className="text-zinc-500 mb-1">Skill DAG ({graph.skills.length})</div>
        {graph.skills.length === 0 ? (
          <Empty>(no dynamic skills)</Empty>
        ) : (
          <ul>
            {graph.skills.map((s, i) => (
              <li key={i}>
                <span className="font-mono">{s.name}</span>
                {(s.deps ?? []).length > 0 && (
                  <span className="text-zinc-500"> → deps: {(s.deps ?? []).join(", ")}</span>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
      <div>
        <div className="text-zinc-500 mb-1">Provenance</div>
        {graph.proposed.length === 0 && graph.activated.length === 0 ? (
          <Empty>(no provenance edges)</Empty>
        ) : (
          <ul>
            {graph.proposed.map((p, i) => (
              <li key={`p-${i}`}>
                #{p.id} [{p.type}] → {p.entity_name}
              </li>
            ))}
            {graph.activated.map((a, i) => (
              <li key={`a-${i}`}>
                #{a.id} ⇒ skill <span className="font-mono">{a.skill}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

// ── Emergence journal ───────────────────────────────────────

export function EmergenceWidget({ counts }: { counts: EmergenceCounts }) {
  if (counts.localPeers.length === 0 && counts.remotePeers.length === 0)
    return <Empty>No emergence observations yet.</Empty>;
  return (
    <div className="space-y-2">
      {counts.localPeers.length > 0 && (
        <div>
          <div className="text-zinc-500 mb-1">local</div>
          <ul>
            {counts.localPeers.map((r) => (
              <li key={`l-${r.name}`}>
                <span className="font-mono">{r.name}</span> · {r.observations}
              </li>
            ))}
          </ul>
        </div>
      )}
      {counts.remotePeers.length > 0 && (
        <div>
          <div className="text-zinc-500 mb-1">remote</div>
          <ul>
            {counts.remotePeers.map((r, i) => (
              <li key={`r-${i}`}>
                <span className="font-mono">{r.host}/{r.peer}</span> · {r.observations}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

// ── Skill assembly attempts ─────────────────────────────────

export function AssemblyJournalWidget({ entries }: { entries: AssemblyJournalEntry[] }) {
  if (entries.length === 0) return <Empty>No assemblies logged.</Empty>;
  return (
    <div className="space-y-2">
      {entries.map((e) => (
        <div key={`${e.mutation_id}-${e.recorded_at}`} className="border-l-2 border-amber-400 pl-2">
          <div className="text-zinc-500">
            #{e.mutation_id} · {e.skill_name} · {e.winning_tier ?? "—"} · {Math.round(e.final_score * 100)}%
          </div>
          {e.attempts.map((a, i) => (
            <div key={i} className="ml-2">
              [{a.tier}] base={Math.round(a.validation_score * 100)}%
              {a.revised && ` revised=${Math.round((a.revised_score ?? 0) * 100)}%`}
              {a.witnesses.length > 0 && ` witnesses=${a.witnesses.join(",")}`}
              {a.winning_witness && ` winner=${a.winning_witness}`}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

// ── Mind file (INBOX / chronicle) ───────────────────────────

export function MindFileWidget({ content }: { content: string }) {
  return (
    <pre className="whitespace-pre-wrap bg-zinc-100 dark:bg-zinc-900 p-2 rounded">
      {content || "(empty)"}
    </pre>
  );
}
