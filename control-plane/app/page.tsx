import {
  allMutations,
  allApiCallTokenRows,
  listEntities,
  recentApiCalls,
} from "@/lib/db";
import { costByModel, totalCost } from "@/lib/cost";
import {
  groupTrustJournal,
  readAssemblyJournal,
  readDriftLog,
  readEmergenceCounts,
  readGraphSnapshot,
  readPeers,
  readPhaseTimings,
  readTrustJournal,
} from "@/lib/graph";
import { readFragmentation } from "@/lib/fragmentation";
import { readHeartbeat, readMindFile, readTrustState } from "@/lib/mind";

import CanvasShell, { WidgetDef } from "@/components/CanvasShell";
import StatusWidget from "@/components/widgets/StatusWidget";
import TokenCostWidget from "@/components/widgets/TokenCostWidget";
import {
  ApiCallsWidget,
  AssemblyJournalWidget,
  ChronicleWidget,
  DriftSparklineWidget,
  EmergenceWidget,
  FragmentationWidget,
  GraphWidget,
  InboxWidget,
  MutationsWidget,
  OntologyWidget,
  PeersWidget,
  PhaseTimingsWidget,
  TrustJournalWidget,
} from "@/components/widgets/SimpleWidgets";

export const dynamic = "force-dynamic";

export default async function HomePage() {
  const hb = readHeartbeat();
  const trust = readTrustState();
  const inbox = readMindFile("INBOX.md") ?? "";
  const chronicle = readMindFile("CHRONICLE.md") ?? "";
  const entities = listEntities();
  const calls = recentApiCalls(20);
  const muts = allMutations(20);
  const timings = readPhaseTimings();
  const peers = readPeers();
  const trustJournal = readTrustJournal(50);
  const trustGroups = groupTrustJournal(trustJournal);
  const emergence = readEmergenceCounts();
  const graph = readGraphSnapshot();
  const assemblies = readAssemblyJournal(10);
  const costRows = allApiCallTokenRows();
  const buckets = costByModel(costRows);
  const cost = totalCost(buckets);
  const driftLog = readDriftLog(60);
  const fragmentation = readFragmentation(20);
  const pendingCount = muts.filter((m) => m.status === "pending").length;

  const widgets: WidgetDef[] = [
    {
      id: "status", title: "Status", eyebrow: "agent", icon: "activity",
      chip: hb?.status === "running" ? { tone: "ok", text: hb.status } : undefined,
      group: "agent", layout: { x: 0, y: 0, w: 5, h: 5 }, defaultStatic: true,
      body: <StatusWidget hb={hb} trust={trust} driftHistory={driftLog} />,
    },
    {
      id: "cost", title: "Token cost", eyebrow: "spend", icon: "coins",
      group: "cost", layout: { x: 5, y: 0, w: 7, h: 5 },
      body: <TokenCostWidget buckets={buckets} total={cost} />,
    },
    {
      id: "drift", title: "Drift composite", eyebrow: "trend", icon: "activity",
      group: "agent", layout: { x: 0, y: 5, w: 6, h: 4 },
      body: <DriftSparklineWidget records={driftLog} />,
    },
    {
      id: "phases", title: "Phase timings",
      eyebrow: timings ? `cycle ${timings.cycle}` : "cycle", icon: "timer",
      group: "agent", layout: { x: 6, y: 5, w: 6, h: 4 },
      body: <PhaseTimingsWidget timings={timings} />,
    },
    {
      id: "ontology", title: "Ontology", eyebrow: "entities", icon: "list",
      group: "skills", layout: { x: 0, y: 9, w: 12, h: 4 },
      body: <OntologyWidget entities={entities} />,
    },
    {
      id: "api_calls", title: "Recent API calls", eyebrow: "live", icon: "git",
      group: "cost", layout: { x: 0, y: 13, w: 6, h: 6 },
      body: <ApiCallsWidget calls={calls} />,
    },
    {
      id: "mutations", title: "Mutations", eyebrow: "queue", icon: "workflow",
      chip: pendingCount > 0 ? { tone: "warn", text: `${pendingCount} pending` } : undefined,
      group: "skills", layout: { x: 6, y: 13, w: 6, h: 6 },
      body: <MutationsWidget mutations={muts} />,
    },
    {
      id: "assembly", title: "Skill assembly", eyebrow: "ladder", icon: "sparkles",
      group: "skills", layout: { x: 0, y: 19, w: 12, h: 6 },
      body: <AssemblyJournalWidget entries={assemblies} />,
    },
    {
      id: "graph", title: "Skill graph", eyebrow: "dag", icon: "git",
      group: "skills", layout: { x: 0, y: 25, w: 6, h: 6 },
      body: <GraphWidget graph={graph} />,
    },
    {
      id: "fragmentation", title: "Fragmentation log", eyebrow: "v4.5", icon: "fragment",
      chip: fragmentation.length > 0 ? { tone: "danger", text: `${fragmentation.length} failure(s)` } : undefined,
      group: "agent", layout: { x: 6, y: 25, w: 6, h: 6 },
      body: <FragmentationWidget rows={fragmentation} />,
    },
    {
      id: "peers", title: "Peers", eyebrow: "federation", icon: "network",
      group: "federation", layout: { x: 0, y: 31, w: 6, h: 5 },
      body: <PeersWidget peers={peers} />,
    },
    {
      id: "trust", title: "Peer trust journal", eyebrow: "trust", icon: "shield",
      group: "federation", layout: { x: 6, y: 31, w: 6, h: 5 },
      body: <TrustJournalWidget groups={trustGroups} />,
    },
    {
      id: "emergence", title: "Emergence journal", eyebrow: "observations", icon: "sparkles",
      group: "federation", layout: { x: 0, y: 36, w: 12, h: 5 },
      body: <EmergenceWidget counts={emergence} />,
    },
    {
      id: "inbox", title: "Inbox", eyebrow: "tasks", icon: "inbox",
      group: "mind", layout: { x: 0, y: 41, w: 6, h: 6 },
      body: <InboxWidget content={inbox} />,
    },
    {
      id: "chronicle", title: "Chronicle", eyebrow: "today", icon: "book",
      group: "mind", layout: { x: 6, y: 41, w: 6, h: 6 },
      body: <ChronicleWidget content={chronicle} />,
    },
  ];

  return <CanvasShell widgets={widgets} />;
}
