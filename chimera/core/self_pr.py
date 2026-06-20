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

from chimera.config import flag_enabled
from chimera.trust import TrustManager, TrustTier

from .foreign_pr_ledger import (
    count_foreign_prs_opened,
    is_verify_cmd_reviewed,
    record_foreign_pr_opened,
)
from .submit_pr import SubmitPrResult, submit_pr

SELF_PR_ENV = "CHIMERA_SELF_PR"
# Balanced envelope (operator-selected 2026-06-02): T4 ADAPTIVE+, draft PR.
MIN_TIER = TrustTier.T4

# ADR 0186 B.4: foreign-PR opt-in / approval flags + the first-N approval bound.
FOREIGN_PR_ENV = "CHIMERA_FOREIGN_PR"
FOREIGN_PR_APPROVAL_FLAG = "CHIMERA_FOREIGN_PR_REQUIRE_APPROVAL"
FOREIGN_PR_APPROVED_ENV = "CHIMERA_FOREIGN_PR_APPROVED"
FOREIGN_PR_APPROVAL_FLOOR = 5
# Operational default allowlist (mirrors real_task_soak.sh); fail-closed.
_DEFAULT_ALLOWLIST = "elementalcollision"


def _repo_allowed(repo: str) -> bool:
    """True iff ``repo`` (owner/name) is in CHIMERA_REPO_ALLOWLIST — an entry is a
    bare owner or a full owner/name (mirrors real_task_soak.sh). Fail-closed."""
    if "/" not in repo:
        return False
    raw = os.environ.get("CHIMERA_REPO_ALLOWLIST") or _DEFAULT_ALLOWLIST
    owner = repo.split("/", 1)[0]
    entries = {e for e in raw.replace(",", " ").split() if e}
    return repo in entries or owner in entries


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


def maybe_foreign_pr(
    *,
    worktree: Path | str,
    repo_root: Path | str,
    foreign_repo: str,
    foreign_base: str = "main",
    run_id: str = "",
    state_dir: Path | str | None = None,
    trust_state_path: Path | str | None = None,
    dry_run: bool = False,
    submit_fn=None,
    gh_runner=None,
    push_runner=None,
) -> SelfPrResult:
    """Open a trust-gated DRAFT PR against a FOREIGN repo — or no-op with a reason
    (ADR 0186 B.4b/B.4c). Fail-closed at every gate; DRAFT-only, never merges.

    Distinct from :func:`maybe_self_pr` so the self path stays byte-identical:
    the foreign path has its own opt-in (``CHIMERA_FOREIGN_PR``, never implied by
    ``CHIMERA_SELF_PR``) plus two extra safety gates — the target's ``verify_cmd``
    must be operator-reviewed, and the first ``FOREIGN_PR_APPROVAL_FLOOR`` foreign
    PRs need explicit per-PR approval (``CHIMERA_FOREIGN_PR_APPROVED=1``) even at
    T4. ``state_dir`` holds the governance ledger (default ``repo_root/state``).
    """
    worktree = Path(worktree)
    repo_root = Path(repo_root)
    state_dir = Path(state_dir) if state_dir else repo_root / "state"
    submit_fn = submit_fn or submit_pr

    # 1. Opt-in — SEPARATE from CHIMERA_SELF_PR, never implied by it.
    if not flag_enabled(FOREIGN_PR_ENV):
        return SelfPrResult(skipped_reason=f"{FOREIGN_PR_ENV} != 1 (off by default)")

    # 2. Allowlist (defense-in-depth — also enforced shell-side pre-clone, B.2/M3).
    if not _repo_allowed(foreign_repo):
        return SelfPrResult(
            skipped_reason=f"repo {foreign_repo!r} not in CHIMERA_REPO_ALLOWLIST"
        )

    # 3. Trust gate — must have earned T4+ (ADAPTIVE), same floor as self-PR.
    tsp = Path(trust_state_path) if trust_state_path else repo_root / "state" / "trust_state.json"
    tier = TrustManager(tsp).tier
    if tier.value < MIN_TIER.value:
        return SelfPrResult(
            skipped_reason=f"trust tier {tier.name} < {MIN_TIER.name} (foreign-PR floor)"
        )

    # 4. Gate gate — only propose what the in-loop critic gate already allowed.
    if not _gate_approved_commit(worktree):
        return SelfPrResult(
            skipped_reason="no gate-approved commit in worktree (ADR 0162 log)"
        )

    # 5. verify_cmd review (B.4c/M4) — the target's gate must be operator-reviewed
    #    for network/secrets/arbitrary-download risk BEFORE we run-and-PR it.
    if not is_verify_cmd_reviewed(state_dir, foreign_repo):
        return SelfPrResult(
            skipped_reason=f"verify_cmd for {foreign_repo!r} not operator-reviewed "
            "(ADR 0186 B.4c) — record a review before opening a foreign PR"
        )

    # 6. First-N approval gate (B.4c/M4) — the first FOREIGN_PR_APPROVAL_FLOOR
    #    foreign PRs need an explicit per-PR operator grant even at T4; graduates
    #    after a clean track record.
    if flag_enabled(FOREIGN_PR_APPROVAL_FLAG):
        opened = count_foreign_prs_opened(state_dir)
        if opened < FOREIGN_PR_APPROVAL_FLOOR and not flag_enabled(FOREIGN_PR_APPROVED_ENV):
            return SelfPrResult(
                skipped_reason=(
                    f"foreign PR {opened + 1}/{FOREIGN_PR_APPROVAL_FLOOR} needs "
                    f"operator approval (set {FOREIGN_PR_APPROVED_ENV}=1)"
                )
            )

    # 7. Delegate to the SAME validated submit path — DRAFT, never merge — but
    #    targeting the foreign remote.
    sub = submit_fn(
        worktree=worktree,
        repo_root=repo_root,
        base=foreign_base,
        draft=True,
        dry_run=dry_run,
        ignore_dirty_prefixes=("mind/",),
        foreign_repo=foreign_repo,
        foreign_base=foreign_base,
        gh_runner=gh_runner,
        push_runner=push_runner,
    )

    # 8. Record a successfully-opened foreign PR (fail-soft) so the approval gate
    #    can count the track record. Only on a real (non-dry-run) success.
    if sub is not None and sub.ok and not dry_run:
        try:
            record_foreign_pr_opened(
                state_dir, foreign_repo, run_id or sub.branch,
                pr_url=getattr(sub, "pr_url", None),
            )
        except OSError:
            pass  # instrumentation must never break a successful PR
    return SelfPrResult(fired=True, submit=sub)
