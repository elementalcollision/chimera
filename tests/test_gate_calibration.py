"""Gate calibration — sound CP false-negative bounds (ADR 0186 B.4l)."""

from __future__ import annotations

import math

import pytest

from chimera.core.gate_calibration import (
    CLEAN,
    EXCEEDS,
    FAIL,
    INSUFFICIENT,
    PASS,
    PROMOTABLE,
    UNCERTIFIED,
    UNKNOWN,
    VIOLATION,
    DriftResult,
    GateOutcome,
    append_gate_outcome,
    bonferroni_alpha,
    cell_counts,
    clopper_pearson_upper,
    drift_eprocess,
    drift_status,
    fnr_upper,
    gate_outcomes_path,
    label_gate_outcomes,
    load_gate_outcomes,
    promotion_decision,
    regularized_incomplete_beta,
    stack_slip_bound,
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


# ── advisory report (observability only) ────────────────────────────


def _seed_cell(tmp_path, n, *, gate="critic", model="opus", repo="self",
               verdict=FAIL, gt=VIOLATION):
    from chimera.core.gate_calibration import append_gate_outcome, gate_outcomes_path
    p = gate_outcomes_path(tmp_path)
    for i in range(n):
        append_gate_outcome(p, GateOutcome(gate=gate, run_id=f"r{i}", diff_sha=f"d{i}",
                                           model_id=model, repo_class=repo,
                                           verdict=verdict, ground_truth=gt, ts="t"))


def test_build_report_empty_state():
    from chimera.core.gate_calibration import build_report
    rep = build_report("/no/such/state")
    assert rep["crawl"]["merged"] == 0 and rep["crawl"]["revert_rate"] is None
    assert rep["cells"] == []


def test_render_report_advisory_and_uncertified_when_empty():
    from chimera.core.gate_calibration import build_report, render_report
    out = render_report(build_report("/no/such/state"))
    assert "ADVISORY" in out and "not a gate decision" in out
    assert "UNCERTIFIED" in out and "revert rate" in out


def test_build_report_with_labelled_cell(tmp_path):
    from chimera.core.gate_calibration import build_report
    _seed_cell(tmp_path, 30)  # 0 misses (all caught) over 30 known-positives
    rep = build_report(tmp_path, n_floor=30)
    cell = next(c for c in rep["cells"] if c["cell"] == ["critic", "opus", "self"])
    assert cell["positives"] == 30 and cell["misses"] == 0
    assert cell["bound"] != UNCERTIFIED and cell["bound"] < 0.12   # 0/30 → ~0.095


def test_render_report_shows_bound_when_certified(tmp_path):
    from chimera.core.gate_calibration import build_report, render_report
    _seed_cell(tmp_path, 30)
    out = render_report(build_report(tmp_path, n_floor=30))
    assert "FNR ≤" in out and "critic [opus/self]" in out


def test_build_report_uncertified_below_floor(tmp_path):
    from chimera.core.gate_calibration import build_report
    _seed_cell(tmp_path, 12)  # below the default floor
    rep = build_report(tmp_path)  # n_floor=30
    cell = next(c for c in rep["cells"] if c["cell"] == ["critic", "opus", "self"])
    assert cell["positives"] == 12 and cell["bound"] == UNCERTIFIED


# ── stage 4: anytime-valid drift e-process ──────────────────────────


def test_drift_eprocess_empty_and_clean_never_alert():
    assert drift_eprocess([], 0.1).n == 0
    assert drift_eprocess([], 0.1).alerted is False
    clean = drift_eprocess([0] * 200, 0.1)   # rate 0 ≪ p0 → e shrinks
    assert clean.alerted is False and clean.peak <= 1.0


def test_drift_eprocess_alerts_on_sustained_degradation():
    r = drift_eprocess([1] * 20, 0.1)        # rate 1.0 ≫ p0 → e explodes
    assert r.alerted is True and r.peak >= r.threshold


def test_drift_eprocess_no_false_alarm_at_null_rate():
    # A long sequence at exactly the baseline rate p0 must (almost) never alert — the
    # martingale stays bounded (this is the Ville guarantee in action).
    p0 = 0.2
    seq = ([1] + [0] * 4) * 60   # rate exactly 0.2 over 300 obs
    assert drift_eprocess(seq, p0).alerted is False


def test_drift_eprocess_deterministic_and_validates_params():
    seq = [1, 0, 1, 1, 0]
    assert drift_eprocess(seq, 0.1).e_value == drift_eprocess(seq, 0.1).e_value
    with pytest.raises(ValueError, match="p0"):
        drift_eprocess([1], 0.0)
    with pytest.raises(ValueError, match="alpha"):
        drift_eprocess([1], 0.1, alpha=1.0)


def test_drift_eprocess_lambda_clamped_keeps_factors_nonnegative():
    # An over-large lam is clamped to 1/p0 so e never goes negative on a clean obs.
    r = drift_eprocess([0] * 5, 0.25, lam=1000.0)
    assert r.e_value >= 0.0 and isinstance(r, DriftResult)


def _pos(verdict, ts):
    return GateOutcome(gate="g", run_id=f"r{ts}", diff_sha=f"d{ts}", model_id="m",
                       repo_class="self", verdict=verdict, ground_truth=VIOLATION, ts=ts)


def test_drift_status_insufficient_then_alerts():
    assert drift_status([_pos(PASS, f"t{i}") for i in range(5)], 0.1, min_n=10) == INSUFFICIENT
    # 15 known-positives all MISSED (gate PASSED a violation) → degraded → alert.
    missed = [_pos(PASS, f"t{i:02d}") for i in range(15)]
    r = drift_status(missed, 0.1, min_n=10)
    assert r != INSUFFICIENT and r.alerted is True


def test_drift_status_orders_by_ts_and_ignores_non_positives():
    # CLEAN/UNKNOWN outcomes are not part of the known-positive stream.
    outs = [_pos(FAIL, f"t{i:02d}") for i in range(12)]
    outs.append(GateOutcome(gate="g", run_id="x", diff_sha="x", model_id="m",
                            repo_class="self", verdict=PASS, ground_truth=CLEAN, ts="t99"))
    r = drift_status(outs, 0.1, min_n=10)
    assert r != INSUFFICIENT and r.n == 12 and r.alerted is False  # all caught → no drift


def test_report_includes_drift_field(tmp_path):
    from chimera.core.gate_calibration import build_report, render_report
    _seed_cell(tmp_path, 12)  # 12 known-positives, all caught (verdict=FAIL by default)
    rep = build_report(tmp_path, drift_p0=0.1)
    cell = next(c for c in rep["cells"] if c["cell"] == ["critic", "opus", "self"])
    assert cell["drift"] != INSUFFICIENT and cell["drift"]["alerted"] is False
    assert "drift:" in render_report(rep)


# ── stage 5: hard-bound promotion + sound composition ───────────────


def test_promotion_decision_states():
    # 0/300 → CP ~0.0099 ≤ budget 0.05 → PROMOTABLE.
    assert promotion_decision(0, 300, max_fnr=0.05).status == PROMOTABLE
    # 0/30 → CP ~0.095 > 0.05 → certified but EXCEEDS the budget.
    assert promotion_decision(0, 30, max_fnr=0.05).status == EXCEEDS
    # 0/30 with a looser 0.10 budget → PROMOTABLE.
    assert promotion_decision(0, 30, max_fnr=0.10).status == PROMOTABLE
    # below the n-floor → never auto-promote.
    r = promotion_decision(0, 12, n_floor=30)
    assert r.status == UNCERTIFIED and r.bound == UNCERTIFIED


def test_stack_slip_bound_is_min_not_product_or_sum():
    # SOUND bound on 'violation slips ALL gates' = min per-gate FNR (no independence).
    assert stack_slip_bound([0.01, 0.2, UNCERTIFIED]) == 0.01
    assert stack_slip_bound([UNCERTIFIED, UNCERTIFIED]) == UNCERTIFIED
    assert stack_slip_bound([]) == UNCERTIFIED
    # explicitly NOT the product (0.01*0.2=0.002) nor the sum (0.21).
    assert stack_slip_bound([0.01, 0.2]) == 0.01


def test_bonferroni_alpha():
    assert bonferroni_alpha(0.05, 4) == 0.0125
    assert bonferroni_alpha(0.05, 1) == 0.05
    assert bonferroni_alpha(0.05, 0) == 0.05


def test_report_promotion_and_stack_slip(tmp_path):
    from chimera.core.gate_calibration import build_report, render_report
    _seed_cell(tmp_path, 300)  # 0 misses / 300 positives → CP ~0.0099 → promotable
    rep = build_report(tmp_path, max_fnr=0.05)
    cell = next(c for c in rep["cells"] if c["cell"] == ["critic", "opus", "self"])
    assert cell["promotion"] == PROMOTABLE
    assert rep["stack_slip_bound"] != UNCERTIFIED and rep["stack_slip_bound"] < 0.02
    assert "promote: ✓" in render_report(rep)


def test_report_promotion_uncertified_below_floor(tmp_path):
    from chimera.core.gate_calibration import build_report
    _seed_cell(tmp_path, 12)  # below floor
    rep = build_report(tmp_path)
    cell = next(c for c in rep["cells"] if c["cell"] == ["critic", "opus", "self"])
    assert cell["promotion"] == UNCERTIFIED and rep["stack_slip_bound"] == UNCERTIFIED


def test_report_bonferroni_corrects_alpha_across_cells(tmp_path):
    from chimera.core.gate_calibration import build_report, render_report
    # Two distinct cells (different gate → distinct fold key) → α spent α/2 each for
    # simultaneous coverage, so a dashboard read can't cherry-pick the tightest.
    _seed_cell(tmp_path, 50, gate="critic")
    _seed_cell(tmp_path, 50, gate="witness")
    rep = build_report(tmp_path, alpha=0.05)
    assert rep["n_cells"] == 2 and rep["effective_alpha"] == 0.025
    assert "Bonferroni" in render_report(rep)


# ── label producer: run_id ↔ crawl disposition → ground_truth (B.4l stage 2) ─


def _seed_gate(state_dir, run_id, *, gate="shadow_arbiter", verdict=PASS):
    append_gate_outcome(
        gate_outcomes_path(state_dir),
        GateOutcome(gate=gate, run_id=run_id, diff_sha="d1", model_id="fugu-ultra",
                    repo_class="self", verdict=verdict, ground_truth=UNKNOWN, ts="t"),
    )


def test_label_gate_outcomes_links_via_run_id(tmp_path):
    from chimera.core.crawl_ledger import (
        CrawlOutcome,
        record_outcome,
        set_disposition,
    )

    for rid in ("run-merged", "run-reverted", "run-pending"):
        record_outcome(tmp_path, CrawlOutcome(run_id=rid, ts="t", slug="s", gate="pass"))
    set_disposition(tmp_path, "run-merged", "merged")
    set_disposition(tmp_path, "run-reverted", "reverted")
    for rid in ("run-merged", "run-reverted", "run-pending"):
        _seed_gate(tmp_path, rid)

    res = label_gate_outcomes(tmp_path)
    assert res == {"violation": 1, "clean": 1, "outcomes": 3}
    by_run = {o.run_id: o for o in load_gate_outcomes(gate_outcomes_path(tmp_path))}
    assert by_run["run-merged"].ground_truth == CLEAN
    assert by_run["run-reverted"].ground_truth == VIOLATION
    assert by_run["run-pending"].ground_truth == UNKNOWN  # no terminal disposition


def test_label_gate_outcomes_is_idempotent(tmp_path):
    from chimera.core.crawl_ledger import (
        CrawlOutcome,
        record_outcome,
        set_disposition,
    )

    record_outcome(tmp_path, CrawlOutcome(run_id="r", ts="t", slug="s", gate="pass"))
    set_disposition(tmp_path, "r", "reverted")
    _seed_gate(tmp_path, "r")
    assert label_gate_outcomes(tmp_path)["violation"] == 1
    # second pass: already labelled → nothing new
    second = label_gate_outcomes(tmp_path)
    assert second["violation"] == 0 and second["clean"] == 0


def test_label_gate_outcomes_skips_run_absent_from_crawl(tmp_path):
    # A gate outcome whose run_id is not in the crawl ledger stays UNKNOWN.
    _seed_gate(tmp_path, "orphan-run")
    res = label_gate_outcomes(tmp_path)
    assert res["violation"] == 0 and res["clean"] == 0
    outs = load_gate_outcomes(gate_outcomes_path(tmp_path))
    assert outs[0].ground_truth == UNKNOWN


def test_labelled_outcomes_feed_cell_counts(tmp_path):
    # The end-to-end point: once labelled, a PASS over a reverted (VIOLATION) run is
    # a counted miss in the FNR denominator.
    from chimera.core.crawl_ledger import (
        CrawlOutcome,
        record_outcome,
        set_disposition,
    )

    record_outcome(tmp_path, CrawlOutcome(run_id="bad", ts="t", slug="s", gate="pass"))
    set_disposition(tmp_path, "bad", "reverted")
    _seed_gate(tmp_path, "bad", verdict=PASS)  # arbiter PASSed a change that reverted
    label_gate_outcomes(tmp_path)
    outs = load_gate_outcomes(gate_outcomes_path(tmp_path))
    misses, positives = cell_counts(outs)
    assert positives == 1 and misses == 1  # a PASS over a VIOLATION == a miss
