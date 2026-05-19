"""Drift response policy — maps drift signals to typed actions.

Per pillar-ontology-drift.md Pattern 4 (the graduated response table).

| Signal                                                      | Action          |
|-------------------------------------------------------------|-----------------|
| composite ≥ lockdown AND boundary recently crossed          | KILL_SESSION    |
| composite ≥ lockdown                                        | DEMOTE_PLAN     |
| stagnation nudge present (orthogonal axis)                  | NUDGE           |
| composite in [warning, lockdown)                            | OBSERVE         |
| otherwise                                                   | OBSERVE         |

Pure module — the orchestrator decides what to do with the decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DriftAction(str, Enum):
    OBSERVE = "observe"
    NUDGE = "nudge"
    DEMOTE_PLAN = "demote_plan"
    KILL_SESSION = "kill_session"


@dataclass(frozen=True)
class DriftSignal:
    """Aggregated drift inputs to the policy."""

    composite_score: float = 0.0
    severity: str = "low"
    fired_instruments: tuple[str, ...] = ()
    stagnation_nudge: str | None = None
    boundary_recently_crossed: bool = False


@dataclass(frozen=True)
class DriftDecision:
    action: DriftAction
    reason: str
    nudge: str | None = None


def respond(
    signal: DriftSignal,
    *,
    lockdown_threshold: float = 0.30,
    warning_threshold: float = 0.15,
) -> DriftDecision:
    """Map a :class:`DriftSignal` to a :class:`DriftDecision`."""
    score = signal.composite_score

    if signal.boundary_recently_crossed and score >= lockdown_threshold:
        return DriftDecision(
            action=DriftAction.KILL_SESSION,
            reason=f"post-boundary drift {score:.2f} ≥ lockdown",
        )

    if score >= lockdown_threshold:
        return DriftDecision(
            action=DriftAction.DEMOTE_PLAN,
            reason=f"composite {score:.2f} ≥ lockdown ({lockdown_threshold})",
        )

    # Stagnation is independent of behavioral score — even a calm agent
    # can be stuck in a single strategy bucket.
    if signal.stagnation_nudge:
        return DriftDecision(
            action=DriftAction.NUDGE,
            reason="stagnation detected",
            nudge=signal.stagnation_nudge,
        )

    if score >= warning_threshold:
        return DriftDecision(
            action=DriftAction.OBSERVE,
            reason=f"composite {score:.2f} in warning band [{warning_threshold}, {lockdown_threshold})",
        )

    return DriftDecision(action=DriftAction.OBSERVE, reason="no drift")
