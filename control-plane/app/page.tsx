import {
  allMutations,
  ladderOutcomesByTier,
  listEntities,
  pendingMutations,
  recentActivity,
  recentApiCalls,
} from "@/lib/db";
import { readHeartbeat, readMindFile, readTrustState, tierLabel } from "@/lib/mind";
import {
  groupTrustJournal,
  readEmergenceCounts,
  readGraphSnapshot,
  readPeers,
  readPhaseTimings,
  readTrustJournal,
} from "@/lib/graph";

export const dynamic = "force-dynamic";

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-8">
      <h2 className="text-lg font-semibold mb-2 border-b border-zinc-300 dark:border-zinc-700 pb-1">
        {title}
      </h2>
      {children}
    </section>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <p className="text-zinc-500 italic">{children}</p>;
}

export default async function HomePage() {
  const hb = readHeartbeat();
  const trust = readTrustState();
  const inbox = readMindFile("INBOX.md") ?? "";
  const chronicle = readMindFile("CHRONICLE.md") ?? "";
  const entities = listEntities();
  const calls = recentApiCalls(15);
  const muts = allMutations(20);
  const pending = pendingMutations();
  const activity = recentActivity(16);
  const ladder = ladderOutcomesByTier();
  const graph = readGraphSnapshot();
  const trustJournal = readTrustJournal(20);
  const timings = readPhaseTimings();
  const peers = readPeers();
  const trustGroups = groupTrustJournal(trustJournal);
  const emergence = readEmergenceCounts();

  return (
    <>
      <Section title="Status">
        {!hb ? (
          <Empty>HEARTBEAT.md not found (set CHIMERA_MIND_DIR or run Chimera once).</Empty>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <Card label="Cycle" value={String(hb.cycle)} />
            <Card label="Status" value={hb.status} />
            <Card
              label="Trust tier"
              value={trust ? `${trust.current_tier} (${tierLabel(trust.current_tier)})` : hb.trust_tier}
            />
            <Card
              label="Last readiness"
              value={trust ? trust.last_readiness.toFixed(2) : "—"}
            />
            <Card
              label="Anthropic calls"
              value={String(hb.model_usage.anthropic_calls ?? 0)}
            />
            <Card
              label="OpenRouter calls"
              value={String(hb.model_usage.openrouter_calls ?? 0)}
            />
            <Card
              label="Last drift score"
              value={hb.last_drift_score == null ? "—" : String(hb.last_drift_score)}
            />
            <Card label="Session started" value={hb.session_started_at ?? "—"} />
          </div>
        )}
      </Section>

      <Section title="INBOX">
        <pre className="whitespace-pre-wrap text-xs bg-zinc-100 dark:bg-zinc-900 p-3 rounded">
          {inbox || "(empty)"}
        </pre>
      </Section>

      <Section title="Ontology (entities)">
        {entities.length === 0 ? (
          <Empty>No entities yet.</Empty>
        ) : (
          <table className="w-full text-xs">
            <thead className="text-left text-zinc-500">
              <tr>
                <th className="py-1">state</th>
                <th>kind</th>
                <th>name</th>
                <th>cycle</th>
                <th>id</th>
              </tr>
            </thead>
            <tbody>
              {entities.map((e) => (
                <tr key={e.id} className="border-t border-zinc-200 dark:border-zinc-800">
                  <td className="py-1 pr-3 font-mono">{e.kfm_state}</td>
                  <td className="pr-3">{e.kind}</td>
                  <td className="pr-3">{e.name}</td>
                  <td className="pr-3">{e.state_entered_at_cycle}</td>
                  <td className="text-zinc-500">{e.id.slice(0, 8)}…</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      <Section title="Recent API calls">
        {calls.length === 0 ? (
          <Empty>No api_calls yet.</Empty>
        ) : (
          <table className="w-full text-xs">
            <thead className="text-left text-zinc-500">
              <tr>
                <th>cycle</th>
                <th>provider</th>
                <th>model</th>
                <th>in</th>
                <th>out</th>
                <th>ms</th>
                <th>finish</th>
              </tr>
            </thead>
            <tbody>
              {calls.map((c) => (
                <tr key={c.id} className="border-t border-zinc-200 dark:border-zinc-800">
                  <td className="py-1 pr-3">{c.cycle}</td>
                  <td className="pr-3">{c.provider}</td>
                  <td className="pr-3 truncate max-w-[18rem]">{c.model_id}</td>
                  <td className="pr-3">{c.input_tokens ?? "—"}</td>
                  <td className="pr-3">{c.output_tokens ?? "—"}</td>
                  <td className="pr-3">{c.latency_ms ?? "—"}</td>
                  <td className="pr-3">{c.error ? `error: ${c.error.slice(0, 60)}` : c.finish_reason ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      <Section title={`Pending mutations (${pending.length})`}>
        {pending.length === 0 ? (
          <Empty>(no pending mutations)</Empty>
        ) : (
          <ul className="space-y-2">
            {pending.map((m) => (
              <li key={m.id} className="border-l-2 border-amber-400 pl-3">
                <div className="text-xs text-zinc-500">#{m.id} · {m.type} · {m.created_at}</div>
                <pre className="whitespace-pre-wrap text-xs">{m.payload}</pre>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="Trust history">
        {!trust ? (
          <Empty>No trust state yet.</Empty>
        ) : (
          <table className="w-full text-xs">
            <thead className="text-left text-zinc-500">
              <tr>
                <th>when</th>
                <th>kind</th>
                <th>from</th>
                <th>to</th>
                <th>reason</th>
              </tr>
            </thead>
            <tbody>
              {trust.history.slice(-10).reverse().map((e, i) => (
                <tr key={i} className="border-t border-zinc-200 dark:border-zinc-800">
                  <td className="py-1 pr-3 text-zinc-500">{e.timestamp}</td>
                  <td className="pr-3">{e.kind}</td>
                  <td className="pr-3">T{e.from_tier}</td>
                  <td className="pr-3">T{e.to_tier}</td>
                  <td className="pr-3 text-zinc-700 dark:text-zinc-300">{e.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      <Section title="Tier ladder outcomes">
        {Object.keys(ladder).length === 0 ? (
          <Empty>No ladder data yet.</Empty>
        ) : (
          <table className="w-full text-xs">
            <thead className="text-left text-zinc-500">
              <tr>
                <th>tier</th>
                <th>success</th>
                <th>transient_fail</th>
                <th>retry_exhausted</th>
                <th>non_retriable</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(ladder).map(([tier, outcomes]) => (
                <tr key={tier} className="border-t border-zinc-200 dark:border-zinc-800">
                  <td className="py-1 pr-3 font-semibold">{tier}</td>
                  <td className="pr-3">{outcomes.success ?? 0}</td>
                  <td className="pr-3">{outcomes.transient_fail ?? 0}</td>
                  <td className="pr-3">{outcomes.retry_exhausted ?? 0}</td>
                  <td className="pr-3">{outcomes.non_retriable ?? 0}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      <Section title="Recent activity (per phase)">
        {activity.length === 0 ? (
          <Empty>No activity rows.</Empty>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
            {activity.map((a) => (
              <div
                key={`${a.cycle}-${a.cell_id}`}
                className="border border-zinc-200 dark:border-zinc-800 rounded px-2 py-1"
              >
                <span className="text-zinc-500">cycle {a.cycle}</span> · {a.cell_id}
              </div>
            ))}
          </div>
        )}
      </Section>

      <Section title="Chronicle (latest)">
        <pre className="whitespace-pre-wrap text-xs bg-zinc-100 dark:bg-zinc-900 p-3 rounded max-h-[40rem] overflow-y-auto">
          {chronicle.trim() || "(empty)"}
        </pre>
      </Section>

      <Section title={`Phase timings${timings ? ` (cycle ${timings.cycle})` : ""}`}>
        {!timings ? (
          <Empty>No phase_timings.json yet. Run `chimera run` once.</Empty>
        ) : (
          <div className="grid grid-cols-3 md:grid-cols-5 gap-2 text-xs">
            {Object.entries(timings.phase_times_ms).map(([k, v]) => (
              <div key={k} className="border border-zinc-200 dark:border-zinc-800 rounded px-2 py-1">
                <div className="text-zinc-500">{k}</div>
                <div className="font-mono">{v.toFixed(0)} ms</div>
              </div>
            ))}
          </div>
        )}
      </Section>

      <Section title={`Graph${graph ? ` (snapshot ${graph.generated_at})` : ""}`}>
        {!graph ? (
          <Empty>
            No graph snapshot yet. Run <code className="font-mono">chimera graph rebuild</code> then{" "}
            <code className="font-mono">chimera graph export</code>.
          </Empty>
        ) : (
          <div className="space-y-4">
            <div>
              <h3 className="text-sm font-semibold mb-1">Skill DAG ({graph.skills.length})</h3>
              {graph.skills.length === 0 ? (
                <Empty>(no dynamic skills)</Empty>
              ) : (
                <table className="w-full text-xs">
                  <thead className="text-left text-zinc-500">
                    <tr><th>skill</th><th>depends_on</th><th>uses_tool</th></tr>
                  </thead>
                  <tbody>
                    {graph.skills.map((s, i) => (
                      <tr key={i} className="border-t border-zinc-200 dark:border-zinc-800">
                        <td className="py-1 pr-3 font-mono">{s.name}</td>
                        <td className="pr-3">{(s.deps ?? []).filter(Boolean).join(", ") || "—"}</td>
                        <td className="pr-3">{(s.tools ?? []).filter(Boolean).join(", ") || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
            <div>
              <h3 className="text-sm font-semibold mb-1">Provenance (latest)</h3>
              {graph.proposed.length === 0 && graph.activated.length === 0 ? (
                <Empty>(no provenance edges)</Empty>
              ) : (
                <ul className="text-xs space-y-1">
                  {graph.proposed.map((p, i) => (
                    <li key={`p-${i}`}>
                      #{p.id} [{p.type}] {p.status} →{" "}
                      <span className="text-zinc-500">{p.entity_kind}</span>{" "}
                      <span className="font-mono">{p.entity_name}</span>
                    </li>
                  ))}
                  {graph.activated.map((a, i) => (
                    <li key={`a-${i}`}>
                      #{a.id} ⇒ activated skill <span className="font-mono">{a.skill}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        )}
      </Section>

      <Section title={`Peers (${peers.length})`}>
        {peers.length === 0 ? (
          <Empty>No peers in registry. Run `chimera serve` or `chimera peers sync`.</Empty>
        ) : (
          <table className="w-full text-xs">
            <thead className="text-left text-zinc-500">
              <tr>
                <th className="py-1">agent_id</th>
                <th>version</th>
                <th>host</th>
                <th>transport</th>
                <th>registered_at</th>
              </tr>
            </thead>
            <tbody>
              {peers.map((p, i) => (
                <tr key={i} className="border-t border-zinc-200 dark:border-zinc-800">
                  <td className="py-1 pr-3 font-mono">{p.agent_id}</td>
                  <td className="pr-3">{p.version}</td>
                  <td className="pr-3">{p.host}</td>
                  <td className="pr-3">{p.reach?.transport ?? "—"}</td>
                  <td className="pr-3 text-zinc-500">{p.registered_at}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      <Section
        title={`Emergence journal (${emergence.localPeers.length} local, ${emergence.remotePeers.length} remote)`}
      >
        {emergence.localPeers.length === 0 && emergence.remotePeers.length === 0 ? (
          <Empty>No emergence observations yet.</Empty>
        ) : (
          <div className="text-xs space-y-2">
            {emergence.localPeers.length > 0 && (
              <div>
                <div className="text-zinc-500 mb-1">local</div>
                <ul>
                  {emergence.localPeers.map((r) => (
                    <li key={`l-${r.name}`}>
                      <span className="font-mono">{r.name}</span> · {r.observations} observation(s)
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {emergence.remotePeers.length > 0 && (
              <div>
                <div className="text-zinc-500 mb-1">remote</div>
                <ul>
                  {emergence.remotePeers.map((r, i) => (
                    <li key={`r-${i}`}>
                      <span className="font-mono">{r.host}/{r.peer}</span> · {r.observations}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </Section>

      <Section title={`Peer trust journal (${trustGroups.length} peer(s), ${trustJournal.length} decision(s))`}>
        {trustGroups.length === 0 ? (
          <Empty>(no peer-trust decisions logged yet)</Empty>
        ) : (
          <table className="w-full text-xs">
            <thead className="text-left text-zinc-500">
              <tr>
                <th>peer</th>
                <th>decisions</th>
                <th>latest</th>
                <th>drift</th>
                <th>when</th>
              </tr>
            </thead>
            <tbody>
              {trustGroups.map((g, i) => (
                <tr key={i} className="border-t border-zinc-200 dark:border-zinc-800">
                  <td className="py-1 pr-3 font-mono">{g.peer}</td>
                  <td className="pr-3">{g.decisions}</td>
                  <td className="pr-3">{g.latest?.decision ?? "—"}</td>
                  <td className="pr-3">{g.latest?.drift_score ?? "—"}</td>
                  <td className="pr-3 text-zinc-500">{g.latest?.recorded_at ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      <Section title="All mutations (last 20)">
        {muts.length === 0 ? (
          <Empty>No mutations yet.</Empty>
        ) : (
          <table className="w-full text-xs">
            <thead className="text-left text-zinc-500">
              <tr>
                <th>id</th>
                <th>type</th>
                <th>status</th>
                <th>created</th>
                <th>reason</th>
              </tr>
            </thead>
            <tbody>
              {muts.map((m) => (
                <tr key={m.id} className="border-t border-zinc-200 dark:border-zinc-800">
                  <td className="py-1 pr-3">#{m.id}</td>
                  <td className="pr-3">{m.type}</td>
                  <td className="pr-3">{m.status}</td>
                  <td className="pr-3 text-zinc-500">{m.created_at}</td>
                  <td className="pr-3">{m.reason ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>
    </>
  );
}

function Card({ label, value }: { label: string; value: string }) {
  return (
    <div className="border border-zinc-200 dark:border-zinc-800 rounded p-3">
      <div className="text-xs text-zinc-500">{label}</div>
      <div className="text-base mt-1 font-semibold">{value}</div>
    </div>
  );
}
