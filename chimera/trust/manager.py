"""TrustManager — tier state machine + readiness scoring + persistence.

Readiness composite (per Reggio, simplified for MVP):

    composite =   stability_weight   * (1 − drift_score_clamped_0_1)
                + activity_weight    * activity_rate_clamped
                + hygiene_weight     * (1 − failure_rate_clamped)

Default weights 0.4 / 0.3 / 0.3; default promotion threshold 0.70.

Promotions are also gated by a minimum dwell time per tier (default
3600 s) so the agent doesn't bounce up the ladder in one good cycle.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from dataclasses import asdict, dataclass, field
from enum import IntEnum
from pathlib import Path

logger = logging.getLogger(__name__)


# v4.93 (ADR 0100): graduated trust decrements by escalation severity.
#
# Soak v7 run-3 surfaced that uniform demotion treats every escalation
# signal alike. 3× ungrounded_citation + 1× scope_evasion collapsed
# T5 → T0 LOCKED before phase-2 could begin, even though the
# ungrounded_citation events were the system working as designed:
# v4.83 caught fabricated citations, the model retried, eventually
# grounded correctly, and the phase-1 deliverable LANDED.
#
# The table below splits finish_reasons by what they imply:
#   - silent_failure / scope_evasion: agent wrote (or claimed to write)
#     against intent. Two-tier demote.
#   - artifact_missing / fix_without_test: incomplete delivery against
#     a specified contract. One-tier demote.
#   - ungrounded_citation: draft-quality signal; the model recovers
#     within the same task. Zero demote (logged, not punished).
#   - max_rounds / length: capability/budget signals routed through
#     tier-escalation memory, not trust. Zero demote.
#
# Reasons not in the table receive 0 by default — add them
# deliberately, do not let unknown signals silently drain trust.
FINISH_REASON_TRUST_DELTAS: dict[str, int] = {
    "silent_failure": 2,
    "scope_evasion": 2,
    "artifact_missing": 1,
    "fix_without_test": 1,
    # v4.99 (ADR 0103): phase-scope variant — same severity as the
    # per-task signal; the branch shipped a chimera/ edit without a
    # tests/ counterpart even though no single task tripped v4.92.
    "phase_fix_without_test": 1,
    # v4.96 (ADR 0101): file exists but lacks a required content
    # marker. Moderate severity — same shape as fix_without_test
    # (incomplete delivery against a specified contract).
    "artifact_incomplete": 1,
    # v4.100 (ADR 0104): inbox claim invalid — agent flipped `[ ]`
    # → `[x]` without producing the deliverable. Moderate severity:
    # treats lying about completion as roughly as bad as
    # fix_without_test (one-tier demote). Severe enough to penalise
    # but not so severe that one slip nukes trust — three lies in
    # short order still escalate via successive demotes.
    "inbox_claim_invalid": 1,
    # v4.101 (ADR 0105): syntax_invalid — agent shipped unparseable
    # Python. Same severity as fix_without_test (one-tier demote):
    # incomplete delivery against an implicit "code must parse"
    # contract. Recoverable with a hint; soak v10 surfaced the gap.
    "syntax_invalid": 1,
    "degenerate_loop_abort": 1,
    "ungrounded_citation": 0,
    "max_rounds": 0,
    "length": 0,
}


class TrustTier(IntEnum):
    T0 = 0  # LOCKED
    T1 = 1  # SUPERVISED
    T2 = 2  # UNLOCKED
    T3 = 3  # TRUSTED
    T4 = 4  # ADAPTIVE
    T5 = 5  # AUTONOMOUS

    @property
    def label(self) -> str:
        names = {
            0: "LOCKED",
            1: "SUPERVISED",
            2: "UNLOCKED",
            3: "TRUSTED",
            4: "ADAPTIVE",
            5: "AUTONOMOUS",
        }
        return names[self.value]


def _utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _parse_iso(value: str) -> dt.datetime:
    """ISO 8601 parser tolerant of trailing 'Z'."""
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return dt.datetime.fromisoformat(value)


@dataclass(frozen=True)
class TrustEvent:
    timestamp: str
    kind: str           # promote | demote | lockdown | bootstrap | autopromote
    from_tier: int
    to_tier: int
    reason: str


@dataclass
class TrustState:
    current_tier: int = TrustTier.T0.value
    tier_entered_at: str = field(default_factory=_utc_now_iso)
    history: list[TrustEvent] = field(default_factory=list)
    last_readiness: float = 0.0

    def to_dict(self) -> dict:
        return {
            "current_tier": self.current_tier,
            "tier_entered_at": self.tier_entered_at,
            "last_readiness": self.last_readiness,
            "history": [asdict(e) for e in self.history],
        }

    @classmethod
    def from_dict(cls, data: dict) -> TrustState:
        return cls(
            current_tier=int(data.get("current_tier", 0)),
            tier_entered_at=str(data.get("tier_entered_at") or _utc_now_iso()),
            last_readiness=float(data.get("last_readiness") or 0.0),
            history=[
                TrustEvent(**ev) for ev in (data.get("history") or [])
            ],
        )


class TrustManager:
    """Owns tier state + history. Pure decisions; persistence on save()."""

    def __init__(
        self,
        state_path: Path,
        *,
        promotion_threshold: float = 0.70,
        min_dwell_seconds: float = 3600.0,
        stability_weight: float = 0.4,
        activity_weight: float = 0.3,
        hygiene_weight: float = 0.3,
    ) -> None:
        self.state_path = Path(state_path)
        self.promotion_threshold = promotion_threshold
        self.min_dwell_seconds = min_dwell_seconds
        self.stability_weight = stability_weight
        self.activity_weight = activity_weight
        self.hygiene_weight = hygiene_weight
        self._state = self._load()

    # ── state I/O ──────────────────────────────────────

    def _load(self) -> TrustState:
        if not self.state_path.exists():
            return TrustState()
        try:
            data = json.loads(self.state_path.read_text())
            return TrustState.from_dict(data)
        except (json.JSONDecodeError, OSError, ValueError, TypeError):
            return TrustState()

    def save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(self._state.to_dict(), sort_keys=True, indent=2)
        )

    # ── introspection ─────────────────────────────────

    @property
    def tier(self) -> TrustTier:
        return TrustTier(self._state.current_tier)

    @property
    def state(self) -> TrustState:
        return self._state

    def hours_in_current_tier(self, *, now: dt.datetime | None = None) -> float:
        ts = now or dt.datetime.now(dt.timezone.utc)
        entered = _parse_iso(self._state.tier_entered_at)
        if entered.tzinfo is None:
            entered = entered.replace(tzinfo=dt.timezone.utc)
        return (ts - entered).total_seconds() / 3600.0

    # ── readiness scoring ─────────────────────────────

    def readiness(
        self,
        *,
        drift_score: float,
        activity_rate: float,
        failure_rate: float,
    ) -> float:
        """Composite readiness in [0, 1]. Inputs are pre-clamped by caller."""
        def _clamp(x: float) -> float:
            return max(0.0, min(1.0, x))
        stability = 1.0 - _clamp(drift_score)
        activity = _clamp(activity_rate)
        hygiene = 1.0 - _clamp(failure_rate)
        composite = (
            self.stability_weight * stability
            + self.activity_weight * activity
            + self.hygiene_weight * hygiene
        )
        self._state.last_readiness = round(composite, 4)
        return composite

    # ── transitions ────────────────────────────────────

    def _record_event(self, kind: str, to_tier: int, reason: str) -> None:
        ev = TrustEvent(
            timestamp=_utc_now_iso(),
            kind=kind,
            from_tier=self._state.current_tier,
            to_tier=to_tier,
            reason=reason,
        )
        self._state.history.append(ev)
        if len(self._state.history) > 200:
            self._state.history = self._state.history[-200:]

    def promote(self, *, reason: str = "manual promotion") -> bool:
        if self._state.current_tier >= TrustTier.T5:
            return False
        new = self._state.current_tier + 1
        self._record_event("promote", new, reason)
        self._state.current_tier = new
        self._state.tier_entered_at = _utc_now_iso()
        self.save()
        return True

    def demote(self, *, reason: str) -> bool:
        if self._state.current_tier <= TrustTier.T0:
            return False
        new = self._state.current_tier - 1
        self._record_event("demote", new, reason)
        self._state.current_tier = new
        self._state.tier_entered_at = _utc_now_iso()
        self.save()
        return True

    def lockdown(self, *, reason: str = "drift lockdown") -> bool:
        """Immediate T0 — bypasses gradual demotion."""
        if self._state.current_tier == TrustTier.T0:
            return False
        self._record_event("lockdown", TrustTier.T0.value, reason)
        self._state.current_tier = TrustTier.T0.value
        self._state.tier_entered_at = _utc_now_iso()
        self.save()
        return True

    def set_tier(
        self,
        tier: TrustTier | int,
        *,
        reason: str,
        kind: str = "operator",
    ) -> bool:
        """Jump directly to ``tier`` (operator escape hatch / revoke).

        Returns True if the tier changed. Records a history event tagged
        ``kind`` (e.g. ``"operator"``, ``"revoke"``). Always persists, even
        on no-op, so the audit trail captures the operator action.
        """
        target = int(tier)
        if not 0 <= target <= TrustTier.T5.value:
            raise ValueError(f"tier out of range: {target}")
        if target == self._state.current_tier:
            return False
        self._record_event(kind, target, reason)
        self._state.current_tier = target
        self._state.tier_entered_at = _utc_now_iso()
        self.save()
        return True

    def apply_finish_reason(
        self,
        finish_reason: str,
        *,
        reason_suffix: str = "",
    ) -> int:
        """Demote according to ``FINISH_REASON_TRUST_DELTAS``.

        Returns the number of tiers actually demoted (clamped at T0).
        Unknown reasons demote 0 tiers — they are not silently penalized.
        Events with delta=0 are logged at debug level only; no state
        change, no history entry.
        """
        delta = FINISH_REASON_TRUST_DELTAS.get(finish_reason, 0)
        if delta <= 0:
            logger.debug(
                "trust: finish_reason=%s delta=0 (no demote)", finish_reason
            )
            return 0
        demoted = 0
        for _ in range(delta):
            reason = f"finish_reason={finish_reason} delta={delta}"
            if reason_suffix:
                reason += f" — {reason_suffix}"
            if not self.demote(reason=reason):
                break
            demoted += 1
        return demoted

    def maybe_autopromote(
        self,
        *,
        readiness: float,
        now: dt.datetime | None = None,
        reason_suffix: str = "",
    ) -> bool:
        """Promote one tier if readiness ≥ threshold AND dwell time met."""
        if self._state.current_tier >= TrustTier.T5:
            return False
        if readiness < self.promotion_threshold:
            return False
        dwell_hours = self.hours_in_current_tier(now=now)
        if dwell_hours * 3600 < self.min_dwell_seconds:
            return False
        reason = (
            f"autopromote: readiness={readiness:.2f} dwell={dwell_hours:.2f}h"
        )
        if reason_suffix:
            reason += f" — {reason_suffix}"
        new = self._state.current_tier + 1
        self._record_event("autopromote", new, reason)
        self._state.current_tier = new
        self._state.tier_entered_at = _utc_now_iso()
        self.save()
        return True
