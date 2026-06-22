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

import math
from dataclasses import asdict, dataclass

UNCERTIFIED = "uncertified"

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
