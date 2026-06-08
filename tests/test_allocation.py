"""Tests for ADR 0172 maximum-entropy (Boltzmann) allocation."""

from __future__ import annotations

import random

import pytest

from chimera.core.allocation import (
    allocate_budget,
    allocation_temperature,
    anneal_temperature,
    boltzmann_allocation_enabled,
    boltzmann_select,
    softmax,
)
from chimera.core.task_splitter import subtask_value


# ── flag / config parsing ───────────────────────────────────


def test_flag_off_by_default(monkeypatch):
    monkeypatch.delenv("CHIMERA_BOLTZMANN_ALLOC", raising=False)
    assert boltzmann_allocation_enabled() is False


@pytest.mark.parametrize("val", ["1", "true", "On", "yes"])
def test_flag_truthy(monkeypatch, val):
    monkeypatch.setenv("CHIMERA_BOLTZMANN_ALLOC", val)
    assert boltzmann_allocation_enabled() is True


def test_temperature_default_zero(monkeypatch):
    monkeypatch.delenv("CHIMERA_BOLTZMANN_TEMP", raising=False)
    assert allocation_temperature() == 0.0


def test_temperature_parsed(monkeypatch):
    monkeypatch.setenv("CHIMERA_BOLTZMANN_TEMP", "1.5")
    assert allocation_temperature() == pytest.approx(1.5)


def test_temperature_bad_value_falls_back(monkeypatch):
    monkeypatch.setenv("CHIMERA_BOLTZMANN_TEMP", "hot")
    assert allocation_temperature() == 0.0


# ── softmax ─────────────────────────────────────────────────


def test_softmax_empty_and_singleton():
    assert softmax([]) == []
    assert softmax([5.0]) == [1.0]


def test_softmax_sums_to_one():
    w = softmax([1.0, 2.0, 3.0], temperature=1.0)
    assert sum(w) == pytest.approx(1.0)


def test_softmax_monotonic_in_value():
    w = softmax([1.0, 2.0, 3.0], temperature=1.0)
    assert w[0] < w[1] < w[2]


def test_softmax_high_temperature_flatter():
    hot = softmax([0.0, 5.0], temperature=10.0)
    cold = softmax([0.0, 5.0], temperature=0.5)
    # Hot is closer to uniform (smaller gap between the two weights).
    assert abs(hot[0] - hot[1]) < abs(cold[0] - cold[1])


def test_softmax_zero_temperature_is_argmax():
    assert softmax([1.0, 9.0, 3.0], temperature=0.0) == [0.0, 1.0, 0.0]


def test_softmax_zero_temperature_splits_ties():
    assert softmax([5.0, 5.0], temperature=0.0) == [0.5, 0.5]


# ── anneal_temperature ──────────────────────────────────────


def test_anneal_starts_hot_and_cools():
    assert anneal_temperature(1.0, step=0) == pytest.approx(1.0)
    assert anneal_temperature(1.0, step=1, rate=0.5) == pytest.approx(0.5)
    assert anneal_temperature(1.0, step=2, rate=0.5) == pytest.approx(0.25)


def test_anneal_floor_respected():
    assert anneal_temperature(1.0, step=10, rate=0.5, floor=0.1) == pytest.approx(0.1)


# ── allocate_budget ─────────────────────────────────────────


def test_allocate_budget_sums_to_budget():
    alloc = allocate_budget([1.0, 2.0, 3.0], 10, temperature=1.0)
    assert sum(alloc) == 10
    assert len(alloc) == 3


def test_allocate_budget_zero_or_empty():
    assert allocate_budget([], 5) == []
    assert allocate_budget([1.0, 2.0], 0) == [0, 0]


def test_allocate_budget_cold_concentrates():
    # Near-zero temperature ⇒ essentially all budget on the best candidate.
    alloc = allocate_budget([1.0, 1.0, 9.0], 9, temperature=0.01)
    assert alloc[2] == 9
    assert alloc[0] == 0 and alloc[1] == 0


def test_allocate_budget_hot_spreads():
    alloc = allocate_budget([1.0, 1.0, 1.0], 9, temperature=5.0)
    # Equal values ⇒ even split.
    assert alloc == [3, 3, 3]


# ── boltzmann_select ────────────────────────────────────────


def test_select_k_ge_n_returns_all():
    items = ["a", "b"]
    assert boltzmann_select(items, [1.0, 2.0], 5) == ["a", "b"]


def test_select_deterministic_top_k_by_value():
    items = ["a", "b", "c", "d"]
    values = [0.1, 0.9, 0.2, 0.8]
    # Keep the two highest (b, d), preserving original order.
    assert boltzmann_select(items, values, 2) == ["b", "d"]


def test_select_preserves_original_order():
    items = ["x", "y", "z"]
    values = [0.5, 0.1, 0.9]
    # Highest are z and x; returned in original order x, z.
    assert boltzmann_select(items, values, 2) == ["x", "z"]


def test_select_ties_keep_earliest():
    items = ["a", "b", "c"]
    values = [1.0, 1.0, 1.0]
    assert boltzmann_select(items, values, 2) == ["a", "b"]


def test_select_stochastic_with_rng_returns_k_in_order():
    items = ["a", "b", "c", "d"]
    values = [1.0, 2.0, 3.0, 4.0]
    out = boltzmann_select(items, values, 2, temperature=1.0, rng=random.Random(0))
    assert len(out) == 2
    # Whatever is sampled, original order is preserved.
    assert out == [i for i in items if i in out]


# ── subtask_value proxy ─────────────────────────────────────


def test_subtask_value_rewards_artifact_path():
    with_path = subtask_value("Append the summary to mind/LESSONS.md")
    without = subtask_value("Think about the architecture")
    assert with_path > without


def test_subtask_value_empty_is_zero():
    assert subtask_value("") == 0.0
    assert subtask_value("   ") == 0.0


# ── split_task integration (flag-gated selection) ───────────


class _StubResponse:
    def __init__(self, text):
        self.text = text


class _StubProvider:
    def __init__(self, text):
        self._text = text

    async def complete_with_tools(self, *, messages, model_id, tools, max_tokens):
        return _StubResponse(self._text)


# Two artifact-naming (high-value) sub-tasks bracket two vague ones; the budget
# is 2, so value-aware selection must keep the artifact-naming pair.
_PAYLOAD = (
    '{"split": true, "subtasks": ['
    '"Think about the design",'
    '"Append findings to mind/NOTES.md",'
    '"Consider the tradeoffs",'
    '"Write the report to state/report.json"'
    ']}'
)


@pytest.mark.asyncio
async def test_split_flag_off_keeps_first_n(monkeypatch):
    from chimera.core.task_splitter import split_task

    monkeypatch.delenv("CHIMERA_BOLTZMANN_ALLOC", raising=False)
    subs = await split_task("task", provider=_StubProvider(_PAYLOAD), model_id="m", max_subtasks=2)
    # Byte-identical flat cap: the first two in model order.
    assert subs == ["Think about the design", "Append findings to mind/NOTES.md"]


@pytest.mark.asyncio
async def test_split_flag_on_keeps_highest_value(monkeypatch):
    from chimera.core.task_splitter import split_task

    monkeypatch.setenv("CHIMERA_BOLTZMANN_ALLOC", "1")
    subs = await split_task("task", provider=_StubProvider(_PAYLOAD), model_id="m", max_subtasks=2)
    # The two artifact-naming sub-tasks win, preserving original order.
    assert subs == [
        "Append findings to mind/NOTES.md",
        "Write the report to state/report.json",
    ]
