"""Gate calibration — sound per-gate false-negative-rate bounds (ADR 0186 B.4l).

Adopted KERNEL ONLY from arXiv:2606.20510 ("Efficient and Sound Probabilistic
Verification for AI Agents"): the one transferable idea is how it makes each
fallible detector's marginal SOUND — a one-sided Clopper-Pearson upper confidence
bound on its measured miss rate. We REJECT the paper's DRO/SDP-over-Datalog
superstructure (it needs a Datalog policy + a conic solver and its own §6 says the
bound goes vacuous on agent-generated code — exactly our regime; see codex q006).

The honest framing (q006): Chimera does not yet have the calibration data for a real
bound — so this module is the MEASUREMENT substrate, advisory-only, with hard
soundness guards baked in:

- ``UNCERTIFIED`` below an n-floor: a wide-or-absent bound must NEVER read as
  "verified" (Chimera's standing rule, cf. B.4j/B.4k).
- FNR denominator is KNOWN-POSITIVES (inputs where a violation was actually present),
  never total runs — dividing misses by all traffic estimates a different, smaller
  quantity.
- ``cell_counts`` STRUCTURALLY refuses to pool across (gate × model × repo_class)
  strata — pooling correlated, drifting strata is the unsound move, so it is made
  impossible rather than merely discouraged.
- One-sided upper bound only; never a point estimate.

Pure + dependency-free: only stdlib ``math`` (lgamma/exp/log). No scipy/numpy —
Chimera's deps stay anthropic/mcp/httpx/pydantic/pyyaml/kuzu. Ledger I/O and the
label producer are separate rungs (B.4l stages 2-3).
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, replace
from pathlib import Path

UNCERTIFIED = "uncertified"
PROMOTABLE = "promotable"        # stage 5: cell may be promoted to a hard gate
EXCEEDS = "exceeds_budget"       # stage 5: certified but FNR bound > the operator budget

# Ground-truth labels for a gate firing.
VIOLATION = "violation"   # a real violation WAS present on this input
CLEAN = "clean"           # confirmed no violation present
UNKNOWN = "unknown"       # not yet labelled (the default for a fresh firing)

# Gate verdicts.
PASS = "pass"
FAIL = "fail"

# Sentinel model id for deterministic (non-LLM) gates — they have no model, but the
# cell key must still be well-defined so they never silently share a cell with an
# LLM gate's outcomes.
DETERMINISTIC = "DETERMINISTIC"


# ── pure statistics: Clopper-Pearson upper bound (no scipy/numpy) ─────


def _betacf(a: float, b: float, x: float, itmax: int = 300, eps: float = 1e-14) -> float:
    """Continued fraction for the incomplete beta function (Lentz's method,
    Numerical Recipes ``betacf``)."""
    tiny = 1e-30
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    h = d
    for m in range(1, itmax + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        de = d * c
        h *= de
        if abs(de - 1.0) < eps:
            break
    return h


def regularized_incomplete_beta(a: float, b: float, x: float) -> float:
    """I_x(a, b) — the regularized incomplete beta function, in pure stdlib."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbeta = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    front = math.exp(lbeta + a * math.log(x) + b * math.log(1.0 - x))
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def _beta_quantile(a: float, b: float, p: float) -> float:
    """Inverse of I_x(a,b): the x with I_x(a,b)=p, via bisection (I_x is monotone
    increasing in x). 100 iterations → ~1e-30 precision, far past float resolution."""
    if p <= 0.0:
        return 0.0
    if p >= 1.0:
        return 1.0
    lo, hi = 0.0, 1.0
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        if regularized_incomplete_beta(a, b, mid) < p:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def clopper_pearson_upper(k: int, n: int, alpha: float = 0.05) -> float:
    """One-sided ``1-alpha`` Clopper-Pearson UPPER confidence bound on the true rate,
    given ``k`` observed events (misses) in ``n`` trials. Exact (conservative): the
    returned U is the rate at which P(X <= k | n, U) = alpha. Edge cases: n<=0 or
    k>=n → 1.0 (max uncertainty / all events observed). The upper limit equals the
    ``1-alpha`` quantile of Beta(k+1, n-k)."""
    if n <= 0 or k >= n:
        return 1.0
    if k < 0:
        k = 0
    return _beta_quantile(k + 1, n - k, 1.0 - alpha)


def fnr_upper(k: int, n: int, *, alpha: float = 0.05, n_floor: int = 30):
    """Sound upper bound on a gate's false-negative rate — or the ``UNCERTIFIED``
    sentinel when ``n`` (the count of KNOWN-POSITIVE inputs) is below ``n_floor``.
    Below the floor a bound is too wide to mean anything, and "no signal" must never
    be read as "verified" — so it is structurally distinct from a number."""
    if n < n_floor:
        return UNCERTIFIED
    return clopper_pearson_upper(k, n, alpha)


# ── gate outcomes + non-pooling stratification ───────────────────────


@dataclass(frozen=True)
class GateOutcome:
    """One gate firing, with (eventually) its ground-truth label. ``model_id`` is
    ``DETERMINISTIC`` for non-LLM gates. ``ground_truth`` starts ``UNKNOWN`` and is
    back-filled by the label producer (B.4l stage 2)."""
    gate: str
    run_id: str
    diff_sha: str
    model_id: str
    repo_class: str
    verdict: str           # PASS | FAIL
    ground_truth: str      # VIOLATION | CLEAN | UNKNOWN
    ts: str

    def cell(self) -> tuple[str, str, str]:
        """The stratification key — bounds are NEVER computed across cells."""
        return (self.gate, self.model_id, self.repo_class)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> GateOutcome:
        return cls(
            gate=d["gate"], run_id=d.get("run_id", ""), diff_sha=d.get("diff_sha", ""),
            model_id=d.get("model_id", DETERMINISTIC), repo_class=d.get("repo_class", ""),
            verdict=d.get("verdict", PASS), ground_truth=d.get("ground_truth", UNKNOWN),
            ts=d.get("ts", ""),
        )


def cell_counts(outcomes) -> tuple[int, int]:
    """(misses, known_positives) for a SINGLE cell. A miss = the gate PASSed while a
    VIOLATION was present (a false negative). The denominator is known-positives
    (ground_truth==VIOLATION), per the FNR definition — NOT total runs.

    Structurally refuses to pool: raises ``ValueError`` if ``outcomes`` span more than
    one (gate × model × repo_class) cell. Pooling correlated/drifting strata is the
    unsound move, so it is made impossible, not merely discouraged."""
    cells = {o.cell() for o in outcomes}
    if len(cells) > 1:
        raise ValueError(f"refusing to pool a gate bound across strata: {sorted(cells)}")
    positives = [o for o in outcomes if o.ground_truth == VIOLATION]
    misses = sum(1 for o in positives if o.verdict == PASS)
    return misses, len(positives)


def stratify(outcomes) -> dict:
    """Group outcomes by cell (gate × model × repo_class). Never merges across cells —
    the dict keys ARE the strata, so a per-cell bound can be computed without ever
    pooling."""
    out: dict = {}
    for o in outcomes:
        out.setdefault(o.cell(), []).append(o)
    return out


# ── ledger I/O (append-only JSONL, fold-latest — crawl_ledger pattern) ─


def gate_outcomes_path(state_dir: Path) -> Path:
    return Path(state_dir) / "gate-outcomes.jsonl"


def append_gate_outcome(path: Path, outcome: GateOutcome) -> Path:
    """Append one GateOutcome line. A ground_truth back-fill is just a re-append
    (fold-latest on read) — no in-place mutation, crash-safe."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(outcome.to_dict(), sort_keys=True) + "\n")
    return p


def load_gate_outcomes(path: Path) -> list[GateOutcome]:
    """Folded latest-per-(gate, run_id, diff_sha) outcomes, in first-seen order.
    Tolerant: blank / non-JSON / non-outcome lines are skipped."""
    p = Path(path)
    if not p.exists():
        return []
    latest: dict[tuple, dict] = {}
    order: list[tuple] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict) or "gate" not in obj:
            continue
        key = (obj.get("gate"), obj.get("run_id"), obj.get("diff_sha"))
        if key not in latest:
            order.append(key)
        latest[key] = obj
    return [GateOutcome.from_dict(latest[k]) for k in order]


def label_gate_outcomes(state_dir: Path) -> dict:
    """Back-fill ``GateOutcome.ground_truth`` from the crawl ledger's per-run
    disposition — the B.4l stage-2 link from a gate firing to its outcome.

    The join key is ``run_id`` (BOTH ledgers key on it; ``diff_sha`` only gives
    per-diff sample granularity within a run). A run whose landed work was
    REVERTED labels its still-UNKNOWN gate outcomes VIOLATION — so a gate that
    PASSed that change is then a counted miss (false negative); a MERGED run
    labels them CLEAN. ``pending``/``abandoned`` carry no signal and stay UNKNOWN.

    Append-only (a re-append wins on fold-latest read) and idempotent: an outcome
    already labelled, or whose run has no terminal disposition, is skipped.
    Returns ``{"violation": n, "clean": n, "outcomes": total}``.
    """
    from .crawl_ledger import read_outcomes  # lazy: one-directional, no cycle

    disposition = {o.run_id: o.disposition for o in read_outcomes(state_dir)}
    terminal = {"reverted": VIOLATION, "merged": CLEAN}
    path = gate_outcomes_path(state_dir)
    outcomes = load_gate_outcomes(path)
    counts = {"violation": 0, "clean": 0, "outcomes": len(outcomes)}
    for o in outcomes:
        if o.ground_truth != UNKNOWN:
            continue
        label = terminal.get(disposition.get(o.run_id, ""))
        if label is None:
            continue
        append_gate_outcome(path, replace(o, ground_truth=label))
        counts["violation" if label == VIOLATION else "clean"] += 1
    return counts


# ── advisory report (observability only — NEVER a gate decision) ─────


def _drift_field(d):
    """JSON-friendly drift summary for the report (sentinel string or a small dict)."""
    if d == INSUFFICIENT:
        return INSUFFICIENT
    return {"alerted": d.alerted, "e_value": round(d.e_value, 3), "n": d.n}


def build_report(state_dir: Path, *, alpha: float = 0.05, n_floor: int = 30,
                 drift_p0: float = 0.1, max_fnr: float = 0.05) -> dict:
    """Assemble the advisory calibration report: the CRAWL landed-work revert rate
    (the one real aggregate signal today) plus a per-(gate × model × repo_class) FNR
    upper bound — or ``UNCERTIFIED`` below the n-floor — an anytime-valid DRIFT status
    (stage 4), and a hard-gate PROMOTION eligibility per cell + a SOUND stack
    slip-through bound (stage 5; both ``UNCERTIFIED`` until cells certify). Every
    number names its target POPULATION (benchmark ≠ field; the revert signal is a
    noisy proxy). Advisory only: nothing here is a gate decision."""
    from .crawl_ledger import summarize_outcomes  # lazy: one-directional, no cycle

    state_dir = Path(state_dir)
    crawl = summarize_outcomes(state_dir)
    groups = sorted(stratify(load_gate_outcomes(gate_outcomes_path(state_dir))).items())
    # Multiplicity: with k cells each reported at α, P(some cell's true FNR exceeds its
    # bound) inflates toward 1 — so a dashboard read across cells must spend α/k each
    # (Bonferroni) for SIMULTANEOUS coverage. Applied by default so the bounds (and the
    # promotion decisions they drive) can't be cherry-picked across cells.
    eff_alpha = bonferroni_alpha(alpha, len(groups))
    cells = []
    for cell, group in groups:
        misses, positives = cell_counts(group)
        promo = promotion_decision(misses, positives, alpha=eff_alpha, max_fnr=max_fnr,
                                   n_floor=n_floor)
        cells.append({
            "cell": list(cell),
            "misses": misses,
            "positives": positives,
            "bound": promo.bound,
            "drift": _drift_field(drift_status(group, drift_p0, alpha=eff_alpha)),
            "promotion": promo.status,
            "population": "labelled known-positives in this stratum",
        })
    return {
        "crawl": {
            "merged": crawl.get("merged", 0),
            "reverted": crawl.get("reverted", 0),
            "revert_rate": crawl.get("revert_rate"),
            "population": "merged CRAWL runs; revert-labelled (noisy proxy — under-counts misses)",
        },
        "cells": cells,
        "alpha": alpha,
        "effective_alpha": eff_alpha,   # Bonferroni-corrected (α / n_cells) — simultaneous
        "n_cells": len(groups),
        "n_floor": n_floor,
        "drift_p0": drift_p0,
        "max_fnr": max_fnr,
        # SOUND stack composition: P(violation slips ALL gates) ≤ min per-gate FNR.
        "stack_slip_bound": stack_slip_bound([c["bound"] for c in cells]),
    }


def render_report(report: dict) -> str:
    """Human-readable advisory report. Always shows n alongside every number and the
    UNCERTIFIED sentinel below the floor — no signal must never read as verified."""
    c = report["crawl"]
    rr = c["revert_rate"]
    lines = [
        "Gate calibration — ADVISORY (observability only; not a gate decision; ADR 0186 B.4l)",
        "",
        "CRAWL landed-work revert rate: "
        + (f"{rr:.1%}" if rr is not None else "n/a")
        + f"  (reverted {c['reverted']}/{c['merged']} merged)",
        f"  population: {c['population']}",
        "",
    ]
    if not report["cells"]:
        lines.append(
            f"Per-gate FNR bounds: no labelled gate outcomes yet → UNCERTIFIED "
            f"(n-floor {report['n_floor']}). The substrate is in place; the data is not."
        )
    else:
        eff = report.get("effective_alpha", report["alpha"])
        bonf = ("" if eff == report["alpha"]
                else f"; Bonferroni α/{report.get('n_cells', 1)}={eff:g} for simultaneous coverage")
        lines.append(
            f"Per-gate FNR upper bounds (one-sided, 1-α={1 - report['alpha']:.2f}{bonf}; "
            f"UNCERTIFIED below n={report['n_floor']} known-positives):"
        )
        for cell in report["cells"]:
            gate, model, repo_class = cell["cell"]
            b = cell["bound"]
            shown = "UNCERTIFIED" if b == UNCERTIFIED else f"FNR ≤ {b:.1%}"
            d = cell.get("drift")
            if d == INSUFFICIENT or d is None:
                drift = "drift: —"
            elif d["alerted"]:
                drift = f"drift: ⚠ DEGRADED (e={d['e_value']})"
            else:
                drift = f"drift: ok (e={d['e_value']})"
            promo = {PROMOTABLE: "promote: ✓", EXCEEDS: "promote: ✗(>budget)"}.get(
                cell.get("promotion"), "promote: —")
            lines.append(
                f"  {gate} [{model}/{repo_class}]  {shown}  "
                f"(misses {cell['misses']}/{cell['positives']})  {drift}  {promo}"
            )
        if report.get("drift_p0") is not None:
            lines.append(
                f"\ndrift = anytime-valid e-process vs baseline miss rate "
                f"p0={report['drift_p0']:g} (⚠ at e≥{1 / report['alpha']:g}); "
                f"'—' = insufficient stream."
            )
        ssb = report.get("stack_slip_bound")
        mf = report.get("max_fnr")
        if mf is not None:
            shown_ssb = "UNCERTIFIED" if ssb == UNCERTIFIED or ssb is None else f"≤ {ssb:.1%}"
            lines.append(
                f"promote ✓ = FNR provably ≤ budget {mf:g} (operator α/δ decision, never "
                f"auto-applied). Stack slip-through (min per-gate FNR, no independence "
                f"assumed): {shown_ssb}. Advisory."
            )
    return "\n".join(lines) + "\n"


# ── stage 4: anytime-valid drift monitor (ADR 0186 B.4l) ─────────────
#
# Has a gate's miss rate DEGRADED past an acceptable baseline p0? A fixed-n
# Clopper-Pearson bound (stages 1-3) is voided by continuous re-checking (optional
# stopping) and by drift; an e-process is the prior-art family that survives both —
# its false-ALARM rate is controlled at ANY stopping time (Ville's inequality), with
# no i.i.d. assumption. Honest caveat (codex q006): this controls false alarms on the
# (proxy-labelled) miss signal; it does not de-bias the underlying rate estimate.
# Inert until the calibration ledger accrues a per-cell stream — reports INSUFFICIENT.

INSUFFICIENT = "insufficient"   # too few known-positives to monitor drift


@dataclass(frozen=True)
class DriftResult:
    """Outcome of the drift e-process. ``alerted`` iff the running e-value ever crossed
    ``threshold`` (=1/alpha) — by Ville that happens with probability ≤ alpha while the
    true miss rate stays ≤ ``p0``, so an alert is α-valid evidence of degradation."""
    alerted: bool
    e_value: float      # final E_n
    peak: float         # max E_n over the run (the anytime statistic)
    n: int
    threshold: float


def drift_eprocess(observations, p0: float, *, lam: float = 1.0,
                   alpha: float = 0.05) -> DriftResult:
    """Anytime-valid test that a gate's true miss rate exceeds ``p0``, via the betting
    test-martingale ``E_n = ∏ (1 + λ(x_i - p0))`` over a 0/1 miss sequence (1 = the gate
    PASSED a known violation = a miss). Under H0 (rate ≤ p0) E_n is a non-negative
    SUPERmartingale with E[E_n] ≤ 1 (= 1 exactly at rate p0; < 1 when better), so
    P(sup_n E_n ≥ 1/alpha) ≤ alpha (Ville) — valid under peeking AND non-i.i.d. ``lam``
    is clamped to ``[0, 1/p0]`` to keep every factor non-negative; soundness holds for
    any λ in range (λ only tunes power). NB: this controls the false-ALARM rate of the
    test, not bias in the underlying (proxy-labelled) miss-rate estimate."""
    if not 0.0 < p0 < 1.0:
        raise ValueError("p0 (baseline miss rate) must be in (0, 1)")
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be in (0, 1)")
    lam = max(0.0, min(lam, 1.0 / p0))
    threshold = 1.0 / alpha
    e = 1.0
    peak = 1.0
    n = 0
    for x in observations:
        e *= 1.0 + lam * ((1.0 if x else 0.0) - p0)
        peak = max(peak, e)
        n += 1
    return DriftResult(alerted=peak >= threshold, e_value=e, peak=peak, n=n,
                       threshold=threshold)


def drift_status(outcomes, p0: float = 0.1, *, lam: float = 1.0,
                 alpha: float = 0.05, min_n: int = 10):
    """Drift status for one cell: order its KNOWN-POSITIVE outcomes by ts, form the
    miss sequence (1 = gate PASSED a violation, 0 = caught), and run the e-process.
    Returns a :class:`DriftResult`, or the ``INSUFFICIENT`` sentinel when fewer than
    ``min_n`` known-positives exist (the monitor needs a stream)."""
    positives = sorted((o for o in outcomes if o.ground_truth == VIOLATION),
                       key=lambda o: o.ts)
    if len(positives) < min_n:
        return INSUFFICIENT
    seq = [1 if o.verdict == PASS else 0 for o in positives]
    return drift_eprocess(seq, p0, lam=lam, alpha=alpha)


# ── stage 5: hard-bound promotion + sound stack composition (B.4l) ───
#
# Conditional and operator-driven: a gate is only ever promoted from advisory to a
# HARD (blocking) gate by an operator who commits an FNR budget (max_fnr) AND has the
# data to certify it. This module SURFACES eligibility; it never auto-promotes.


@dataclass(frozen=True)
class PromotionResult:
    """Whether a cell may be promoted to a hard gate. ``status`` ∈ {PROMOTABLE,
    EXCEEDS, UNCERTIFIED}; ``bound`` is the CP FNR upper bound (or UNCERTIFIED)."""
    status: str
    bound: float | str
    max_fnr: float
    n: int


def promotion_decision(misses: int, n: int, *, alpha: float = 0.05,
                       max_fnr: float = 0.05, n_floor: int = 30) -> PromotionResult:
    """May this gate cell be PROMOTED from advisory to a HARD (blocking) gate? Only if
    its false-negative rate is provably ≤ ``max_fnr`` (the operator's committed budget)
    at 1-alpha confidence. ``n < n_floor`` → UNCERTIFIED (never auto-promote on thin
    data). Else the CP upper bound U: U ≤ max_fnr → PROMOTABLE; U > max_fnr → EXCEEDS
    (too leaky, or data too sparse to certify below budget). NEVER auto-applied — this
    is surfaced for an explicit operator α/δ decision (the critic `false_approve==0`
    floor, generalized)."""
    b = fnr_upper(misses, n, alpha=alpha, n_floor=n_floor)
    if b == UNCERTIFIED:
        return PromotionResult(UNCERTIFIED, UNCERTIFIED, max_fnr, n)
    return PromotionResult(PROMOTABLE if b <= max_fnr else EXCEEDS, b, max_fnr, n)


def stack_slip_bound(bounds):
    """SOUND upper bound on P(a violation slips the WHOLE stack undetected) — i.e.
    EVERY gate misses it. Since all-miss ⊆ {gate_i misses} for each i, P(all miss) ≤
    min_i FNR_i for ANY joint distribution — no independence assumed. This is the
    assumption-free composition:

    * NOT the product (∏ FNR_i assumes INDEPENDENCE — unsound under correlated misses,
      which Chimera has: one confusing diff fools several gates at once), and
    * NOT the sum (Σ bounds P(SOME gate misses) — a different event).

    ``bounds`` is per-gate FNR upper bounds; UNCERTIFIED entries are ignored.
    UNCERTIFIED if none are certified."""
    numeric = [b for b in bounds if b != UNCERTIFIED]
    return min(numeric) if numeric else UNCERTIFIED


def bonferroni_alpha(alpha: float, k: int) -> float:
    """The per-cell α for SIMULTANEOUS 1-alpha coverage across ``k`` reported cells
    (Bonferroni): with ``k`` cells each at α, P(some cell's true FNR exceeds its bound)
    can approach 1 — so a dashboard read across many cells must spend α/k per cell. No
    independence assumed (union bound). ``k <= 1`` → alpha unchanged."""
    if k <= 1:
        return alpha
    return alpha / k
