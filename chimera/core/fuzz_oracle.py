"""Seeded-fuzz correctness oracle (ADR 0186 B.4k, adopted from arXiv:2606.20128).

The paper ("The Correctness Illusion in LLM GPU Kernels"): a fixed-input test
certifies buggy code because it checks one point in the input space. The fix is
seeded property/fuzz testing — many randomized inputs, each checked against an
oracle. The CRUX is the oracle-source problem: fuzzing inputs is trivial; what you
compare the output AGAINST is the hard part. This module gives the two oracle
sources that fit Chimera's task distribution (see codex q005):

- ``fuzz_check`` — PROPERTY/metamorphic: an invariant is the oracle (range,
  round-trip, idempotence, ordering, conservation). The lead mode — Chimera mostly
  writes small pure helpers, the textbook property-fuzz target.
- ``differential_check`` — DIFFERENTIAL: the pre-change code is the reference, for
  behaviour-preserving tasks (refactor/optimize/migrate). A secondary mode.

Two correctness properties of the harness itself:

1. SEEDED + reproducible. Every run takes a ``seed``; the first counterexample is
   returned WITH the seed, so a failure reproduces exactly. An un-seeded fuzz
   failure is a non-reproducible accusation (the same failure mode q004 found one
   layer up, where a single un-repeated guardrail sample lied).
2. NO silent N/A. Both functions REQUIRE an oracle (a ``property_fn`` / a
   ``baseline_fn``). "No oracle available" is the caller's decision and must be
   recorded distinctly at the gate layer — never as a pass — or the gate
   manufactures the very false confidence it exists to remove.

Pure + injectable: ``fn`` / ``gen`` / ``property_fn`` / ``baseline_fn`` are passed
in, so the harness is fully unit-testable without Hypothesis or a live agent.
"""

from __future__ import annotations

from dataclasses import dataclass
from random import Random
from typing import Any, Callable


@dataclass(frozen=True)
class FuzzResult:
    """Outcome of a fuzz run. ``ok`` is True iff every trial held. On failure,
    ``counterexample`` is the first input that broke (re-runnable via ``seed``) and
    ``detail`` explains how (property False / candidate raised / divergence)."""
    ok: bool
    trials: int                 # inputs actually run (== where it stopped on failure)
    passed: int                 # trials that held before the first counterexample
    seed: int
    counterexample: Any = None
    detail: str | None = None


def fuzz_check(
    fn: Callable[[Any], Any],
    gen: Callable[[Random], Any],
    property_fn: Callable[[Any, Any], bool],
    *,
    trials: int = 100,
    seed: int = 0,
) -> FuzzResult:
    """Run ``fn`` on ``trials`` seeded inputs from ``gen(rng)`` and assert that
    ``property_fn(inp, out)`` holds for each. Fail-fast: returns the FIRST
    counterexample (a minimal reproducer beats a count for a correctness gate).
    ``fn`` or ``property_fn`` raising on an input is itself a counterexample — the
    candidate crashed, or the invariant could not be established. Deterministic
    given ``seed`` (a generator error propagates: that is a setup bug, not a
    finding)."""
    rng = Random(seed)
    n = max(1, trials)
    passed = 0
    for i in range(n):
        inp = gen(rng)  # generator faults propagate — a broken generator is a bug
        try:
            out = fn(inp)
            held = bool(property_fn(inp, out))
            detail = None if held else "property returned False"
        except Exception as exc:
            held = False
            detail = f"{type(exc).__name__}: {exc}"[:200]
        if held:
            passed += 1
        else:
            return FuzzResult(ok=False, trials=i + 1, passed=passed, seed=seed,
                              counterexample=inp, detail=detail)
    return FuzzResult(ok=True, trials=n, passed=passed, seed=seed)


@dataclass
class _Call:
    ok: bool
    value: Any = None
    exc: BaseException | None = None


def _safe_call(fn: Callable[[Any], Any], inp: Any) -> _Call:
    try:
        return _Call(True, fn(inp))
    except Exception as exc:
        return _Call(False, exc=exc)


def _diff_detail(b: _Call, c: _Call) -> str:
    bs = repr(b.value)[:120] if b.ok else f"raised {type(b.exc).__name__}"
    cs = repr(c.value)[:120] if c.ok else f"raised {type(c.exc).__name__}"
    return f"baseline={bs} vs candidate={cs}"


def differential_check(
    baseline_fn: Callable[[Any], Any],
    candidate_fn: Callable[[Any], Any],
    gen: Callable[[Random], Any],
    *,
    trials: int = 100,
    seed: int = 0,
    equal: Callable[[Any, Any], bool] | None = None,
) -> FuzzResult:
    """Behaviour-preservation oracle: assert ``candidate_fn(x)`` matches
    ``baseline_fn(x)`` (the pre-change code is the reference) over seeded fuzzed
    inputs. Symmetric: both must return-equal, OR both must raise the same exception
    type — a refactor that changes WHICH exception is raised is a behaviour change.
    ``equal`` customises value comparison (default ``==``; e.g. ``math.isclose`` for
    floats). Returns the first divergence with the seed. Deterministic given
    ``seed``."""
    eq = equal or (lambda a, b: a == b)
    rng = Random(seed)
    n = max(1, trials)
    passed = 0
    for i in range(n):
        inp = gen(rng)
        b = _safe_call(baseline_fn, inp)
        c = _safe_call(candidate_fn, inp)
        if b.ok and c.ok:
            held = bool(eq(b.value, c.value))
        elif not b.ok and not c.ok:
            held = type(b.exc) is type(c.exc)
        else:
            held = False  # one raised, the other returned → divergence
        if held:
            passed += 1
        else:
            return FuzzResult(ok=False, trials=i + 1, passed=passed, seed=seed,
                              counterexample=inp, detail=_diff_detail(b, c))
    return FuzzResult(ok=True, trials=n, passed=passed, seed=seed)
