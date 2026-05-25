"""Dialectic API — LLM-queryable peer-model surface (ADR 0133).

Phase 3 #2 of the Honcho-inspired roadmap (ADR 0123). The dialectic
API lets a caller (operator via CLI, or a federated peer via MCP) ask
a natural-language question about what Chimera knows about a peer.

The module is **persistence-aware but provider-agnostic** — it
gathers context from the journals on disk (peer cards, peer-trust
journal, optionally peer-beliefs JSONL and a live KFM fetch) and
hands the assembled prompt back. The caller runs the provider call.
Mirrors the deriver pattern (ADR 0124) and the peer-cards narrative
layer (ADR 0130).

Sources consulted, in priority order:

  1. ``mind/peers/<peer>.md`` — the deterministic+narrated peer card
     (ADR 0128–0131).
  2. ``chimera/a2a/peer_trust_journal.py`` — last N ALLOW/DEGRADE/REFUSE
     decisions, with reasons.
  3. ``mind/peer_beliefs.jsonl`` — observer/observed self-beliefs
     (ADR 0132). **Optional**: module imports defensively so this
     works whether or not ADR 0132 has landed on main.
  4. Live KFM snapshot via :func:`chimera.a2a.peers.fetch_peer_kfm`,
     only when the caller passes ``fetch_kfm=True``. Adds a network
     call per ``ask``; opt-in.

When a peer is unknown (no card, no journal entries), the context is
empty and :func:`build_dialectic_prompt` produces a "no data" framing
the LLM is asked to use honestly. See ADR 0133 §"Unknown peer".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ── Filename sanitiser (mirrors engines/peer_cards.py) ────────────


_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]")


def _safe_filename(peer_name: str) -> str:
    safe = _SAFE_NAME.sub("_", peer_name or "")
    safe = safe.lstrip(".")
    return safe or "_"


# ── Context bundle ───────────────────────────────────────────────


@dataclass
class DialecticContext:
    """Bundle of grounding signal assembled for one ``ask`` call.

    Every field is optional — an unknown peer produces a context
    where everything is ``None`` / empty, and the prompt builder
    renders a "no data" framing.
    """

    peer_name: str
    peer_card_markdown: str | None = None
    recent_decisions: list[dict[str, Any]] = field(default_factory=list)
    beliefs: list[dict[str, Any]] = field(default_factory=list)
    kfm_snapshot: dict[str, Any] | None = None
    sources_used: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return (
            self.peer_card_markdown is None
            and not self.recent_decisions
            and not self.beliefs
            and not self.kfm_snapshot
        )


# ── Gather (sync; KFM is opt-in async via caller) ────────────────


def gather_dialectic_context(
    peer_name: str,
    *,
    mind_dir: Path,
    recent_decisions_n: int = 5,
) -> DialecticContext:
    """Read every available grounding source for ``peer_name``.

    Sync only — no LLM, no network. The KFM fetch is left to the
    caller (which may want it async-batched with other peers).
    Belief journal is imported defensively so an environment without
    ADR 0132 still produces a useful context.
    """
    ctx = DialecticContext(peer_name=peer_name)

    # 1. Peer card markdown.
    card_path = Path(mind_dir) / "peers" / f"{_safe_filename(peer_name)}.md"
    if card_path.exists():
        try:
            ctx.peer_card_markdown = card_path.read_text(encoding="utf-8")
            ctx.sources_used.append(f"peer_card:{card_path.name}")
        except OSError:
            pass

    # 2. Peer-trust journal — last N decisions.
    try:
        from .peer_trust_journal import list_decisions
        decisions = list_decisions(peer_name)
        decisions.sort(
            key=lambda d: getattr(d, "recorded_at", ""), reverse=True,
        )
        for rec in decisions[:recent_decisions_n]:
            ctx.recent_decisions.append({
                "decision": getattr(rec, "decision", ""),
                "reason": getattr(rec, "reason", ""),
                "drift_score": getattr(rec, "drift_score", None),
                "recorded_at": getattr(rec, "recorded_at", ""),
            })
        if ctx.recent_decisions:
            ctx.sources_used.append(
                f"trust_journal:{len(ctx.recent_decisions)}",
            )
    except Exception:
        # Trust journal absent / read failure: keep going.
        pass

    # 3. Belief JSONL (ADR 0132) — optional / defensive import.
    try:
        from .peer_beliefs import list_beliefs  # type: ignore[import-not-found]
        beliefs = list_beliefs(mind_dir=mind_dir, observer=peer_name)
        beliefs.sort(
            key=lambda b: getattr(b, "recorded_at", ""), reverse=True,
        )
        for b in beliefs[:recent_decisions_n]:
            ctx.beliefs.append({
                "observer": getattr(b, "observer", ""),
                "observed": getattr(b, "observed", ""),
                "label": getattr(b, "label", "UNKNOWN"),
                "drift_score": getattr(b, "drift_score", None),
                "recorded_at": getattr(b, "recorded_at", ""),
            })
        if ctx.beliefs:
            ctx.sources_used.append(f"beliefs:{len(ctx.beliefs)}")
    except Exception:
        # Module not present (ADR 0132 not on main): skip silently.
        pass

    return ctx


# ── Prompt template ──────────────────────────────────────────────


_DIALECTIC_PROMPT = """You are Chimera's Dialectic agent. Answer the question \
about peer "{peer_name}" in a single short paragraph (UNDER 120 words). \
Use ONLY the grounding below — do not invent facts. If the grounding \
doesn't support an answer, say so honestly.
When the question requires information from multiple sessions, integrate facts across the entire history. When a fact stated in an earlier session is contradicted by a later session, prefer the later session.

Question: {question}

── Peer card (mind/peers/{safe_name}.md) ──
{peer_card_block}

── Recent trust decisions ──
{decisions_block}

── Recent beliefs (observer→observed) ──
{beliefs_block}

── Live KFM snapshot ──
{kfm_block}

Answer in plain prose. No markdown, no preamble."""


_UNKNOWN_PEER_PROMPT = """You are Chimera's Dialectic agent. A user asked about \
peer "{peer_name}" but Chimera has no recorded information about them — no \
peer card, no trust decisions, no beliefs.

Question: {question}

Reply in one short sentence honestly stating that Chimera has no record of \
this peer. Do not invent information."""


def _render_decisions(decisions: list[dict[str, Any]]) -> str:
    if not decisions:
        return "(none)"
    out = []
    for d in decisions:
        reason = f" — {d['reason']}" if d.get("reason") else ""
        score = (
            f" [drift={d['drift_score']:.2f}]"
            if isinstance(d.get("drift_score"), (int, float))
            else ""
        )
        out.append(
            f"- {d.get('recorded_at', '')} "
            f"**{d.get('decision', '')}**{score}{reason}"
        )
    return "\n".join(out)


def _render_beliefs(beliefs: list[dict[str, Any]]) -> str:
    if not beliefs:
        return "(none)"
    out = []
    for b in beliefs:
        score = (
            f" [drift={b['drift_score']:.2f}]"
            if isinstance(b.get("drift_score"), (int, float))
            else ""
        )
        out.append(
            f"- {b.get('recorded_at', '')} "
            f"({b.get('observer', '')}→{b.get('observed', '')}) "
            f"**{b.get('label', '')}**{score}"
        )
    return "\n".join(out)


def _render_kfm(kfm: dict[str, Any] | None) -> str:
    if not kfm:
        return "(not fetched)"
    return "\n".join(f"- {k}: {v}" for k, v in sorted(kfm.items()))


def build_dialectic_prompt(ctx: DialecticContext, question: str) -> str:
    """Render the dialectic prompt for ``ctx``.

    When the context is empty, returns the "no data" framing instead
    of the full template — keeps the LLM from confabulating.
    """
    if ctx.is_empty():
        return _UNKNOWN_PEER_PROMPT.format(
            peer_name=ctx.peer_name,
            question=question.strip(),
        )
    return _DIALECTIC_PROMPT.format(
        peer_name=ctx.peer_name,
        safe_name=_safe_filename(ctx.peer_name),
        question=question.strip(),
        peer_card_block=(ctx.peer_card_markdown or "(no card)").strip(),
        decisions_block=_render_decisions(ctx.recent_decisions),
        beliefs_block=_render_beliefs(ctx.beliefs),
        kfm_block=_render_kfm(ctx.kfm_snapshot),
    )


def trim_answer(text: str, *, word_cap: int = 140) -> str:
    """Strip markdown fences and cap to ``word_cap`` words.

    Mirrors :func:`chimera.engines.peer_cards.apply_narrative` — the
    prompt asks for ≤120 words; we cap at 140 (20-word slack) and add
    an ellipsis when trimmed.
    """
    if not text:
        return ""
    t = text.strip()
    if t.startswith("```"):
        lines = t.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        t = "\n".join(lines).strip()
    words = re.findall(r"\S+", t)
    if len(words) > word_cap:
        t = " ".join(words[:word_cap]) + "…"
    return t


__all__ = [
    "DialecticContext",
    "build_dialectic_prompt",
    "gather_dialectic_context",
    "trim_answer",
]
