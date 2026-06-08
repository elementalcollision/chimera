"""Federation connectivity gauge — percolation over the TRUSTED graph (ADR 0168).

The Kuzu ``TRUSTED`` projection (``memory/graph.py``) records Chimera's
trust decisions as directed ``Peer -[TRUSTED{verdict}]-> Peer`` edges, but it
is **inert**: nothing reads it back to reason about the federation's shape.

Random graph theory says what to compute over it. Model the *trust-reachable*
federation as a graph whose edges are the dispatches the policy would
``ALLOW``. Peer churn, drift rises, and lockdowns delete edges — bond/site
percolation events. Two numbers fall out:

- **Connectivity** = |largest trust-reachable component| / N. Below a critical
  connectivity the swarm shatters into capability-islands that can't
  collectively cover the task set. For an Erdős–Rényi view the giant component
  appears at mean degree ⟨k⟩ > 1 (Newman 2003; Callaway et al. 2000).
- **Hub concentration** = the share of trust edges incident on the single most
  connected node. Trust that concentrates on one relay is a
  single-point-of-trust-failure: that node's drift/lockdown fragments the
  swarm (scale-free graphs are robust to random drop-out, fragile to hub
  removal).

This module is the **pure** computation plus a snapshot reader. It is
default-OFF: the graph-export snapshot only gains a ``federation`` block when
``CHIMERA_FEDERATION_METRICS`` is enabled, so the artifact is byte-identical
until opted in.
"""

from __future__ import annotations

import os
from collections import defaultdict
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping

# Verdicts that constitute a trust-reachable edge. ``ALLOW`` only by default —
# DEGRADE proceeds but downgraded, REFUSE never dispatches.
_DEFAULT_CONNECTIVE = ("ALLOW",)


def federation_metrics_enabled() -> bool:
    """Honour ``CHIMERA_FEDERATION_METRICS`` (default: off, ADR 0168).

    Same parsing shape as ``peer_selection_enabled`` (ADR 0167).
    """
    raw = os.environ.get("CHIMERA_FEDERATION_METRICS", "").strip().lower()
    return raw in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class FederationConnectivity:
    """Percolation/resilience gauge over the trust-reachable federation."""

    n_nodes: int
    n_edges: int            # distinct connective (e.g. ALLOW) peer pairs
    largest_component: int
    connectivity: float     # largest_component / n_nodes (1.0 when n_nodes ≤ 1)
    mean_degree: float      # ⟨k⟩ = 2·n_edges / n_nodes; giant component at ⟨k⟩>1
    hub_node: str | None    # most trust-connected node
    hub_degree: int
    hub_concentration: float  # hub_degree / (2·n_edges); 1.0 ⇒ pure star
    isolated_nodes: int     # nodes with no connective edge

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def add(self, x: str) -> None:
        self.parent.setdefault(x, x)

    def find(self, x: str) -> str:
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        # path compression
        while self.parent[x] != root:
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def compute_connectivity(
    edges: Iterable[tuple[str, str, str]],
    nodes: Iterable[str] | None = None,
    *,
    connective_verdicts: tuple[str, ...] = _DEFAULT_CONNECTIVE,
) -> FederationConnectivity:
    """Compute the connectivity gauge from ``(src, dst, verdict)`` edges.

    ``nodes`` optionally supplies the full node set (so peers with no edge —
    e.g. every dispatch REFUSEd — still count toward N and lower connectivity).
    When omitted, the node set is derived from the edge endpoints. Edges are
    treated as **undirected** for connectivity (reachability is symmetric for
    "can the swarm collaborate"); self-loops and duplicate pairs are ignored.
    """
    connective = {v.upper() for v in connective_verdicts}
    uf = _UnionFind()
    node_set: set[str] = set(nodes) if nodes is not None else set()
    for n in node_set:
        uf.add(n)

    pairs: set[frozenset[str]] = set()
    degree: dict[str, int] = defaultdict(int)
    for src, dst, verdict in edges:
        node_set.add(src)
        node_set.add(dst)
        uf.add(src)
        uf.add(dst)
        if (verdict or "").upper() not in connective:
            continue
        if src == dst:
            continue
        pair = frozenset((src, dst))
        if pair in pairs:
            continue
        pairs.add(pair)
        uf.union(src, dst)
        degree[src] += 1
        degree[dst] += 1

    n = len(node_set)
    n_edges = len(pairs)
    if n == 0:
        return FederationConnectivity(0, 0, 0, 0.0, 0.0, None, 0, 0.0, 0)

    comp_size: dict[str, int] = defaultdict(int)
    for node in node_set:
        comp_size[uf.find(node)] += 1
    largest = max(comp_size.values())

    hub_node, hub_degree = (None, 0)
    if degree:
        hub_node = max(degree, key=lambda k: (degree[k], k))
        hub_degree = degree[hub_node]
    total_degree = 2 * n_edges
    hub_concentration = (hub_degree / total_degree) if total_degree else 0.0
    isolated = sum(1 for node in node_set if degree[node] == 0)

    return FederationConnectivity(
        n_nodes=n,
        n_edges=n_edges,
        largest_component=largest,
        connectivity=(largest / n) if n > 1 else 1.0,
        mean_degree=total_degree / n,
        hub_node=hub_node,
        hub_degree=hub_degree,
        hub_concentration=hub_concentration,
        isolated_nodes=isolated,
    )


def from_trusted_rows(
    trusted_rows: Iterable[Mapping[str, Any]],
    nodes: Iterable[str] | None = None,
    *,
    connective_verdicts: tuple[str, ...] = _DEFAULT_CONNECTIVE,
) -> FederationConnectivity:
    """Compute the gauge from graph-snapshot ``trusted`` rows.

    Each row is the shape the ``chimera graph export`` snapshot emits:
    ``{"from": <agent_id>, "to": <agent_id>, "verdict": <str>, ...}``.
    """
    edges = (
        (str(r.get("from")), str(r.get("to")), str(r.get("verdict") or ""))
        for r in trusted_rows
    )
    return compute_connectivity(edges, nodes, connective_verdicts=connective_verdicts)
