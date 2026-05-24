"""Peer Cards — Honcho-inspired periodic peer-state snapshots (ADR 0128).

A peer card is a consolidated, human-readable per-peer summary that
answers: "who is this peer, how have they been behaving, what state
are they in right now". Cards are refreshed at session rotation and
written to ``mind/peers/<peer>.md`` (one file per peer plus a
``self.md`` for Chimera's own trust state).

This module owns the **deterministic** card: trust label, recent
decisions, last KFM snapshot, last-seen timestamp. The optional LLM
narrative — gated behind ``CHIMERA_PEER_CARD_LLM=1`` per ADR 0128 — is
added by the caller, which knows the provider topology; this module
stays provider-agnostic, mirroring the deriver pattern from ADR 0124.

See [ADR 0128](../../docs/adr/0128-peer-cards.md) for the design
decisions captured against this implementation (storage location,
refresh trigger, schema, scope).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]")


def _safe_filename(peer_name: str) -> str:
    """Sanitise a peer name for use as a path segment.

    Replaces any character outside ``[A-Za-z0-9._-]`` with ``_``, then
    strips leading dots so a name like ``../etc/passwd`` can't render
    as a hidden file or path-like artifact in ``mind/peers/``.
    """
    safe = _SAFE_NAME.sub("_", peer_name or "")
    safe = safe.lstrip(".")
    return safe or "_"


def peers_dir(mind_dir: Path) -> Path:
    """``mind/peers/`` — created on first write by :func:`write_peer_card`."""
    return Path(mind_dir) / "peers"


@dataclass
class PeerCard:
    """Deterministic per-peer snapshot.

    Field semantics:
      * ``peer_name`` — identifier as used by the federation registry,
        or ``"self"`` for Chimera's own trust state.
      * ``is_self`` — True for the self-card; suppresses peer-only
        fields in rendering.
      * ``trust_label`` — string tier label (e.g. ``"TRUSTED"``) or
        decision (``"ALLOW"``); None when unknown.
      * ``composite_score`` — current readiness/composite score in
        [0.0, 1.0], or None when not available.
      * ``recent_events`` — list of (timestamp, label, reason) tuples;
        most-recent first. Capped at 5 by callers.
      * ``last_seen_at`` — ISO timestamp of the last contact/event
        (None for self-card or peers never observed).
      * ``cycles_since_last_contact`` — best-effort integer, or None
        when no current-cycle anchor was supplied.
      * ``kfm_snapshot`` — dict from :func:`a2a.peers.fetch_peer_kfm`,
        or None when the peer is offline or the call failed.
      * ``narrative`` — optional LLM-derived prose paragraph
        (≤100 words). Set by the opt-in narrative path; this module
        does not populate it.
    """

    peer_name: str
    is_self: bool = False
    trust_label: str | None = None
    composite_score: float | None = None
    recent_events: list[tuple[str, str, str]] = field(default_factory=list)
    last_seen_at: str | None = None
    cycles_since_last_contact: int | None = None
    kfm_snapshot: dict[str, Any] | None = None
    narrative: str | None = None


# ── Builders ──────────────────────────────────────────────────────


def build_self_card(
    *,
    trust_state: Any,
    recent_n: int = 5,
) -> PeerCard:
    """Build the self-card from a :class:`chimera.trust.manager.TrustState`.

    Accepts any object with the expected attributes
    (``current_tier``, ``last_readiness``, ``history``,
    ``tier_entered_at``) — the duck-typing keeps the import out of
    this module so a self-card can be assembled in tests without the
    full trust subsystem on the path.
    """
    tier = getattr(trust_state, "current_tier", None)
    history = list(getattr(trust_state, "history", []) or [])
    history.sort(
        key=lambda e: getattr(e, "timestamp", ""),
        reverse=True,
    )
    events: list[tuple[str, str, str]] = []
    for ev in history[:recent_n]:
        ts = getattr(ev, "timestamp", "")
        kind = getattr(ev, "kind", "")
        reason = getattr(ev, "reason", "")
        events.append((ts, kind, reason))

    return PeerCard(
        peer_name="self",
        is_self=True,
        trust_label=_label_for_tier(tier),
        composite_score=getattr(trust_state, "last_readiness", None),
        recent_events=events,
        last_seen_at=getattr(trust_state, "tier_entered_at", None),
    )


def build_peer_card(
    peer_name: str,
    *,
    decisions: list[Any] | None = None,
    kfm_snapshot: dict[str, Any] | None = None,
    current_cycle: int | None = None,
    recent_n: int = 5,
) -> PeerCard:
    """Build a peer card from the peer-trust journal + optional KFM snapshot.

    ``decisions`` is a list of
    :class:`chimera.a2a.peer_trust_journal.TrustDecisionRecord` (or
    any object exposing ``decision``, ``reason``, ``drift_score``,
    ``recorded_at``). Empty / None ⇒ a card with no recent events.

    ``cycles_since_last_contact`` is computed from
    ``kfm_snapshot["cycle"]`` and ``current_cycle`` when both are
    available; otherwise None.
    """
    decisions = list(decisions or [])
    decisions.sort(key=lambda d: getattr(d, "recorded_at", ""), reverse=True)

    events: list[tuple[str, str, str]] = []
    latest_drift: float | None = None
    last_seen: str | None = None
    for rec in decisions[:recent_n]:
        ts = getattr(rec, "recorded_at", "")
        label = getattr(rec, "decision", "")
        reason = getattr(rec, "reason", "")
        events.append((ts, label, reason))
        if last_seen is None and ts:
            last_seen = ts
        if latest_drift is None:
            score = getattr(rec, "drift_score", None)
            if score is not None:
                latest_drift = float(score)

    cycles_since = None
    if (
        kfm_snapshot is not None
        and current_cycle is not None
        and isinstance(kfm_snapshot.get("cycle"), int)
    ):
        cycles_since = max(0, int(current_cycle) - int(kfm_snapshot["cycle"]))

    trust_label = events[0][1] if events else None

    return PeerCard(
        peer_name=peer_name,
        is_self=False,
        trust_label=trust_label,
        composite_score=latest_drift,
        recent_events=events,
        last_seen_at=last_seen,
        cycles_since_last_contact=cycles_since,
        kfm_snapshot=kfm_snapshot,
    )


def _label_for_tier(tier: int | None) -> str | None:
    """Map a trust tier integer to its label, avoiding a hard import."""
    if tier is None:
        return None
    names = {
        0: "LOCKED",
        1: "SUPERVISED",
        2: "UNLOCKED",
        3: "TRUSTED",
        4: "ADAPTIVE",
        5: "AUTONOMOUS",
    }
    try:
        return names.get(int(tier), str(tier))
    except (TypeError, ValueError):
        return None


# ── Rendering ─────────────────────────────────────────────────────


def render_peer_card(card: PeerCard) -> str:
    """Render a :class:`PeerCard` as markdown for ``mind/peers/<peer>.md``.

    The format is operator-grep-able: an H1 with the peer name, then
    a state table, then a recent-events list, then optional KFM and
    narrative sections.
    """
    lines: list[str] = []
    header = "self" if card.is_self else card.peer_name
    lines.append(f"# Peer card — {header}")
    lines.append("")
    lines.append("## State")
    lines.append("")
    rows: list[tuple[str, str]] = []
    if card.trust_label is not None:
        rows.append(("Trust label", card.trust_label))
    if card.composite_score is not None:
        rows.append(("Composite / readiness", f"{card.composite_score:.3f}"))
    if card.last_seen_at:
        rows.append(("Last seen", card.last_seen_at))
    if card.cycles_since_last_contact is not None:
        rows.append(("Cycles since contact", str(card.cycles_since_last_contact)))
    if not rows:
        lines.append("_(no state recorded)_")
    else:
        lines.append("| Field | Value |")
        lines.append("|---|---|")
        for k, v in rows:
            lines.append(f"| {k} | {v} |")
    lines.append("")

    lines.append("## Recent events")
    lines.append("")
    if not card.recent_events:
        lines.append("_(none)_")
    else:
        for ts, label, reason in card.recent_events:
            r = f" — {reason}" if reason else ""
            lines.append(f"- `{ts}` **{label}**{r}")
    lines.append("")

    if card.kfm_snapshot and not card.is_self:
        lines.append("## KFM snapshot")
        lines.append("")
        for k, v in card.kfm_snapshot.items():
            lines.append(f"- **{k}**: {v}")
        lines.append("")

    if card.narrative:
        lines.append("## Narrative")
        lines.append("")
        lines.append(card.narrative.strip())
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# ── Consolidation ─────────────────────────────────────────────────


def write_peer_card(mind_dir: Path, card: PeerCard) -> Path:
    """Write ``card`` to ``mind/peers/<safe-name>.md`` (creating dirs)."""
    target_dir = peers_dir(mind_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{_safe_filename(card.peer_name)}.md"
    path.write_text(render_peer_card(card), encoding="utf-8")
    return path


def consolidate_peer_cards(
    *,
    mind_dir: Path,
    trust_state: Any | None = None,
    peer_names: list[str] | None = None,
    decisions_by_peer: dict[str, list[Any]] | None = None,
    kfm_by_peer: dict[str, dict[str, Any]] | None = None,
    current_cycle: int | None = None,
) -> list[Path]:
    """Build + write self-card and one card per peer; return written paths.

    Every argument is optional so callers can drive the consolidation
    incrementally (e.g. skip KFM fetch when the federation is offline,
    skip the self-card from a test that doesn't have a TrustManager).
    """
    written: list[Path] = []
    if trust_state is not None:
        written.append(write_peer_card(mind_dir, build_self_card(trust_state=trust_state)))

    decisions_by_peer = decisions_by_peer or {}
    kfm_by_peer = kfm_by_peer or {}
    for name in peer_names or []:
        card = build_peer_card(
            name,
            decisions=decisions_by_peer.get(name),
            kfm_snapshot=kfm_by_peer.get(name),
            current_cycle=current_cycle,
        )
        written.append(write_peer_card(mind_dir, card))

    return written


__all__ = [
    "PeerCard",
    "build_peer_card",
    "build_self_card",
    "consolidate_peer_cards",
    "peers_dir",
    "render_peer_card",
    "write_peer_card",
]
