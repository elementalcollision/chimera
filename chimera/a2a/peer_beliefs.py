"""Peer beliefs — observer/observed belief records (ADR 0132).

A belief is a typed snapshot of one agent's view of another, scoped by
``(observer, observed)``. In Honcho's terminology this is the
representation graph: what observer A believes about observed B.

This first cut implements **peer self-beliefs**: the observer is also
the observed (observer == observed == peer). The data source is each
peer's own KFM snapshot (drift_score, trust_tier) fetched via
:func:`chimera.a2a.peers.fetch_peer_kfm`. True cross-peer beliefs
("what peer A says about peer B") require federation protocol
additions — out of scope here; see ADR 0132 §"Out of scope".

The module is **persistence-first**: belief records append to
``mind/peer_beliefs.jsonl`` (one JSON object per line). Downstream
consumers (graph projection, CLI verbs, dashboards) read from the
journal — the JSONL is the source of truth, not the graph.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


# ── Belief label mapping ──────────────────────────────────────────


# Coarse three-band label, derived from drift_score in [0.0, 1.0].
# Thresholds tuned to mirror the trust-manager DEGRADE/REFUSE bands at
# the federation layer (ADR 0009): a peer that's drifted past ~0.6 in
# its own view is unlikely to be trustworthy from ours either.
_TRUST_THRESHOLD = 0.30
_DISTRUST_THRESHOLD = 0.60


def label_for_drift(drift_score: float | None) -> str:
    """Map a drift score to a coarse ``TRUSTS|NEUTRAL|DISTRUSTS|UNKNOWN`` label.

    ``None`` (no signal) → ``"UNKNOWN"``. Scores < 0.30 →
    ``"TRUSTS"``; 0.30 ≤ score < 0.60 → ``"NEUTRAL"``; ≥ 0.60 →
    ``"DISTRUSTS"``. Out-of-range scores are clamped before mapping.
    """
    if drift_score is None:
        return "UNKNOWN"
    try:
        score = float(drift_score)
    except (TypeError, ValueError):
        return "UNKNOWN"
    if score < 0.0:
        score = 0.0
    elif score > 1.0:
        score = 1.0
    if score < _TRUST_THRESHOLD:
        return "TRUSTS"
    if score < _DISTRUST_THRESHOLD:
        return "NEUTRAL"
    return "DISTRUSTS"


# ── Belief record ─────────────────────────────────────────────────


@dataclass(frozen=True)
class PeerBelief:
    """One observer→observed belief snapshot.

    Field semantics:
      * ``observer`` — agent recording the belief (peer name, or
        ``"self"`` for Chimera's own).
      * ``observed`` — agent the belief is about. In this PR's scope
        ``observer == observed`` (peer self-beliefs derived from KFM).
      * ``label`` — one of ``TRUSTS|NEUTRAL|DISTRUSTS|UNKNOWN``.
      * ``drift_score`` — numeric value the label was derived from
        (or ``None``).
      * ``recorded_at`` — ISO timestamp of the snapshot.
      * ``source`` — ``"kfm"`` for KFM-derived beliefs, ``"tool"`` for
        future explicit attestation, ``"operator"`` for CLI-entered.
      * ``extra`` — provenance dict (e.g. raw KFM cycle, trust_tier);
        opaque to the projection layer.
    """

    observer: str
    observed: str
    label: str
    drift_score: float | None
    recorded_at: str
    source: str = "kfm"
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "observer": self.observer,
            "observed": self.observed,
            "label": self.label,
            "drift_score": self.drift_score,
            "recorded_at": self.recorded_at,
            "source": self.source,
            "extra": dict(self.extra),
        }

    @classmethod
    def from_dict(cls, obj: dict[str, Any]) -> PeerBelief:
        return cls(
            observer=str(obj.get("observer", "")),
            observed=str(obj.get("observed", "")),
            label=str(obj.get("label", "UNKNOWN")),
            drift_score=obj.get("drift_score"),
            recorded_at=str(obj.get("recorded_at", "")),
            source=str(obj.get("source", "kfm")),
            extra=dict(obj.get("extra") or {}),
        )


# ── KFM → belief adapter ──────────────────────────────────────────


def belief_from_kfm(peer_name: str, kfm: dict[str, Any]) -> PeerBelief:
    """Construct a self-belief record for ``peer_name`` from its KFM dict.

    The KFM tool (:func:`chimera.a2a.peers.fetch_peer_kfm`) returns
    ``{cycle, trust_tier, plan_kfm_state, last_drift_score}``. We
    derive a coarse label from ``last_drift_score`` and stash the rest
    as provenance in ``extra``.
    """
    drift = kfm.get("last_drift_score")
    return PeerBelief(
        observer=peer_name,
        observed=peer_name,
        label=label_for_drift(drift),
        drift_score=float(drift) if drift is not None else None,
        recorded_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        source="kfm",
        extra={
            "cycle": kfm.get("cycle"),
            "trust_tier": kfm.get("trust_tier"),
            "plan_kfm_state": kfm.get("plan_kfm_state"),
        },
    )


# ── JSONL persistence ─────────────────────────────────────────────


def default_journal_path(mind_dir: Path) -> Path:
    """``mind/peer_beliefs.jsonl`` — created on first write."""
    return Path(mind_dir) / "peer_beliefs.jsonl"


def record_belief(belief: PeerBelief, *, mind_dir: Path) -> Path:
    """Append ``belief`` to ``mind/peer_beliefs.jsonl``; return its path."""
    target = default_journal_path(mind_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(belief.to_dict(), ensure_ascii=False) + "\n")
    return target


def list_beliefs(
    *,
    mind_dir: Path,
    observer: str | None = None,
    observed: str | None = None,
) -> list[PeerBelief]:
    """Read every belief from the journal, oldest-first.

    Optional ``observer`` / ``observed`` filters narrow the result.
    Malformed lines are skipped silently — the journal is append-only
    and a half-written line (crash mid-write) shouldn't break readers.
    """
    target = default_journal_path(mind_dir)
    if not target.exists():
        return []
    out: list[PeerBelief] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        belief = PeerBelief.from_dict(obj)
        if observer is not None and belief.observer != observer:
            continue
        if observed is not None and belief.observed != observed:
            continue
        out.append(belief)
    return out


def latest_per_pair(*, mind_dir: Path) -> dict[tuple[str, str], PeerBelief]:
    """Return the most-recent belief per ``(observer, observed)`` tuple.

    Most-recent is determined by ``recorded_at`` (ISO strings sort
    correctly under lexicographic comparison given fixed precision).
    """
    out: dict[tuple[str, str], PeerBelief] = {}
    for b in list_beliefs(mind_dir=mind_dir):
        key = (b.observer, b.observed)
        prev = out.get(key)
        if prev is None or b.recorded_at > prev.recorded_at:
            out[key] = b
    return out


__all__ = [
    "PeerBelief",
    "belief_from_kfm",
    "default_journal_path",
    "label_for_drift",
    "latest_per_pair",
    "list_beliefs",
    "record_belief",
]
