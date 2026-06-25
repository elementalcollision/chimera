"""Witness-panel calibration + candidate A/B (ADR 0187 #4).

Runs the witness-panel members — and an optional CANDIDATE member (e.g. Sakana
`fugu-ultra`) — over a labelled change set, then reports:

- each member's accuracy, especially the dangerous **false-APPROVE** (waving a
  bad change through);
- the candidate's **vote-agreement** with each existing member — the INDEPENDENCE
  check: a cross-vendor router like Fugu may *correlate* with the existing slots
  rather than add a fresh gradient, in which case it earns no panel seat;
- the panel's accuracy **with vs without** the candidate (does adding it flip
  decisions toward or away from the truth?).

Measurement only — never changes a live gate. The per-case decision reuses the
real :func:`witness_panel.panel_decision` (asymmetric charter override + voting).
"""

from __future__ import annotations

from dataclasses import dataclass

from .witness_panel import panel_decision


@dataclass(frozen=True)
class MemberStats:
    label: str
    n: int               # cases the member actually ANSWERED (errors excluded)
    correct: int
    false_approve: int   # approved a change that SHOULD be rejected (dangerous)
    false_reject: int    # rejected a change that SHOULD be approved
    errors: int = 0      # cases the provider failed on — EXCLUDED, never counted

    @property
    def accuracy(self) -> float:
        return self.correct / self.n if self.n else 0.0


def member_stats(label: str, verdicts: list, should_approve: list[bool]) -> MemberStats:
    """Per-member confusion over the labelled cases. ``verdicts`` are WitnessVerdicts
    (``.approved``) aligned with ``should_approve``; a ``None`` entry is an ERROR
    (provider outage / credit exhaustion) and is EXCLUDED — never silently counted
    as an approve, which would fabricate verdicts and corrupt false-approve."""
    correct = fa = fr = errors = answered = 0
    for v, ok in zip(verdicts, should_approve):
        if v is None:
            errors += 1
            continue
        answered += 1
        if bool(v.approved) == ok:
            correct += 1
        elif v.approved and not ok:
            fa += 1
        else:  # (not approved) and ok
            fr += 1
    return MemberStats(label, answered, correct, fa, fr, errors)


def vote_agreement(a: list, b: list) -> float:
    """Fraction of cases where two members' approve/reject decisions match.

    1.0 = identical voter (redundant); ~0.5 = independent on a balanced set. The
    independence signal for whether a candidate adds a fresh gradient. Cases where
    EITHER member errored (``None``) are excluded."""
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if not pairs:
        return 0.0
    return sum(1 for x, y in pairs if bool(x.approved) == bool(y.approved)) / len(pairs)


def panel_confusion(
    per_member_verdicts: list[list],
    should_approve: list[bool],
    *,
    voting: str = "majority",
) -> dict:
    """Confusion of the panel decision against the labels, using the real asymmetric
    rule. A member that errored (``None``) on a case simply does not vote on it; a
    case where NO member answered is skipped (``skipped``) rather than decided on
    an empty panel."""
    correct = fa = fr = skipped = 0
    for i, ok in enumerate(should_approve):
        case_verdicts = [m[i] for m in per_member_verdicts if m[i] is not None]
        if not case_verdicts:
            skipped += 1
            continue
        approved = panel_decision(case_verdicts, voting=voting)
        if approved == ok:
            correct += 1
        elif approved and not ok:
            fa += 1
        else:
            fr += 1
    counted = len(should_approve) - skipped
    return {"n": counted, "correct": correct, "false_approve": fa,
            "false_reject": fr, "skipped": skipped,
            "accuracy": correct / counted if counted else 0.0}
