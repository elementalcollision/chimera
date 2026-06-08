# ADR 0168 — Federation connectivity gauge (percolation, v4.120)

**Status:** Proposed (2026-06-08)

## Context

Chimera already materialises a `TRUSTED` projection in Kuzu
(`memory/graph.py`): directed `Peer -[TRUSTED{verdict, drift_score}]-> Peer`
edges, one per latest trust decision. It is **inert** — the graph-export
snapshot emits the raw edges, but nothing reads them back to reason about the
federation's *shape*.

The investigation in
[entropy-graph-subtasking-2026-06-06.md](../research/entropy-graph-subtasking-2026-06-06.md)
(§2a, ranked #2) points at the random-graph-theory result this graph licenses.
Model the trust-reachable federation as a graph whose edges are the dispatches
the policy would `ALLOW`; peer churn, drift rises, and lockdowns are
bond/site **percolation** events. Two numbers fall out and turn an
already-built-but-inert graph into the swarm's single resilience gauge:

- **Connectivity** = |largest trust-reachable component| / N. Below a critical
  connectivity the swarm shatters into capability-islands. For an Erdős–Rényi
  view the giant component exists once mean degree ⟨k⟩ > 1 (Newman 2003;
  Callaway et al. 2000).
- **Hub concentration** = share of trust edges on the single most-connected
  node. Scale-free graphs are robust to random drop-out but fragile to **hub
  removal**; if trust concentrates on one relay, that node's drift/lockdown
  fragments the swarm — a single-point-of-trust-failure.

## Decision

A pure gauge module computes these from the projection; the graph-export
snapshot gains a `federation` block behind a default-OFF flag.

### Code

- `chimera/memory/federation_metrics.py` — new module:
  - `federation_metrics_enabled()` — honours `CHIMERA_FEDERATION_METRICS`
    (default off; same parsing shape as `peer_selection_enabled`, ADR 0167).
  - `FederationConnectivity` — frozen dataclass: `n_nodes`, `n_edges`,
    `largest_component`, `connectivity`, `mean_degree`, `hub_node`,
    `hub_degree`, `hub_concentration`, `isolated_nodes`; `to_dict()`.
  - `compute_connectivity(edges, nodes, *, connective_verdicts=("ALLOW",))` —
    **pure**. Union-find over the undirected projection of connective edges;
    dedupes pairs, ignores self-loops; `nodes` lets edge-less peers count
    toward N (so an all-REFUSE peer correctly lowers connectivity).
  - `from_trusted_rows(rows, nodes)` — adapter for the snapshot's `trusted`
    row shape.
- `chimera/cli.py` — `chimera graph export` adds
  `snapshot["federation"] = from_trusted_rows(...).to_dict()` **only when the
  flag is on**, querying the full `Peer` node set so isolated peers count.
- `chimera/memory/__init__.py` — export the four names.

### CLI / dashboard

- `control-plane/lib/graph.ts` — `GraphSnapshot.federation?` typed as
  `FederationConnectivity`; `readFederationConnectivity()` reader.
- `control-plane/components/widgets/SimpleWidgets.tsx` —
  `FederationConnectivityWidget`: the connectivity %, ⟨k⟩, hub share, and
  isolated count, with `fragmented` / `⟨k⟩ < 1` / `hub risk` pills and a
  single-point-of-trust-failure callout.
- `control-plane/app/page.tsx` — wired into the `federation` group beside the
  emergence journal.

Operator surface is the `CHIMERA_FEDERATION_METRICS` flag; the snapshot is
byte-identical (no `federation` key) until enabled, and the widget shows an
enable hint meanwhile.

## Tests

`tests/test_federation_metrics.py` — 14 cases: flag parsing; empty graph;
single node = fully connected; star federation is connected but hub-concentrated
(⟨k⟩ = 1.5, hub share 0.5); a REFUSE edge leaves its peer isolated; DEGRADE
excluded by default but optional via `connective_verdicts`; two disjoint pairs
fragment to 0.5; duplicate/self edges ignored; `nodes`-supplied isolated peer
lowers connectivity; `from_trusted_rows` matches the snapshot shape. Existing
`test_graph_store` stays green (29 passing across the slice).

The control-plane TypeScript was not compiled in-container (no `node_modules`);
the change follows the existing widget/type/`data-tone` conventions exactly.

## Non-goals

- **Live recompute / alarming.** This ships the gauge and its dashboard
  surface; a drift-style alarm when connectivity drops toward fragmentation is
  a follow-up (the metric is the prerequisite).
- **Stochastic-block-model capability clustering** (research §2b) — valuable
  once N is large enough for blocks to exist; separate ADR.
- **Peer-to-peer trust edges.** Today `TRUSTED` is Self→Peer (a star), so the
  hub is structurally `self`; the union-find core already handles general
  topologies for when peers attest to each other.

## Why this shape

Asymptotic percolation math is *decorative* at N = 1–2 and pays off as the
swarm grows — so this is a "build the gauge now, it pays later" play, not an
urgent behavioural change, which is exactly why it ships as flag-gated
observability with zero effect on the dispatch path. Keeping
`compute_connectivity` pure (union-find over plain tuples) lets the
graph-theory be unit-tested without Kuzu or a live federation, mirroring how
ADR 0167 split its pure `choose` from the async orchestrator.
