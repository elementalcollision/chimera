import { Heartbeat, TrustState, tierLabel } from "@/lib/mind";

interface Props {
  hb: Heartbeat | null;
  trust: TrustState | null;
}

function Card({ label, value }: { label: string; value: string }) {
  return (
    <div className="border border-zinc-200 dark:border-zinc-800 rounded p-2">
      <div className="text-zinc-500">{label}</div>
      <div className="mt-1 font-semibold">{value}</div>
    </div>
  );
}

export default function StatusWidget({ hb, trust }: Props) {
  if (!hb) return <p className="text-zinc-500 italic">HEARTBEAT.md not found.</p>;
  return (
    <div className="grid grid-cols-2 gap-2">
      <Card label="Cycle" value={String(hb.cycle)} />
      <Card label="Status" value={hb.status} />
      <Card
        label="Trust tier"
        value={trust ? `${trust.current_tier} (${tierLabel(trust.current_tier)})` : hb.trust_tier}
      />
      <Card
        label="Readiness"
        value={trust ? trust.last_readiness.toFixed(2) : "—"}
      />
      <Card label="Anthropic calls" value={String(hb.model_usage.anthropic_calls ?? 0)} />
      <Card label="OpenRouter calls" value={String(hb.model_usage.openrouter_calls ?? 0)} />
      <Card label="Last drift" value={hb.last_drift_score == null ? "—" : String(hb.last_drift_score)} />
      <Card label="Session started" value={hb.session_started_at?.slice(0, 16) ?? "—"} />
    </div>
  );
}
