"""Cross-provider witness panel for ACT code review (v4.103, ADR 0107).

Extends v4.102's single-witness gate (``chimera/core/witness.py``).
Replaces the single ``witness_code_change`` call with a panel of N
witnesses spanning multiple providers; voting is unanimous by default.

References
----------
- ADR 0031 (multi-witness critique for skill assembly).
- ADR 0035 (cross-provider defaults).
- ADR 0106 (v4.102: single-witness code review).
- ADR 0107 (v4.103: this module — cross-provider panel for code review).

Rationale: a single witness from the same provider as the agent has
correlated failure modes. Soak v10's broken ``ActResult(...)`` block
parsed-but-was-malformed Python; a same-family witness might
pattern-match it as "reasonable-looking." Cross-provider panels (ADR
0031) catch the gradient blind-spot. v4.103 wires that pattern into
v4.102's code-review hook.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from ..providers import Provider
from ..providers.tiers import Provider as ProviderKind
from .witness import WitnessVerdict, witness_code_change

logger = logging.getLogger(__name__)


# ── Configuration ─────────────────────────────────────────


def panel_size() -> int:
    """``CHIMERA_WITNESS_PANEL_SIZE`` env var. Default: 3.

    Clamped to ``[1, 5]``. 1 is the debugging escape hatch — under
    ``CHIMERA_WITNESS_REQUIRE_CROSS_PROVIDER=1`` it will log a warning.
    """
    raw = os.environ.get("CHIMERA_WITNESS_PANEL_SIZE", "3").strip()
    try:
        n = int(raw)
    except ValueError:
        return 3
    return max(1, min(n, 5))


def require_cross_provider() -> bool:
    """``CHIMERA_WITNESS_REQUIRE_CROSS_PROVIDER`` env var. Default: 1.

    Soaks should always be 1. Setting 0 silences the degradation
    warning when only one provider is configured.
    """
    return os.environ.get(
        "CHIMERA_WITNESS_REQUIRE_CROSS_PROVIDER", "1"
    ).strip() not in {"0", "", "false", "False"}


def voting_rule() -> str:
    """``CHIMERA_WITNESS_VOTING`` env var. Default: ``unanimous``.

    Code review is stricter than skill-assembly's majority rule because
    foundational-code blast radius makes false-negative cost ≫
    false-positive cost.
    """
    raw = os.environ.get("CHIMERA_WITNESS_VOTING", "unanimous").strip().lower()
    return raw if raw in {"unanimous", "majority"} else "unanimous"


# ── Panel members ─────────────────────────────────────────


@dataclass(frozen=True)
class PanelMember:
    """One slot in the witness panel.

    ``label`` is the human-readable tag we prefix concerns with
    (e.g. ``"anthropic:sonnet"``). ``provider_kind`` selects the
    runtime provider; ``model_id`` is what that provider sees;
    ``context_tokens`` informs diff-chunking decisions.
    """
    label: str
    provider_kind: ProviderKind
    model_id: str
    context_tokens: int = 200_000


# Default panel: Anthropic sonnet + two distinct OpenRouter providers.
# Captured here rather than in tiers.json because v4.103's contract is
# "cross-provider witness for code review" and the membership is tied
# to that contract, not to general tier routing.
_DEFAULT_PANEL: tuple[PanelMember, ...] = (
    PanelMember(
        "anthropic:sonnet", ProviderKind.ANTHROPIC,
        "claude-sonnet-4-6", context_tokens=200_000,
    ),
    PanelMember(
        "openrouter:deepseek-v4-pro", ProviderKind.OPENROUTER,
        "deepseek/deepseek-v4-pro", context_tokens=1_048_576,
    ),
    PanelMember(
        "openrouter:gpt-5-pro", ProviderKind.OPENROUTER,
        "openai/gpt-5-pro", context_tokens=400_000,
    ),
)


def build_witness_panel(
    agent_provider_kind: ProviderKind,
    available: set[ProviderKind],
    *,
    size: int | None = None,
    require_diversity: bool | None = None,
) -> list[PanelMember]:
    """Pick up to ``size`` panel members enforcing provider diversity.

    Rules:
      - The agent's own provider appears at most ONCE.
      - Members from providers other than the agent's are preferred
        in the ordering.
      - Members whose ``provider_kind`` is not in ``available`` are
        skipped (their runtime ``Provider`` is unconfigured).
      - When ``require_diversity`` is true and only one provider is
        configured, returns a degraded panel and logs a warning — the
        soak runner is responsible for surfacing that.
    """
    n = size if size is not None else panel_size()
    diversity = (
        require_diversity if require_diversity is not None
        else require_cross_provider()
    )

    pool = [m for m in _DEFAULT_PANEL if m.provider_kind in available]
    if not pool:
        return []

    others = [m for m in pool if m.provider_kind != agent_provider_kind]
    own = [m for m in pool if m.provider_kind == agent_provider_kind]
    ordered = others + own

    picked: list[PanelMember] = []
    agent_seen = False
    seen_providers: set[ProviderKind] = set()
    for m in ordered:
        if len(picked) >= n:
            break
        if m.provider_kind == agent_provider_kind:
            if agent_seen:
                continue
            agent_seen = True
        picked.append(m)
        seen_providers.add(m.provider_kind)

    if diversity and len(seen_providers) < 2:
        logger.warning(
            "witness_panel: only %d provider(s) available; degrading "
            "to single-provider panel (size=%d). Set "
            "CHIMERA_WITNESS_REQUIRE_CROSS_PROVIDER=0 to silence.",
            len(seen_providers), len(picked),
        )
    return picked


# ── Decision + aggregation ────────────────────────────────


def panel_decision(
    verdicts: Iterable[WitnessVerdict],
    *,
    voting: str | None = None,
) -> bool:
    """Apply the configured voting rule to ``verdicts``.

    Empty panel approves (no signal to act on). Unanimous gate is the
    default; majority is the v4.102 fallback when explicitly set.
    """
    rule = voting or voting_rule()
    vs = list(verdicts)
    if not vs:
        return True
    if rule == "unanimous":
        return all(v.approved for v in vs)
    return sum(1 for v in vs if v.approved) > len(vs) / 2


def aggregate_concerns(
    labelled: list[tuple[str, WitnessVerdict]],
    *,
    cap: int = 5,
) -> list[str]:
    """Collect concerns from rejecting witnesses, tagged + deduped.

    Output shape: ``["[label] concern", ...]``. Dedupe is by the
    lower-cased first 60 chars — close enough to catch
    "Dangling open-paren on line 1524" repeated across witnesses
    without coalescing genuinely different issues.
    """
    out: list[str] = []
    seen: set[str] = set()
    for label, v in labelled:
        if v.approved:
            continue
        for c in v.concerns:
            stripped = c.strip()
            key = stripped.lower()[:60]
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(f"[{label}] {stripped}")
            if len(out) >= cap:
                return out
    return out


# ── Diff sizing ───────────────────────────────────────────


def _approx_tokens(diff: str) -> int:
    """Cheap 4-char-per-token estimate."""
    return max(1, len(diff) // 4)


def diff_fits(diff: str, panel: list[PanelMember]) -> bool:
    """All members can ingest the diff with room for prompt + reply."""
    if not panel:
        return True
    overhead = 2_000
    approx = _approx_tokens(diff) + overhead
    return all(approx <= m.context_tokens for m in panel)


def split_by_file(diff: str) -> list[str]:
    """Split a ``capture_diff_for_witness`` blob into per-file chunks.

    Each chunk keeps its ``=== path ===`` header so the witness sees
    the same shape as the unsplit case.
    """
    if "=== " not in diff:
        return [diff]
    chunks: list[str] = []
    cur: list[str] = []
    for line in diff.splitlines(keepends=True):
        if line.startswith("=== ") and cur:
            chunks.append("".join(cur))
            cur = [line]
        else:
            cur.append(line)
    if cur:
        chunks.append("".join(cur))
    return chunks


# ── Entry point ───────────────────────────────────────────


ProviderResolver = Callable[[ProviderKind], Provider | None]


async def review_with_panel(
    task_text: str,
    diff: str,
    paths: list[str],
    panel: list[PanelMember],
    provider_resolver: ProviderResolver,
    *,
    charter_excerpts: str = "",
) -> list[tuple[str, WitnessVerdict]]:
    """Run ``panel`` over ``diff`` in parallel; return ``[(label, verdict)]``.

    When the diff exceeds the smallest panel member's window, the
    diff is split per-file and each member reviews all chunks; a
    member rejects iff ANY of its chunks rejects, approves iff ALL
    approve. The diff is never silently truncated — that masks the
    very issues this gate exists to catch.
    """
    if not panel or not paths or not diff.strip():
        return []

    chunks = [diff]
    if not diff_fits(diff, panel):
        chunks = split_by_file(diff)
        logger.info(
            "witness_panel: diff exceeds smallest member's window; "
            "split into %d per-file chunks for review",
            len(chunks),
        )

    async def _one_member(m: PanelMember) -> tuple[str, WitnessVerdict]:
        provider = provider_resolver(m.provider_kind)
        if provider is None:
            logger.warning(
                "witness_panel: provider %s unavailable; member %s "
                "defaults to approve",
                m.provider_kind.value, m.label,
            )
            return m.label, WitnessVerdict(
                approved=True,
                summary=f"{m.label}: provider unavailable",
            )
        chunk_verdicts: list[WitnessVerdict] = []
        for chunk_diff in chunks:
            v = await witness_code_change(
                task_text, chunk_diff, paths, provider,
                model_id=m.model_id,
                charter_excerpts=charter_excerpts,
            )
            chunk_verdicts.append(v)
        if any(not r.approved for r in chunk_verdicts):
            concerns: list[str] = []
            for r in chunk_verdicts:
                if not r.approved:
                    concerns.extend(r.concerns)
            return m.label, WitnessVerdict(
                approved=False,
                concerns=concerns[:5],
                summary=f"{m.label}: rejected ({len(chunks)} chunk(s))",
            )
        return m.label, WitnessVerdict(
            approved=True,
            summary=f"{m.label}: approved",
        )

    tasks = [_one_member(m) for m in panel]
    return list(await asyncio.gather(*tasks))
