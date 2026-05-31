"""Faithfulness gate — is a change's behaviour actually pinned by the suite?

The first live real-task soak (ADR 0158) exposed the core risk of test-gated
autonomy: the agent made the failing tests pass by the cheapest path, which
happened to DROP an untested clause (`or s[i-1].isdigit()` in `to_snake`). The
gate (ruff + pytest) was green, so by the loop's contract it was "correct" — a
textbook Goodhart failure: when an incomplete suite is the target, it gets
satisfied by removing behaviour the suite doesn't guard.

This module is the deterministic primitive against that: given the file a change
touched and the test command, it RE-USES the mutation verifier (ADR 0152,
`verify_test_teeth`) to ask "could you change this file's behaviour and have the
suite still pass?". Every surviving mutant is an unverified behaviour — a blind
spot the agent must close (by authoring a discriminating test) before the change
is accepted as faithfully verified. No human-written contract is involved: the
blind spots are derived from the code itself.

Honest scope. The AST mutator probes operators / constants / boolean ops /
indices — it does NOT probe method-call branches (e.g. `.isdigit()`), so it
will not, on its own, flag a *deleted* method-call clause. It catches
under-tested LOGIC and forces the suite toward completeness; catching behaviour
DELETION needs a complementary differential/characterization check (the next
step). This gate is necessary, not yet sufficient.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .mutation_teeth import verify_test_teeth


@dataclass
class FaithfulnessReport:
    target: str
    baseline_passed: bool
    teeth_score: float = 0.0
    mutants_applied: int = 0
    survived: list[str] = field(default_factory=list)
    threshold: float = 1.0

    @property
    def faithful(self) -> bool:
        """True when the suite passes on the real file AND pins every probed
        behaviour (teeth_score >= threshold, i.e. no surviving mutant above the
        bar). A baseline that does not even pass cannot be assessed → False."""
        return self.baseline_passed and self.teeth_score >= self.threshold

    def summary(self) -> str:
        if not self.baseline_passed:
            return f"UNASSESSABLE — suite not green on {self.target}"
        if self.faithful:
            return (
                f"FAITHFUL — {self.target}: every probed behaviour pinned "
                f"({self.mutants_applied} mutants, score {self.teeth_score:.2f})"
            )
        blind = ", ".join(self.survived) or "(none enumerated)"
        return (
            f"UNDER-VERIFIED — {self.target}: score {self.teeth_score:.2f} < "
            f"{self.threshold:.2f}; unpinned behaviour the change could alter "
            f"undetected — add tests that kill: {blind}"
        )


def assess_faithfulness(
    target_path: Path | str,
    test_cmd: list[str],
    *,
    cwd: Path | str | None = None,
    threshold: float = 1.0,
    max_mutants: int = 40,
    timeout: float = 120.0,
) -> FaithfulnessReport:
    """Assess whether ``test_cmd`` pins the behaviour of ``target_path``.

    Wraps :func:`verify_test_teeth`: runs the suite on the real file (baseline),
    then mutates the file one site at a time; a mutant the suite still passes is
    a surviving blind spot. ``threshold`` is the fraction of mutants that must be
    killed for the change to count as faithfully verified (default 1.0 — every
    probed behaviour pinned). Never raises; the file is always restored.
    """
    report = verify_test_teeth(
        target_path, test_cmd, cwd=cwd, max_mutants=max_mutants, timeout=timeout,
    )
    return FaithfulnessReport(
        target=str(target_path),
        baseline_passed=report.baseline_passed,
        teeth_score=report.teeth_score,
        mutants_applied=report.mutants_applied,
        survived=list(report.survived),
        threshold=threshold,
    )
