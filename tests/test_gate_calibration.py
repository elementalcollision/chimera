"""Gate calibration — sound CP false-negative bounds (ADR 0186 B.4l)."""

from __future__ import annotations

import math

import pytest

from chimera.core.gate_calibration import (
    CLEAN,
    FAIL,
    PASS,
    UNCERTIFIED,
    UNKNOWN,
    VIOLATION,
    GateOutcome,
    cell_counts,
    clopper_pearson_upper,
    fnr_upper,
    regularized_incomplete_beta,
    stratify,
)


def _binom_cdf(k: int, n: int, p: float) -> float:
    """Independent P(X<=k) for X~Binomial(n,p) — verifies the CP defining property
    without going through the beta code path."""
    return sum(math.comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(k + 1))


# ── Clopper-Pearson: independent defining-property check ─────────────


def test_cp_satisfies_binomial_defining_property():
    # The CP upper U for (k,n,alpha) is exactly the p where P(X<=k | n,p) == alpha.
    for k, n in [(0, 30), (1, 30), (3, 50), (0, 300), (5, 100), (12, 40)]:
        u = clopper_pearson_upper(k, n, 0.05)
        assert abs(_binom_cdf(k, n, u) - 0.05) < 1e-6, (k, n, u)


def test_cp_closed_form_k0():
    # k=0 closed form: U = 1 - alpha**(1/n).
    for n in (12, 30, 300):
        assert abs(clopper_pearson_upper(0, n, 0.05) - (1 - 0.05 ** (1 / n))) < 1e-9


def test_cp_known_values():
    assert abs(clopper_pearson_upper(0, 30) - 0.0951) < 1e-3
    assert abs(clopper_pearson_upper(0, 300) - 0.00994) < 1e-3
    assert abs(clopper_pearson_upper(0, 12) - 0.2209) < 1e-3  # the critic-gate n=12 case


def test_cp_monotonic_in_k_and_n():
    assert clopper_pearson_upper(1, 30) > clopper_pearson_upper(0, 30)   # more misses → looser
    assert clopper_pearson_upper(0, 300) < clopper_pearson_upper(0, 30)  # more trials → tighter


def test_cp_edge_cases():
    assert clopper_pearson_upper(0, 0) == 1.0
    assert clopper_pearson_upper(5, 5) == 1.0     # all trials were misses
    assert clopper_pearson_upper(7, 3) == 1.0     # k>n guard → max uncertainty


def test_regularized_incomplete_beta_endpoints():
    assert regularized_incomplete_beta(2, 3, 0.0) == 0.0
    assert regularized_incomplete_beta(2, 3, 1.0) == 1.0
    # I_x(1,n) = 1-(1-x)^n (closed form for a=1).
    assert abs(regularized_incomplete_beta(1, 30, 0.0951) - (1 - (1 - 0.0951) ** 30)) < 1e-9


# ── fnr_upper sentinel (no signal must never read as verified) ───────


def test_fnr_upper_uncertified_below_floor():
    assert fnr_upper(0, 12) == UNCERTIFIED          # below default floor 30
    assert fnr_upper(0, 29) == UNCERTIFIED
    v = fnr_upper(0, 30)
    assert v != UNCERTIFIED and abs(v - 0.0951) < 1e-3


def test_fnr_upper_custom_floor():
    assert fnr_upper(0, 12, n_floor=10) != UNCERTIFIED
    assert fnr_upper(0, 12, n_floor=100) == UNCERTIFIED


# ── GateOutcome + non-pooling stratification ────────────────────────


def _o(gate="g", model="m", repo="self", verdict=PASS, gt=UNKNOWN):
    return GateOutcome(gate=gate, run_id="r", diff_sha="d", model_id=model,
                       repo_class=repo, verdict=verdict, ground_truth=gt, ts="t")


def test_gate_outcome_roundtrip_and_cell():
    o = _o(gt=VIOLATION)
    assert GateOutcome.from_dict(o.to_dict()) == o
    assert o.cell() == ("g", "m", "self")


def test_cell_counts_misses_over_known_positives():
    outs = [
        _o(verdict=PASS, gt=VIOLATION),   # miss: gate passed a real violation
        _o(verdict=FAIL, gt=VIOLATION),   # caught (not a miss) — still a positive
        _o(verdict=PASS, gt=CLEAN),       # true negative — NOT a positive
        _o(verdict=PASS, gt=UNKNOWN),     # unlabelled — excluded
    ]
    misses, positives = cell_counts(outs)
    assert misses == 1 and positives == 2   # denominator = known positives only


def test_cell_counts_refuses_to_pool():
    mixed = [_o(model="a", gt=VIOLATION), _o(model="b", gt=VIOLATION)]
    with pytest.raises(ValueError, match="refusing to pool"):
        cell_counts(mixed)


def test_stratify_groups_by_cell_without_merging():
    outs = [_o(model="a"), _o(model="a"), _o(model="b"), _o(repo="foreign")]
    cells = stratify(outs)
    assert len(cells) == 3
    assert len(cells[("g", "a", "self")]) == 2
    # every stratify() group is single-cell → cell_counts never raises on its output.
    for group in cells.values():
        cell_counts(group)


# ── ledger I/O (append-only JSONL, fold-latest) ─────────────────────


def test_gate_outcomes_ledger_roundtrip_and_fold(tmp_path):
    from dataclasses import replace

    from chimera.core.gate_calibration import (
        append_gate_outcome,
        gate_outcomes_path,
        load_gate_outcomes,
    )
    p = gate_outcomes_path(tmp_path)
    o = _o(gt=UNKNOWN)
    append_gate_outcome(p, o)
    # A ground-truth back-fill is a re-append of the same (gate, run_id, diff_sha) key.
    append_gate_outcome(p, replace(o, ground_truth=VIOLATION))
    loaded = load_gate_outcomes(p)
    assert len(loaded) == 1 and loaded[0].ground_truth == VIOLATION  # fold-latest wins


def test_load_gate_outcomes_absent_and_tolerant(tmp_path):
    from chimera.core.gate_calibration import (
        append_gate_outcome,
        load_gate_outcomes,
    )
    assert load_gate_outcomes(tmp_path / "none.jsonl") == []
    p = tmp_path / "g.jsonl"
    p.write_text('not json\n{"no_gate_field": 1}\n')  # both lines skipped
    append_gate_outcome(p, _o(gt=CLEAN))
    assert len(load_gate_outcomes(p)) == 1
