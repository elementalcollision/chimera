"""Tests for ADR 0168 federation connectivity gauge."""

from __future__ import annotations

import pytest

from chimera.memory import (
    compute_connectivity,
    federation_metrics_enabled,
    from_trusted_rows,
)


# ── flag parsing ────────────────────────────────────────────


def test_flag_off_by_default(monkeypatch):
    monkeypatch.delenv("CHIMERA_FEDERATION_METRICS", raising=False)
    assert federation_metrics_enabled() is False


@pytest.mark.parametrize("val", ["1", "true", "YES", "on"])
def test_flag_truthy(monkeypatch, val):
    monkeypatch.setenv("CHIMERA_FEDERATION_METRICS", val)
    assert federation_metrics_enabled() is True


# ── compute_connectivity ────────────────────────────────────


def test_empty_graph():
    m = compute_connectivity([])
    assert m.n_nodes == 0
    assert m.connectivity == 0.0
    assert m.hub_node is None


def test_single_node_is_fully_connected():
    m = compute_connectivity([], nodes=["self"])
    assert m.n_nodes == 1
    assert m.largest_component == 1
    assert m.connectivity == 1.0
    assert m.isolated_nodes == 1


def test_star_federation_is_connected_but_hub_concentrated():
    # self trusts three peers — a pure star (the single-relay topology).
    edges = [
        ("self", "a", "ALLOW"),
        ("self", "b", "ALLOW"),
        ("self", "c", "ALLOW"),
    ]
    m = compute_connectivity(edges)
    assert m.n_nodes == 4
    assert m.n_edges == 3
    assert m.largest_component == 4
    assert m.connectivity == 1.0
    # ⟨k⟩ = 2·3 / 4 = 1.5 > 1 ⇒ giant component exists.
    assert m.mean_degree == pytest.approx(1.5)
    # self carries all 3 of the 3 undirected edges ⇒ 3 / (2·3) = 0.5.
    assert m.hub_node == "self"
    assert m.hub_degree == 3
    assert m.hub_concentration == pytest.approx(0.5)
    assert m.isolated_nodes == 0


def test_refused_edge_leaves_peer_isolated():
    edges = [
        ("self", "a", "ALLOW"),
        ("self", "b", "REFUSE"),  # not connective
    ]
    m = compute_connectivity(edges)
    assert m.n_nodes == 3  # self, a, b all known
    assert m.n_edges == 1
    assert m.largest_component == 2  # self–a
    assert m.connectivity == pytest.approx(2 / 3)
    assert m.isolated_nodes == 1  # b


def test_degrade_excluded_by_default_but_optional():
    edges = [("self", "a", "DEGRADE")]
    assert compute_connectivity(edges).n_edges == 0
    widened = compute_connectivity(edges, connective_verdicts=("ALLOW", "DEGRADE"))
    assert widened.n_edges == 1


def test_two_disjoint_pairs_fragment():
    edges = [
        ("a", "b", "ALLOW"),
        ("c", "d", "ALLOW"),
    ]
    m = compute_connectivity(edges)
    assert m.n_nodes == 4
    assert m.largest_component == 2
    assert m.connectivity == pytest.approx(0.5)


def test_duplicate_and_self_edges_ignored():
    edges = [
        ("self", "a", "ALLOW"),
        ("a", "self", "ALLOW"),  # same undirected pair
        ("self", "self", "ALLOW"),  # self-loop
    ]
    m = compute_connectivity(edges)
    assert m.n_edges == 1
    assert m.hub_degree == 1


def test_isolated_node_via_nodes_argument():
    # A peer known to the federation but with no ALLOW edge lowers connectivity.
    edges = [("self", "a", "ALLOW")]
    m = compute_connectivity(edges, nodes=["self", "a", "lonely"])
    assert m.n_nodes == 3
    assert m.connectivity == pytest.approx(2 / 3)
    assert m.isolated_nodes == 1


def test_from_trusted_rows_matches_snapshot_shape():
    rows = [
        {"from": "self", "to": "a", "verdict": "ALLOW", "drift_score": 0.1},
        {"from": "self", "to": "b", "verdict": "REFUSE", "drift_score": 0.5},
    ]
    m = from_trusted_rows(rows, nodes=["self", "a", "b"])
    assert m.largest_component == 2
    assert m.isolated_nodes == 1
    d = m.to_dict()
    assert d["connectivity"] == pytest.approx(2 / 3)
    assert set(d) >= {"n_nodes", "connectivity", "hub_concentration", "mean_degree"}
