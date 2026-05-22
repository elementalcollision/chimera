"""Witness review for foundational code changes (v4.102, ADR 0106).

A semantic-correctness layer that runs at ACT completion AFTER the
parse-time `syntax_invalid` gate (v4.101). Where `py_compile` verifies
the file parses, a witness model READS the diff and asks the questions
a human reviewer would: does it match the task's intent, are there
obvious bugs, do parens/clauses match, does it follow the file's
existing conventions?

Defense in depth: across 10 soaks, every agent commit to chimera/*.py
shipped without a second model reading the diff. Soak v9 produced an
INBOX lie + untested act.py edit; soak v10 produced a structurally
invalid `return ActResult(...)` block that the runner spun on for 13
minutes. v4.101 catches v10; this catches both.

Scope: foundational code only. ``chimera/*.py`` and ``tests/*.py``,
excluding ``chimera/_version.py`` / ``chimera/__init__.py`` (no
semantics worth witnessing). ``mind/``, ``state/``, ``docs/`` writes
are intentionally skipped — the planner already proposes there and
witnessing every prose write would burn budget without catching the
class of bug this gate exists for.

Output contract: ``WitnessVerdict(approved, concerns, summary)``.
``approved=False`` populates ``ActResult.witness_concerns`` and
sets ``finish_reason="witness_rejected"``.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..providers import Provider
from ..providers.base import ChatMessage
from ..providers.tiers import MODEL_TIERS
from ..providers.tiers import Provider as ProviderKind

logger = logging.getLogger(__name__)


# ── Configuration ─────────────────────────────────────────


def witness_enabled() -> bool:
    """``CHIMERA_WITNESS_ENABLED`` env var. Default: enabled."""
    return os.environ.get("CHIMERA_WITNESS_ENABLED", "1").strip() not in {"0", "", "false", "False"}


def witness_tier() -> str:
    """``CHIMERA_WITNESS_TIER`` env var. Default: sonnet.

    Sonnet is the right floor: haiku misses too many structural and
    convention defects in soak v9/v10 manual replays; opus per-touch
    cost (~$0.15) is hard to justify at 2-5 witnessings/soak. Sonnet
    sits at ~$0.01-0.05/call.
    """
    return os.environ.get("CHIMERA_WITNESS_TIER", "sonnet").strip() or "sonnet"


# ── Verdict ───────────────────────────────────────────────


@dataclass
class WitnessVerdict:
    """Result of a single witness review pass.

    ``approved`` is the authoritative gate. ``concerns`` carries up to
    a handful of short-form lines for the remediation hint. ``summary``
    is a one-line description suitable for logs.
    """

    approved: bool
    concerns: list[str] = field(default_factory=list)
    summary: str = ""


# ── Scope ─────────────────────────────────────────────────

# Paths that look like foundational code but we explicitly do NOT
# witness — version bumps and import shim files are mechanical edits
# where review noise outweighs signal.
_WITNESS_EXCLUDE_EXACT: frozenset[str] = frozenset({
    "chimera/_version.py",
    "chimera/__init__.py",
})

_FOUNDATIONAL_PREFIXES: tuple[str, ...] = ("chimera/", "tests/")


def should_witness(write_targets: list[str]) -> list[str]:
    """Return the subset of ``write_targets`` that triggers witness review.

    A path qualifies when it ends in ``.py`` AND lives under one of the
    foundational roots AND is not in the explicit exclusion list. The
    return value is the actual file list a witness call would see;
    callers treat an empty list as "skip witness entirely".
    """
    out: list[str] = []
    for path in write_targets:
        if not path.endswith(".py"):
            continue
        if path in _WITNESS_EXCLUDE_EXACT:
            continue
        if not any(path.startswith(prefix) for prefix in _FOUNDATIONAL_PREFIXES):
            continue
        out.append(path)
    return out


# ── Diff capture ──────────────────────────────────────────


def capture_diff_for_witness(
    write_targets: list[str],
    *,
    worktree: Path | None = None,
    max_bytes: int = 64_000,
) -> str:
    """Return a unified-diff-shaped blob over ``write_targets`` vs HEAD.

    We do NOT shell out to ``git diff`` here. The ACT executor runs
    inside the active worktree on a long-running clone with potentially
    unstaged edits that aren't on a single SHA; reading the post-write
    file contents and rendering a synthetic ``--- HEAD\\n+++ working``
    block keeps the witness call deterministic and survives ``git``
    being unavailable in unit-test environments.

    The pre-image is the file's content at HEAD (via ``git show``) when
    available, falling back to empty (the file is new).
    """
    import subprocess

    root = worktree or Path.cwd()
    chunks: list[str] = []
    used = 0
    for path in write_targets:
        full = root / path
        try:
            post = full.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        try:
            r = subprocess.run(
                ["git", "show", f"HEAD:{path}"],
                cwd=str(root), capture_output=True, text=True, timeout=5,
            )
            pre = r.stdout if r.returncode == 0 else ""
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pre = ""
        block = (
            f"=== {path} ===\n"
            f"--- HEAD:{path}\n+++ working:{path}\n"
            f"# PRE ({len(pre)} bytes):\n{pre}\n"
            f"# POST ({len(post)} bytes):\n{post}\n"
        )
        if used + len(block) > max_bytes:
            chunks.append(f"=== {path} === [truncated: budget exhausted]\n")
            break
        chunks.append(block)
        used += len(block)
    return "".join(chunks)


# ── Prompt + parsing ──────────────────────────────────────


_WITNESS_SYSTEM_PROMPT = (
    "You are a code-review witness for the Chimera agent framework. "
    "Another agent just wrote a code change. Your job: read the diff, "
    "compare it against the task that motivated it, and decide whether "
    "the change is safe to ship to a long-running soak run.\n\n"
    "What to check:\n"
    "  1. STRUCTURAL SANITY — matched parens/brackets/braces, no dangling "
    "clauses (e.g. a `return foo(` interrupted by a dedented statement), "
    "indentation consistent within blocks. (`py_compile` already passed; "
    "you are catching things that parse but are structurally wrong.)\n"
    "  2. CORRECTNESS vs intent — does the change actually do what the "
    "task asked? Off-by-one errors, swapped operands, inverted "
    "conditions, missing edge cases the task named.\n"
    "  3. OBVIOUS BUGS — `len(x)` where `len(x)-1` is needed, mutation "
    "of an iterable while iterating, `==` vs `is` for non-singletons.\n"
    "  4. CONVENTIONS — if surrounding code uses type hints / docstrings "
    "/ a particular logger / a particular dataclass shape, the change "
    "should too. Don't flag stylistic preferences; flag clear breaks.\n\n"
    "What NOT to flag: speculative refactors, comment density, "
    "doc-comment phrasing, anything you'd write as \"could be nicer\"."
    "\n\nOutput format: a single JSON object on one line:\n"
    '  {"approved": <bool>, "concerns": [<short string>, ...], '
    '"summary": <one-line string>}\n\n'
    "`concerns` MUST be non-empty when approved=false and empty when "
    "approved=true. Each concern is one sentence, names the file, and "
    "either cites a line region or describes the structural defect "
    "concretely. Cap concerns at 5; the most important ones first."
)


def _build_user_prompt(task_text: str, diff: str, paths: list[str]) -> str:
    paths_block = ", ".join(f"`{p}`" for p in paths) or "(none)"
    return (
        f"## Task that motivated the change\n\n{task_text}\n\n"
        f"## Files written\n\n{paths_block}\n\n"
        f"## Diff (synthetic pre/post by file)\n\n{diff}\n\n"
        f"Reply with the JSON verdict only."
    )


_JSON_OBJECT_PATTERN = re.compile(r"\{.*\}", re.DOTALL)


def parse_verdict(text: str) -> WitnessVerdict:
    """Extract a ``WitnessVerdict`` from a witness reply.

    Tolerant of code fences and leading prose; we hunt for the first
    balanced JSON object. On any parse failure we approve — false
    rejection is worse than false approval because (a) the lower
    layers already filtered the catastrophic cases and (b) a witness
    that crashes shouldn't strand the agent.
    """
    if not text or not text.strip():
        return WitnessVerdict(approved=True, summary="empty witness reply; defaulted to approve")
    m = _JSON_OBJECT_PATTERN.search(text)
    if m is None:
        return WitnessVerdict(approved=True, summary="no JSON in witness reply; defaulted to approve")
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return WitnessVerdict(approved=True, summary="unparseable witness JSON; defaulted to approve")
    approved = bool(obj.get("approved", True))
    raw_concerns = obj.get("concerns", []) or []
    concerns = [str(c).strip() for c in raw_concerns if str(c).strip()][:5]
    summary = str(obj.get("summary", "")).strip()[:240]
    if not approved and not concerns:
        concerns = [summary or "witness rejected without specific concerns"]
    return WitnessVerdict(approved=approved, concerns=concerns, summary=summary)


# ── Entry point ───────────────────────────────────────────


def _resolve_tier(tier: str) -> tuple[str, ProviderKind]:
    """Return ``(model_id, provider_kind)`` for ``tier`` (haiku/sonnet/opus)."""
    cfg = MODEL_TIERS.get(tier) or MODEL_TIERS["sonnet"]
    return cfg.model_id, cfg.provider


async def witness_code_change(
    task_text: str,
    diff: str,
    paths: list[str],
    provider: Provider,
    tier: str | None = None,
    *,
    max_tokens: int = 1024,
) -> WitnessVerdict:
    """Ask ``provider`` to review the code change.

    The witness call uses ``provider.stream()`` because we want plain
    text out — no tools are needed. Caller is responsible for choosing
    the provider that matches the requested tier; the default
    ``ActExecutor`` plumbing supplies an ``AnthropicProvider``.

    Returns ``WitnessVerdict(approved=True, ...)`` on any unexpected
    error so a flaky provider never strands the agent.
    """
    if not paths:
        return WitnessVerdict(approved=True, summary="no foundational paths; skipped")
    if not diff.strip():
        return WitnessVerdict(approved=True, summary="empty diff; skipped")

    tier_name = tier or witness_tier()
    model_id, _provider_kind = _resolve_tier(tier_name)

    messages = [
        ChatMessage(role="user", content=_build_user_prompt(task_text, diff, paths)),
    ]

    pieces: list[str] = []
    try:
        async for chunk in provider.stream(
            messages,
            model_id=model_id,
            max_tokens=max_tokens,
            system=_WITNESS_SYSTEM_PROMPT,
        ):
            if chunk.text:
                pieces.append(chunk.text)
    except Exception:
        logger.exception("witness_code_change: provider call failed; defaulting to approve")
        return WitnessVerdict(approved=True, summary="witness provider error; defaulted to approve")

    return parse_verdict("".join(pieces))
