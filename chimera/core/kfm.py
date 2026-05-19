"""KFM lifecycle state machine — pure table-driven module.

Ported from ``village/services/clerk/src/clerk/kfm.py`` per ADR 0001
§"KFM functional ontology" and grounded in Agentic_Evolution §3 + §8.2.

Single source of truth for:

  1. The legal KFM states.
  2. The legal transitions between those states.
  3. The operator authorised to request each transition.
  4. A pure ``check_transition(from_state, to_state, operator_type)``
     function returning a structured result — never raises, never
     touches a DB.

This module is intentionally stateless. Persistence is handled in
:mod:`chimera.memory.entities`; this file only knows the rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# Canonical KFM lifecycle states, in the order an entity walks through them.
KFM_STATES: tuple[str, ...] = (
    "NEW",
    "EXPERIMENTAL",
    "CANDIDATE",
    "STABLE",
    "DEPRECATED",
    "ARCHIVED",
    "KILLED",
)

#: Operator labels. ``bootstrap`` is the privileged escape hatch used at
#: agent creation; it is never a legal request value on a state-change
#: endpoint outside the bootstrap path.
OperatorType = Literal["f", "m", "k", "bootstrap"]

#: Map of from_state → frozenset of legal to_states. Linear today; later
#: extensions (e.g. ARCHIVED → EXPERIMENTAL revival) require their own ADR.
LEGAL_TRANSITIONS: dict[str, frozenset[str]] = {
    "NEW": frozenset({"EXPERIMENTAL"}),
    "EXPERIMENTAL": frozenset({"CANDIDATE"}),
    "CANDIDATE": frozenset({"STABLE"}),
    "STABLE": frozenset({"DEPRECATED"}),
    "DEPRECATED": frozenset({"ARCHIVED"}),
    "ARCHIVED": frozenset({"KILLED"}),
    "KILLED": frozenset(),
}

#: Map of (from_state, to_state) → the single operator authorised to request it.
TRANSITION_AUTHORITY: dict[tuple[str, str], OperatorType] = {
    ("NEW", "EXPERIMENTAL"): "f",
    ("EXPERIMENTAL", "CANDIDATE"): "m",
    ("CANDIDATE", "STABLE"): "m",
    ("STABLE", "DEPRECATED"): "k",
    ("DEPRECATED", "ARCHIVED"): "k",
    ("ARCHIVED", "KILLED"): "k",
}


@dataclass(frozen=True)
class TransitionResult:
    """Pure-function result. Never raises; the caller translates into errors."""

    allowed: bool
    reason: str
    authorized_operator: OperatorType | None = None

    @property
    def ok(self) -> bool:
        return self.allowed


def check_transition(
    from_state: str,
    to_state: str,
    operator_type: str,
) -> TransitionResult:
    """Is this a legal KFM transition by an authorised operator?

    Returns a :class:`TransitionResult`. Never raises. Never touches a DB.
    """
    if from_state not in KFM_STATES:
        return TransitionResult(False, "unknown_from_state")
    if to_state not in KFM_STATES:
        return TransitionResult(False, "unknown_to_state")
    if operator_type not in ("f", "m", "k", "bootstrap"):
        return TransitionResult(False, "unknown_operator")
    legal = LEGAL_TRANSITIONS.get(from_state, frozenset())
    if to_state not in legal:
        return TransitionResult(False, "illegal_transition")
    authorized = TRANSITION_AUTHORITY[(from_state, to_state)]
    if operator_type != authorized and operator_type != "bootstrap":
        return TransitionResult(
            False, "operator_not_authorized", authorized_operator=authorized
        )
    return TransitionResult(True, "ok", authorized_operator=authorized)
