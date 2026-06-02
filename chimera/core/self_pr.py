"""ADR 0163 — trust-gated autonomous self-PR (the autonomy ladder's next rung).

ADR 0102 made PR submission OPERATOR-invoked on purpose: the agent never holds
push credentials, and a human runs `chimera submit-pr` after review. This module
adds the *autonomous* rung on top of that machinery — Chimera proposes its own PR
when it has earned the trust — without weakening the threat model:

- **Off by default.** Fires only under explicit opt-in (`CHIMERA_SELF_PR=1`).
  Launching a self-PR-enabled soak stays a deliberate operator action.
- **Trust-gated.** Only at tier T4 (ADAPTIVE) or above — the agent must have
  earned broad autonomy first (ADR 0008 trust ladder).
- **Gate-gated.** Only when the worktree carries a commit the in-loop critic gate
  ALLOWED (ADR 0162) — a self-PR can only ever propose a change the safety floor
  already approved.
- **Reuses `submit_pr.validate()`.** Same secret-path / fix-without-test /
  runtime-pytest re-validation as the operator verb — no weaker path to a PR.
- **DRAFT only, never merges.** Opens a draft PR for human review. Nothing lands
  without a human marking it ready AND merging. The autonomy is "propose," not
  "ship."

This is strictly additive: with the env unset (the default), `maybe_self_pr` is a
no-op and behaviour is exactly the manual-handoff status quo.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from chimera.trust import TrustManager, TrustTier

from .submit_pr import SubmitPrResult, submit_pr

SELF_PR_ENV = "CHIMERA_SELF_PR"
# Balanced envelope (operator-selected 2026-06-02): T4 ADAPTIVE+, draft PR.
MIN_TIER = TrustTier.T4


@dataclass
class SelfPrResult:
    """Outcome of a self-PR attempt. ``fired`` means all gates passed and the
    (draft) submit path ran; ``submit`` carries that path's result."""

    fired: bool = False
    skipped_reason: str = ""
    submit: SubmitPrResult | None = None

    def to_dict(self) -> dict:
        return {
            "fired": self.fired,
            "skipped_reason": self.skipped_reason,
            "submit_ok": (self.submit.ok if self.submit else None),
            "branch": (self.submit.branch if self.submit else ""),
        }


def _gate_approved_commit(worktree: Path) -> bool:
    """True iff the worktree's LAST in-loop critic-gate decision allowed a commit
    (ADR 0162 ``critic-gate-log.jsonl``). A self-PR may only propose a change the
    gate already approved — fail-closed on a missing/unreadable/empty log."""
    log = worktree / "state" / "critic-gate-log.jsonl"
    try:
        lines = [ln for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()]
    except OSError:
        return False
    if not lines:
        return False
    try:
        last = json.loads(lines[-1])
    except (json.JSONDecodeError, ValueError):
        return False
    return last.get("allowed") is True


def maybe_self_pr(
    *,
    worktree: Path | str,
    repo_root: Path | str,
    base: str = "main",
    trust_state_path: Path | str | None = None,
    dry_run: bool = False,
    submit_fn=None,
    gh_runner=None,
    push_runner=None,
) -> SelfPrResult:
    """Open a trust-gated DRAFT self-PR — or no-op with a reason.

    Fail-closed at every gate. ``submit_fn`` is a seam for tests (defaults to the
    real :func:`submit_pr`); ``gh_runner``/``push_runner`` forward to it.
    """
    worktree = Path(worktree)
    repo_root = Path(repo_root)
    submit_fn = submit_fn or submit_pr

    # 1. Opt-in. Default behaviour = manual-handoff status quo (no-op).
    if os.environ.get(SELF_PR_ENV) != "1":
        return SelfPrResult(skipped_reason=f"{SELF_PR_ENV} != 1 (off by default)")

    # 2. Trust gate — must have earned T4+ (ADAPTIVE).
    tsp = Path(trust_state_path) if trust_state_path else repo_root / "state" / "trust_state.json"
    tier = TrustManager(tsp).tier
    if tier.value < MIN_TIER.value:
        return SelfPrResult(
            skipped_reason=f"trust tier {tier.name} < {MIN_TIER.name} (self-PR floor)"
        )

    # 3. Gate gate — only propose what the in-loop critic gate already allowed.
    if not _gate_approved_commit(worktree):
        return SelfPrResult(
            skipped_reason="no gate-approved commit in worktree (ADR 0162 log)"
        )

    # 4. Delegate to the SAME validated submit path the operator verb uses —
    #    DRAFT, never merge. validate() re-runs the secret/test/honesty gates.
    sub = submit_fn(
        worktree=worktree,
        repo_root=repo_root,
        base=base,
        draft=True,
        dry_run=dry_run,
        # mind/* is the soak's operational journal (heartbeat/inbox/session),
        # written after the agent's commit and never part of the PR — must not
        # block an otherwise-clean self-PR.
        ignore_dirty_prefixes=("mind/",),
        gh_runner=gh_runner,
        push_runner=push_runner,
    )
    return SelfPrResult(fired=True, submit=sub)
