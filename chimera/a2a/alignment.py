"""Alignment ceremony — verify a peer is aligned before substantive work.

Per ADR 0013 (v2.8). Loosely modelled on Xenocomm's 5 alignment
strategies but specialised to Chimera's existing identity + kfm-state
data plane (no new wire format).

Five pure strategies run against the peer's advertised payload:

- **capability**: required capabilities are all present in the peer's
  advertised set
- **version**: peer's major version matches ours (semver-major compat)
- **kfm_state**: peer's plan is in the OK set (STABLE / CANDIDATE);
  otherwise it's drifted
- **schema**: a peer-side tool schema is compatible with ours
  (compared by parameter name set)
- **drift**: peer's last drift composite is under the lockdown threshold

Each strategy returns an :class:`AlignmentReport`. The ceremony
aggregates them into one :class:`CeremonyVerdict`:

  - all ALIGNED → ``aligned``
  - any FAILED → ``failed`` (refuse downstream calls)
  - else → ``drifted`` (proceed cautiously / degrade)

The ceremony is pure — input is whatever payload the caller hands
in. Callers do the fetching (via the existing identity / kfm-state /
list_tools paths).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AlignmentResult(str, Enum):
    ALIGNED = "aligned"
    DRIFTED = "drifted"
    FAILED = "failed"


class CeremonyResult(str, Enum):
    ALIGNED = "aligned"
    DRIFTED = "drifted"
    FAILED = "failed"


@dataclass(frozen=True)
class AlignmentReport:
    strategy: str
    result: AlignmentResult
    reason: str


@dataclass(frozen=True)
class CeremonyVerdict:
    result: CeremonyResult
    reports: tuple[AlignmentReport, ...]

    @property
    def reasons(self) -> list[str]:
        return [r.reason for r in self.reports]


# ── individual strategies ───────────────────────────────────


def capability_alignment(
    peer_identity: dict[str, Any] | None,
    *,
    required: tuple[str, ...],
) -> AlignmentReport:
    if peer_identity is None:
        return AlignmentReport(
            strategy="capability",
            result=AlignmentResult.FAILED,
            reason="no peer identity available",
        )
    caps = set(peer_identity.get("capabilities") or ())
    missing = sorted(set(required) - caps)
    if not missing:
        return AlignmentReport(
            strategy="capability",
            result=AlignmentResult.ALIGNED,
            reason=f"peer has all required capabilities ({len(required)})",
        )
    return AlignmentReport(
        strategy="capability",
        result=AlignmentResult.FAILED,
        reason=f"peer missing capabilities: {missing}",
    )


def _major(version: str) -> int | None:
    head, _, _ = (version or "").lstrip("v").partition(".")
    try:
        return int(head)
    except ValueError:
        return None


def version_alignment(
    peer_identity: dict[str, Any] | None,
    *,
    local_version: str,
) -> AlignmentReport:
    if peer_identity is None:
        return AlignmentReport(
            strategy="version",
            result=AlignmentResult.FAILED,
            reason="no peer identity available",
        )
    peer_ver = str(peer_identity.get("version") or "")
    p_major = _major(peer_ver)
    l_major = _major(local_version)
    if p_major is None or l_major is None:
        return AlignmentReport(
            strategy="version",
            result=AlignmentResult.DRIFTED,
            reason=f"unparseable version(s): peer={peer_ver!r} local={local_version!r}",
        )
    if p_major == l_major:
        return AlignmentReport(
            strategy="version",
            result=AlignmentResult.ALIGNED,
            reason=f"semver-major match (v{p_major})",
        )
    return AlignmentReport(
        strategy="version",
        result=AlignmentResult.DRIFTED,
        reason=f"peer major v{p_major} vs local v{l_major}",
    )


_OK_KFM_STATES = frozenset({"STABLE", "CANDIDATE"})


def kfm_state_alignment(
    peer_state: dict[str, Any] | None,
) -> AlignmentReport:
    if peer_state is None:
        return AlignmentReport(
            strategy="kfm_state",
            result=AlignmentResult.DRIFTED,
            reason="peer state unavailable",
        )
    state = peer_state.get("plan_kfm_state")
    if state in _OK_KFM_STATES:
        return AlignmentReport(
            strategy="kfm_state",
            result=AlignmentResult.ALIGNED,
            reason=f"peer plan in {state}",
        )
    if state in {"DEPRECATED", "ARCHIVED", "KILLED"}:
        return AlignmentReport(
            strategy="kfm_state",
            result=AlignmentResult.FAILED,
            reason=f"peer plan in terminal-ish state {state!r}",
        )
    return AlignmentReport(
        strategy="kfm_state",
        result=AlignmentResult.DRIFTED,
        reason=f"peer plan in {state!r} (not OK, not terminal)",
    )


def schema_alignment(
    peer_schema: dict[str, Any] | None,
    local_schema: dict[str, Any],
) -> AlignmentReport:
    """Compare two OpenAI-shaped tool schemas by parameter name set."""
    if peer_schema is None:
        return AlignmentReport(
            strategy="schema",
            result=AlignmentResult.DRIFTED,
            reason="peer schema unavailable",
        )

    def _params(sch: dict[str, Any]) -> set[str]:
        fn = sch.get("function") if sch.get("type") == "function" else sch
        params = (fn or {}).get("parameters") or {}
        return set((params.get("properties") or {}).keys())

    peer_params = _params(peer_schema)
    local_params = _params(local_schema)
    if peer_params == local_params:
        return AlignmentReport(
            strategy="schema",
            result=AlignmentResult.ALIGNED,
            reason="param sets identical",
        )
    only_peer = sorted(peer_params - local_params)
    only_local = sorted(local_params - peer_params)
    if local_params.issubset(peer_params):
        return AlignmentReport(
            strategy="schema",
            result=AlignmentResult.DRIFTED,
            reason=f"peer has extra params {only_peer}; local subset",
        )
    return AlignmentReport(
        strategy="schema",
        result=AlignmentResult.FAILED,
        reason=f"peer missing local params {only_local}",
    )


def drift_alignment(
    peer_state: dict[str, Any] | None,
    *,
    lockdown_threshold: float = 0.30,
) -> AlignmentReport:
    if peer_state is None:
        return AlignmentReport(
            strategy="drift",
            result=AlignmentResult.DRIFTED,
            reason="peer state unavailable",
        )
    score = peer_state.get("last_drift_score")
    if score is None:
        return AlignmentReport(
            strategy="drift",
            result=AlignmentResult.ALIGNED,
            reason="no drift score (treat as 0)",
        )
    try:
        s = float(score)
    except (TypeError, ValueError):
        return AlignmentReport(
            strategy="drift",
            result=AlignmentResult.DRIFTED,
            reason=f"unparseable drift score: {score!r}",
        )
    if s >= lockdown_threshold:
        return AlignmentReport(
            strategy="drift",
            result=AlignmentResult.FAILED,
            reason=f"peer drift {s:.2f} ≥ lockdown ({lockdown_threshold})",
        )
    return AlignmentReport(
        strategy="drift",
        result=AlignmentResult.ALIGNED,
        reason=f"peer drift {s:.2f} below lockdown",
    )


# ── aggregator ──────────────────────────────────────────────


@dataclass
class AlignmentCeremony:
    """Aggregate the 5 strategies against one peer's payloads.

    Inputs:
      - ``peer_identity``: dict from ``chimera-identity`` (or None)
      - ``peer_state``:    dict from ``chimera-kfm-state`` (or None)
      - ``required_capabilities``: capabilities the local agent expects
      - ``local_version``: this Chimera's version (for semver-major check)
      - ``schema_pair``:   optional (peer_schema, local_schema) tuple to run
                           schema_alignment on; ``None`` skips that strategy
      - ``lockdown_threshold``: per ADR 0009; default 0.30

    Call :meth:`run` to get a :class:`CeremonyVerdict`.
    """

    required_capabilities: tuple[str, ...] = ()
    local_version: str = ""
    schema_pair: tuple[dict, dict] | None = None
    lockdown_threshold: float = 0.30

    def run(
        self,
        *,
        peer_identity: dict[str, Any] | None,
        peer_state: dict[str, Any] | None,
    ) -> CeremonyVerdict:
        reports: list[AlignmentReport] = [
            capability_alignment(peer_identity, required=self.required_capabilities),
            version_alignment(peer_identity, local_version=self.local_version),
            kfm_state_alignment(peer_state),
            drift_alignment(peer_state, lockdown_threshold=self.lockdown_threshold),
        ]
        if self.schema_pair is not None:
            reports.append(schema_alignment(self.schema_pair[0], self.schema_pair[1]))

        any_failed = any(r.result is AlignmentResult.FAILED for r in reports)
        any_drifted = any(r.result is AlignmentResult.DRIFTED for r in reports)
        if any_failed:
            verdict = CeremonyResult.FAILED
        elif any_drifted:
            verdict = CeremonyResult.DRIFTED
        else:
            verdict = CeremonyResult.ALIGNED
        return CeremonyVerdict(result=verdict, reports=tuple(reports))
