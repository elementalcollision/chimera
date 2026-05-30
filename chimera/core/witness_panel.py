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
import re
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
    """``CHIMERA_WITNESS_VOTING`` env var. Default: ``majority``.

    History: the default was ``unanimous`` (v4.103) on the theory that
    foundational-code blast radius makes false-negative cost ≫ false-
    positive cost. The build soaks (v42/v43/v44) disproved the second
    half empirically: on CORRECT build diffs (tests green) a single
    idiosyncratic dissent among the 3-model panel rejected the diff and
    churned the soak — a recurring, real false-POSITIVE cost. The fix is
    ASYMMETRIC (see :func:`panel_decision`): the high-value class the
    unanimous rule actually protected — charter / security / scope
    crossings (e.g. the v13 RAW_ALLOWLIST expansion) — still rejects on
    ANY single dissent, while ordinary code-quality concerns now require
    a MAJORITY. So the default relaxes to ``majority`` without losing the
    catch unanimity was chosen for. Set ``CHIMERA_WITNESS_VOTING=unanimous``
    to restore the strict rule for a high-stakes run.
    """
    raw = os.environ.get("CHIMERA_WITNESS_VOTING", "majority").strip().lower()
    return raw if raw in {"unanimous", "majority"} else "majority"


# Charter / security / scope vocabulary. A dissent whose concern names
# one of these is treated as the high-value class the unanimous rule was
# built for (v13 RAW_ALLOWLIST, v14 "NOT on clear"): it rejects on ANY
# single dissent regardless of the numeric voting rule. Deliberately the
# security-leaning side of the line — matching here PRESERVES strictness,
# so erring broad is the safe direction. Ordinary code-quality nitpicks
# ("off-by-one", "missing docstring", "parens") match none of these and
# fall to the majority rule, which is the over-rejection this fix targets.
_CHARTER_CONCERN_MARKERS = re.compile(
    r"(?i)\b(?:charter|read-?only|allow-?list|deny-?list|MUST NOT|shall not|"
    r"out of scope|forbidden|sandbox|RAW_ALLOWLIST|security boundary|"
    r"privilege|threshold the|crosses)\b"
)


def _is_charter_concern(concern: str) -> bool:
    """True iff ``concern`` reads as a charter/security/scope crossing."""
    return bool(_CHARTER_CONCERN_MARKERS.search(concern or ""))


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


# Default panel POOL (v4.111): five members; ``build_witness_panel``
# picks ``panel_size()`` of them per call. Pool > panel_size so the
# active panel rotates across cycles (see ``seed`` arg below). Captured
# here rather than in tiers.json because the contract is "cross-provider
# witness for code review" and membership is tied to that contract, not
# to general tier routing.
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
    # v4.111 additions — operator-selected for additional gradient
    # diversity across soaks. Same OpenRouter provider kind; rotation
    # picks among them per cycle so any single model's idiosyncratic
    # bias gets averaged out.
    PanelMember(
        "openrouter:qwen-3.7-max", ProviderKind.OPENROUTER,
        "qwen/qwen3.7-max", context_tokens=1_000_000,
    ),
    PanelMember(
        "openrouter:glm-4.7", ProviderKind.OPENROUTER,
        "z-ai/glm-4.7", context_tokens=200_000,
    ),
)


def build_witness_panel(
    agent_provider_kind: ProviderKind,
    available: set[ProviderKind],
    *,
    size: int | None = None,
    require_diversity: bool | None = None,
    seed: int | None = None,
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
      - v4.111: when ``seed`` is supplied (typically the cycle index
        or a task-signature hash), the "others" pool is shuffled
        deterministically before picking. Pool size (5) exceeds
        default panel size (3), so seeded shuffling causes the
        active panel to rotate across cycles while remaining
        reproducible for a given seed. When ``seed`` is None, the
        original declaration order is preserved so unit tests and
        the v10/v13 fixture replays stay deterministic.
    """
    import random

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
    if seed is not None:
        random.Random(seed).shuffle(others)
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
    """Apply the (asymmetric) voting rule to ``verdicts``; True == approve.

    Empty panel approves (no signal). Otherwise:

      1. CHARTER OVERRIDE (always on, both rules): if ANY disapproving
         witness raises a charter/security/scope concern
         (:func:`_is_charter_concern`), the panel rejects — a single
         model spotting a threshold crossing (v13 RAW_ALLOWLIST, v14
         "NOT on clear") is decisive regardless of the count. This is the
         catch the unanimous default was actually chosen for.
      2. Otherwise the numeric rule applies. Default ``majority`` (reject
         only when MORE than half disapprove) — so a single idiosyncratic
         dissent on a CORRECT diff (the v42/v43/v44 over-rejection) no
         longer churns the soak. ``unanimous`` (opt-in) rejects on any
         dissent, charter or not.
    """
    rule = voting or voting_rule()
    vs = list(verdicts)
    if not vs:
        return True
    # Charter/security dissent is decisive on any single vote.
    for v in vs:
        if not v.approved and any(_is_charter_concern(c) for c in v.concerns):
            return False
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
