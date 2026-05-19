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
import { readHeartbeat, readMindFile, readTrustState } from "@/lib/mind";

import CanvasShell, { WidgetDef } from "@/components/CanvasShell";
import DriftSparklineWidget from "@/components/widgets/DriftSparklineWidget";
import StatusWidget from "@/components/widgets/StatusWidget";
import TokenCostWidget from "@/components/widgets/TokenCostWidget";
import {
  ApiCallsWidget,
  AssemblyJournalWidget,
  EmergenceWidget,
  GraphWidget,
  MindFileWidget,
  MutationsWidget,
  OntologyWidget,
  PeersWidget,
  PhaseTimingsWidget,
  TrustJournalWidget,
} from "@/components/widgets/SimpleWidgets";

export const dynamic = "force-dynamic";

export default async function HomePage() {
  // SSR-fetch every datum once; widgets are pure render-from-props.
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

  const widgets: WidgetDef[] = [
    {
      id: "status",
      title: "Status",
      layout: { x: 0, y: 0, w: 5, h: 5 },
      defaultStatic: true,
      body:<StatusWidget hb={hb} trust={trust} />,
    },
    {
      id: "token-cost",
      title: "Token cost",
      layout: { x: 5, y: 0, w: 7, h: 5 },
      body:<TokenCostWidget buckets={buckets} total={cost} />,
    },
    {
      id: "drift-sparkline",
      title: "Drift composite (last 60)",
      layout: { x: 0, y: 5, w: 6, h: 4 },
      body:<DriftSparklineWidget records={driftLog} />,
    },
    {
      id: "phase-timings",
      title: "Phase timings",
      layout: { x: 6, y: 5, w: 6, h: 4 },
      body:<PhaseTimingsWidget timings={timings} />,
    },
    {
      id: "ontology",
      title: "Ontology",
      layout: { x: 0, y: 9, w: 12, h: 4 },
      body:<OntologyWidget entities={entities} />,
    },
    {
      id: "api-calls",
      title: "Recent API calls",
      layout: { x: 0, y: 9, w: 6, h: 6 },
      body:<ApiCallsWidget calls={calls} />,
    },
    {
      id: "mutations",
      title: "Mutations",
      layout: { x: 6, y: 9, w: 6, h: 6 },
      body:<MutationsWidget mutations={muts} />,
    },
    {
      id: "assembly",
      title: "Skill assembly attempts",
      layout: { x: 0, y: 15, w: 12, h: 6 },
      body:<AssemblyJournalWidget entries={assemblies} />,
    },
    {
      id: "graph",
      title: "Graph (snapshot)",
      layout: { x: 0, y: 21, w: 6, h: 6 },
      body:<GraphWidget graph={graph} />,
    },
    {
      id: "peers",
      title: "Peers",
      layout: { x: 6, y: 21, w: 6, h: 6 },
      body:<PeersWidget peers={peers} />,
    },
    {
      id: "trust",
      title: "Peer trust journal",
      layout: { x: 0, y: 27, w: 6, h: 5 },
      body:<TrustJournalWidget groups={trustGroups} />,
    },
    {
      id: "emergence",
      title: "Emergence journal",
      layout: { x: 6, y: 27, w: 6, h: 5 },
      body:<EmergenceWidget counts={emergence} />,
    },
    {
      id: "inbox",
      title: "INBOX",
      layout: { x: 0, y: 32, w: 6, h: 6 },
      body:<MindFileWidget content={inbox} />,
    },
    {
      id: "chronicle",
      title: "Chronicle",
      layout: { x: 6, y: 32, w: 6, h: 6 },
      body:<MindFileWidget content={chronicle.slice(-4000)} />,
    },
  ];

  return <CanvasShell widgets={widgets} />;
}
