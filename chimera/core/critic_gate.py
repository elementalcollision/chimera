"""In-loop critic enforcement (ADR 0162) — the commit-time gate.

ADR 0160 built the internal critic and wired it as an *advisory* step. ADR 0162
promotes it to a *gate*: a commit must not land unless the critic adjudicates the
staged change faithful. This module is that gate, factored so the same logic
guards both commit paths (the agent's `git_commit` tool via the shell handler,
and the ADR 0148 autocommit fallback).

Design (see ADR 0162):

- **Verdict bound to the staged diff.** `chimera review` writes a verdict artifact
  keyed by the SHA-256 of `git diff --cached`. The gate accepts it ONLY if a
  matching-hash artifact exists and is APPROVED — the agent can *run* the
  reviewer but cannot forge its output, and a hash mismatch (diff changed since
  review) invalidates a stale verdict.
- **Authoritative fallback.** With no valid artifact, the gate reviews the staged
  diff itself (diff + docstrings; no faithfulness report — which the calibration
  showed the critic does not need: it caught every differential-blind near-miss
  on diff+docstring alone). The commit is never allowed on an unreviewed diff.
- **Reject-requires-confirmation.** A REJECT is not a hard stop: an independent
  second reviewer is consulted, and the commit is blocked ONLY if it also
  rejects. This absorbs the measured ~20% false-reject (incl. a clean fix the
  differential couldn't corroborate) without moving the 0% false-approve side.
- **Fail-closed.** An unparseable/errored verdict is NOT approval → it routes to
  the reject/escalate path, ending in a block-with-handoff, never a silent pass.
- **Off by default.** Enforcement runs only under `CHIMERA_CRITIC_ENFORCE=1`.
  `CHIMERA_ALLOW_CRITIC_REJECT=1` is the operator escape valve for a confirmed
  false-reject (single-use, operator-aware — mirrors the scope-check override).
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

from .critic import CriticVerdict

# A reviewer adjudicates a staged diff → a verdict. Injectable for tests; the
# default builds a real cross-model reviewer from the configured providers.
Reviewer = Callable[[str], Awaitable[CriticVerdict]]

_ARTIFACT_PREFIX = "critic-verdict-"
_ENFORCE_ENV = "CHIMERA_CRITIC_ENFORCE"
_OVERRIDE_ENV = "CHIMERA_ALLOW_CRITIC_REJECT"


@dataclass
class GateDecision:
    """The outcome of the commit-time critic gate."""

    allowed: bool
    source: str = ""               # disabled | empty-diff | override | artifact | recomputed
    reason: str = ""               # human-readable, surfaced to the agent on block
    verdict: CriticVerdict | None = None
    escalation: CriticVerdict | None = None
    diff_sha: str = ""
    escalated: bool = field(default=False)


# ── enforcement switches ─────────────────────────────────────────────


def enforce_enabled() -> bool:
    return os.environ.get(_ENFORCE_ENV) == "1"


def override_active() -> bool:
    return bool(os.environ.get(_OVERRIDE_ENV))


# ── staged diff + hashing ────────────────────────────────────────────


def staged_diff(repo_root: Path) -> str:
    """The staged index as a unified diff — exactly what will be committed, and
    exactly the snapshot the ADR 0146 scope check already inspects."""
    try:
        proc = subprocess.run(
            ["git", "diff", "--cached"], cwd=str(repo_root),
            capture_output=True, text=True, timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError):
        return ""
    return proc.stdout if proc.returncode == 0 else ""


def diff_sha(diff: str) -> str:
    return hashlib.sha256(diff.encode("utf-8")).hexdigest()


def staged_files(repo_root: Path) -> list[str]:
    """Paths in the staged index (for docstring extraction in the fallback)."""
    try:
        proc = subprocess.run(
            ["git", "diff", "--cached", "--name-only"], cwd=str(repo_root),
            capture_output=True, text=True, timeout=30,
        )
    except (subprocess.TimeoutExpired, OSError):
        return []
    if proc.returncode != 0:
        return []
    return [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]


# ── verdict artifact (hash-bound) ────────────────────────────────────


def _artifact_dir(repo_root: Path) -> Path:
    return repo_root / "state"


def artifact_path(repo_root: Path, sha: str) -> Path:
    return _artifact_dir(repo_root) / f"{_ARTIFACT_PREFIX}{sha}.json"


def write_verdict_artifact(
    repo_root: Path,
    diff: str,
    verdict: CriticVerdict,
    *,
    goal: str | None = None,
    model_id: str | None = None,
) -> Path:
    """Persist a verdict keyed by the staged-diff hash. Written by `chimera
    review` so the gate can accept it without recomputing — the binding to the
    diff hash is what makes it unforgeable and self-invalidating."""
    import json

    sha = diff_sha(diff)
    payload = {
        "diff_sha256": sha,
        "approved": bool(verdict.approved),
        "concerns": list(verdict.concerns),
        "rationale": verdict.rationale,
        "parsed": verdict.parsed,
        "goal": goal or "",
        "model_id": model_id or "",
    }
    d = _artifact_dir(repo_root)
    d.mkdir(parents=True, exist_ok=True)
    p = artifact_path(repo_root, sha)
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return p


def load_verdict_artifact(repo_root: Path, diff: str) -> CriticVerdict | None:
    """Load the verdict whose recorded hash matches the CURRENT staged diff.
    Returns None on absence, hash mismatch, or corruption — any of which means
    "no trustworthy verdict; recompute"."""
    import json

    sha = diff_sha(diff)
    p = artifact_path(repo_root, sha)
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError, OSError):
        return None
    if not isinstance(data, dict) or data.get("diff_sha256") != sha:
        return None
    if "approved" not in data:
        return None
    return CriticVerdict(
        approved=data.get("approved") is True,
        concerns=[str(c) for c in (data.get("concerns") or [])],
        rationale=str(data.get("rationale", "")),
        parsed=bool(data.get("parsed", True)),
    )


# ── the gate ─────────────────────────────────────────────────────────


def _block_reason(verdict: CriticVerdict, escalation: CriticVerdict | None) -> str:
    parts = [
        "git commit blocked by the in-loop critic gate (ADR 0162): the change "
        "was adjudicated NOT faithful.",
        f"  critic: {verdict.summary()}",
    ]
    if escalation is not None:
        parts.append(f"  second opinion (independent): {escalation.summary()}")
        parts.append("  Both reviewers rejected — this is very likely a real "
                     "regression. Address the concern (restore the behaviour or "
                     "pin it with a test), then re-commit.")
    else:
        parts.append("  No independent second opinion was available, so the "
                     "fail-closed default holds: needs human review.")
    parts.append("")
    parts.append("Override (operator-aware, single-use, for a CONFIRMED "
                 f"false-reject): export {_OVERRIDE_ENV}=1")
    return "\n".join(parts)


async def check_commit_critic(
    repo_root: Path,
    *,
    goal: str | None = None,
    reviewer: Reviewer | None = None,
    escalator: Reviewer | None = None,
) -> GateDecision:
    """Adjudicate the staged commit. Returns a :class:`GateDecision`; callers
    block the commit when ``allowed`` is False and surface ``reason``.

    ``reviewer``/``escalator`` are injectable (tests pass mocks); when omitted and
    enforcement is on, defaults are built from the configured providers.
    """
    if not enforce_enabled():
        return GateDecision(allowed=True, source="disabled")

    diff = staged_diff(repo_root)
    if not diff.strip():
        return GateDecision(allowed=True, source="empty-diff")
    sha = diff_sha(diff)

    if override_active():
        return GateDecision(
            allowed=True, source="override", diff_sha=sha,
            reason=f"{_OVERRIDE_ENV}=1 — operator overrode the critic gate.",
        )

    # 1. Trust a hash-matched APPROVED artifact; else recompute authoritatively.
    verdict = load_verdict_artifact(repo_root, diff)
    source = "artifact"
    if verdict is None or not verdict.parsed:
        if reviewer is None:
            reviewer = _default_reviewer(repo_root, goal)
        verdict = await reviewer(diff)
        source = "recomputed"

    if verdict.approved:
        return GateDecision(allowed=True, source=source, verdict=verdict, diff_sha=sha)

    # 2. Reject → require confirmation by an INDEPENDENT second reviewer.
    if escalator is None:
        escalator = _default_escalator(repo_root, goal)
    escalation = await escalator(diff) if escalator is not None else None
    if escalation is not None and escalation.approved:
        # A lone over-cautious reject, overruled — the false-reject rescue path.
        return GateDecision(
            allowed=True, source=source, verdict=verdict, escalation=escalation,
            diff_sha=sha, escalated=True,
            reason="critic rejected but an independent second opinion approved "
                   "(false-reject overruled).",
        )

    return GateDecision(
        allowed=False, source=source, verdict=verdict, escalation=escalation,
        diff_sha=sha, escalated=escalation is not None,
        reason=_block_reason(verdict, escalation),
    )


# ── default reviewers (real providers; not exercised by unit tests) ──


def _docstrings_for_staged(repo_root: Path) -> str:
    from chimera.cli import _function_docstrings  # lazy: avoid import cycle

    out: list[str] = []
    for rel in staged_files(repo_root):
        if not rel.endswith(".py"):
            continue
        try:
            src = (repo_root / rel).read_text(encoding="utf-8")
        except OSError:
            continue
        ds = _function_docstrings(src)
        if ds:
            out.append(ds)
    return "\n\n".join(out)


def _build_reviewer(repo_root: Path, goal: str | None, tier: str) -> Reviewer | None:
    """Build a reviewer at the given tier from the configured providers, or None
    if none is available (the gate treats None as 'no second opinion')."""
    from .critic import review_change

    try:
        from chimera.core import ChimeraLoop
        from chimera.providers.tiers import Provider as ProviderKind
        from chimera.providers.tiers import select_rung

        loop = ChimeraLoop()
        providers = loop._act.providers if loop._act is not None else {}
        if not providers:
            return None
        rung = select_rung(tier)
        provider = providers.get(rung.config.provider)
        if provider is None:
            return None
        model_id = (
            rung.config.model_id if rung.config.provider is ProviderKind.ANTHROPIC
            else rung.config.openrouter_model_id
        )
    except Exception:
        return None

    docstring = _docstrings_for_staged(repo_root)

    async def _review(diff: str) -> CriticVerdict:
        return await review_change(
            diff, provider=provider, model_id=model_id, goal=goal,
            docstring=docstring, faithfulness=None,
        )

    return _review


def _default_reviewer(repo_root: Path, goal: str | None) -> Reviewer:
    r = _build_reviewer(repo_root, goal, "sonnet")
    if r is not None:
        return r

    async def _unavailable(_diff: str) -> CriticVerdict:
        # Fail-closed: no provider ⇒ cannot adjudicate ⇒ not an approval.
        return CriticVerdict(
            False, ["critic gate: no provider available to review the commit"],
            parsed=False,
        )

    return _unavailable


def _default_escalator(repo_root: Path, goal: str | None) -> Reviewer | None:
    # Independent second opinion: a different tier (opus) for cross-checking a
    # reject. With a single provider this is a weaker independence than a
    # different vendor — disclosed in ADR 0162.
    return _build_reviewer(repo_root, goal, "opus")
