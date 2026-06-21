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
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from chimera.config import flag_enabled
from chimera.trust import TrustManager, TrustTier

from .foreign_pr_ledger import (
    count_foreign_prs_opened,
    is_verify_cmd_reviewed,
    record_foreign_pr_opened,
)
from .repo_verify import _gate_subprocess_env
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

# Operational footprint the soak/runtime writes INTO a foreign clone but which is
# never part of a foreign PR — so it must not trip submit_pr.validate()'s
# clean-tree gate (ADR 0186, dirty-tree gap caught by the first claude-daemon
# dry run). The self path only needs "mind/" because chimera's own .gitignore
# already covers state/ and the venv; an arbitrary foreign repo does NOT, so the
# foreign path must ignore its full footprint explicitly:
#   mind/    — the soak's agent journal (INBOX/HEARTBEAT/SESSION_LOG/research/soak)
#   state/   — the agent's CHIMERA_STATE_DIR (trust_state.json, chimera.db, crawl/)
#   uv.lock  — mutated as a side-effect of `uv run` (agent + verify_cmd resolve)
# The autocommit stages ONLY $TASK_FILES (B.4e: `git add -- $TASK_FILES`), so the
# PR carries the allowlisted change alone; this gate just stops the operational
# residue left UNCOMMITTED alongside it from reading as "dirty worktree".
_FOREIGN_IGNORE_DIRTY = ("mind/", "state/", "uv.lock")


# Strict GitHub "owner/name" shape — rejects path-traversal / injection in the
# repo string before it ever reaches the push URL or `gh --repo` (B.4 review).
_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def _repo_allowed(repo: str) -> bool:
    """True iff ``repo`` (owner/name) is well-formed AND in CHIMERA_REPO_ALLOWLIST
    — an entry is a bare owner or a full owner/name (mirrors real_task_soak.sh).
    Fail-closed: a malformed repo (e.g. ``owner/../evil``) is refused even if its
    owner is allowlisted, since the string flows into the push URL / gh --repo."""
    if not _REPO_RE.match(repo):
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


def _foreign_gate_approved(worktree: Path, verify_cmd: str | None) -> bool:
    """Foreign 'gate-approved' signal (ADR 0186 B.4e): the target repo's OWN
    ``verify_cmd`` passes at HEAD, run with provider secrets stripped (B.4a M1).

    Replaces self-PR's chimera critic-gate-log check — a foreign repo never writes
    that log, and its own gate command is the authoritative quality signal. The
    committed change is at HEAD, so a green ``verify_cmd`` confirms the PR's content
    is good. Fail-closed: no ``verify_cmd``, or any non-zero exit / error / timeout
    → False (no PR)."""
    if not verify_cmd or not verify_cmd.strip():
        return False  # empty/whitespace-only → cannot confirm → fail-closed
    try:
        proc = subprocess.run(
            verify_cmd, shell=True, cwd=str(worktree),
            capture_output=True, text=True, timeout=900,
            env=_gate_subprocess_env(),
        )
    except (subprocess.SubprocessError, OSError):
        return False
    return proc.returncode == 0


def _git_current_ref(worktree: Path) -> str | None:
    """The current branch name, or the commit SHA on detached HEAD (the
    ``rev-parse HEAD`` fallback) — for restoring the worktree after the dance.
    Returns None only on a git error, never merely because HEAD is detached."""
    for args in (("rev-parse", "--abbrev-ref", "HEAD"), ("rev-parse", "HEAD")):
        try:
            p = subprocess.run(["git", *args], cwd=str(worktree),
                               capture_output=True, text=True, timeout=30)
        except (subprocess.SubprocessError, OSError):
            return None
        ref = p.stdout.strip()
        if p.returncode == 0 and ref and ref != "HEAD":
            return ref
    return None


def _git_checkout(worktree: Path, ref: str) -> int | None:
    """Force-checkout ``ref`` via an ARGV git call (no shell — ``ref`` is never
    shell-interpolated). Force discards the prior gate run's non-PR drift
    (pytest/uv caches, uv.lock) that would otherwise block the checkout; the PR
    content is committed, so nothing real is lost. Returns the exit code, or None
    on error/timeout."""
    try:
        p = subprocess.run(["git", "checkout", "-q", "-f", ref], cwd=str(worktree),
                           capture_output=True, text=True, timeout=60)
    except (subprocess.SubprocessError, OSError):
        return None
    return p.returncode


def _run_gate_cmd(worktree: Path, cmd: str) -> int | None:
    """Run a sandboxed gate command in ``worktree``; return its exit code, or None
    on error/timeout (secrets stripped, B.4a)."""
    try:
        proc = subprocess.run(
            cmd, shell=True, cwd=str(worktree), capture_output=True, text=True,
            timeout=1800, env=_gate_subprocess_env(),
        )
    except (subprocess.SubprocessError, OSError):
        return None
    return proc.returncode


def _foreign_no_regression(
    worktree: Path, base: str, regression_cmd: str | None
) -> bool:
    """No pass-to-pass regression (ADR 0186 B.4i, adopted from Phoenix 2606.20243):
    if ``regression_cmd`` (the target's BROADER suite) is GREEN on ``base``, it must
    stay GREEN at HEAD (the agent's commit). This catches a change that edits source
    and silently breaks a previously-passing test — which the SCOPED verify_cmd gate
    (B.4e) never runs and so cannot see.

    Returns True (proceed) when: no ``regression_cmd`` is configured (opt-in — the
    common additive-test task can't regress), OR the suite is already RED on base
    (no green baseline to protect — warn, don't block on a pre-existing failure).
    Returns False (block) only when base was GREEN and HEAD is RED. Fail-OPEN on a
    harness error (None exit / lost ref): a flaky-infra false block is worse than
    leaning on B.4e + the draft + B.4g; the regression gate is additive assurance,
    not a primary safety boundary. ALWAYS restores the worktree to its original ref."""
    if not regression_cmd or not regression_cmd.strip():
        return True
    orig = _git_current_ref(worktree)
    if orig is None:
        return True  # git error (NOT detached HEAD) → skip rather than risk the tree
    try:
        if _git_checkout(worktree, base) != 0:
            return True  # base unavailable → no baseline
        base_rc = _run_gate_cmd(worktree, regression_cmd)
        if base_rc != 0:
            return True  # base already red (or errored) → no green baseline to protect
        if _git_checkout(worktree, orig) != 0:
            return True  # couldn't return to HEAD → skip (finally still restores)
        head_rc = _run_gate_cmd(worktree, regression_cmd)
        if head_rc is None:
            return True  # harness/timeout error at HEAD → fail-open (additive gate)
        return head_rc == 0  # regression iff base GREEN but HEAD RED
    finally:
        _git_checkout(worktree, orig)  # ALWAYS restore the worktree to its branch


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
    #    Registry-backed read (ADR 0176) — honours the bool contract, matching
    #    maybe_foreign_pr; identical to the old != "1" check for unset/"1".
    if not flag_enabled(SELF_PR_ENV):
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
    verify_cmd: str | None = None,
    regression_cmd: str | None = None,
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
    T4. ``state_dir`` holds the governance ledger AND the standing-trust source
    (default ``repo_root/state``).

    Trust source (2026-06-20, B.4 scope_evasion RCA): the gate reads the operator's
    STANDING trust from ``state_dir`` — NOT the throwaway clone's per-run trust.
    A foreign soak runs ``chimera run`` in the clone, which mutates the clone's
    trust copy (a single in-run ``scope_evasion`` demotes it 2 tiers); that copy is
    discarded with the clone, so gating on it would let one noisy ACT cycle block
    an otherwise-clean PR. Gating on standing trust is safe because the PR content
    is independently bounded: the foreign autocommit commits ONLY the allowlist
    (``git add -- $TASK_FILES``), and the gate-pass + critic-commit + verify-review
    + first-5 approval gates still apply. Per-run trust stays the self-loop's
    learning signal; it is not the foreign-PR decision.
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

    # 3. Trust gate — STANDING trust (state_dir), not the clone's per-run copy
    #    (see the docstring's "Trust source" note). Must have earned T4+ (ADAPTIVE).
    tsp = Path(trust_state_path) if trust_state_path else state_dir / "trust_state.json"
    tier = TrustManager(tsp).tier
    if tier.value < MIN_TIER.value:
        return SelfPrResult(
            skipped_reason=f"trust tier {tier.name} < {MIN_TIER.name} (foreign-PR floor)"
        )

    # 4. verify_cmd review (B.4c/M4) — the target's gate must be operator-reviewed
    #    for network/secrets/arbitrary-download risk. This MUST precede gate 6,
    #    which actually RUNS the verify_cmd — never execute unreviewed foreign code.
    if not is_verify_cmd_reviewed(state_dir, foreign_repo):
        return SelfPrResult(
            skipped_reason=f"verify_cmd for {foreign_repo!r} not operator-reviewed "
            "(ADR 0186 B.4c) — record a review before opening a foreign PR"
        )

    # 5. First-N approval gate (B.4c/M4) — the first FOREIGN_PR_APPROVAL_FLOOR
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

    # 6. Gate-approved (foreign, B.4e) — the target's OWN verify_cmd must pass at
    #    HEAD (sandboxed, secrets stripped). Runs ONLY after the review (4) confirmed
    #    it is safe to execute and approval (5) cleared. A foreign repo never writes
    #    the chimera critic-gate log, so the verify_cmd is the authoritative quality
    #    signal that the committed change is good.
    if not _foreign_gate_approved(worktree, verify_cmd):
        return SelfPrResult(
            skipped_reason="foreign verify_cmd did not pass at HEAD (or --verify-cmd "
            "missing) — cannot confirm the change is good"
        )

    # 6.5 No pass-to-pass regression (B.4i, Phoenix) — if a broader regression_cmd
    #     is configured and was GREEN on base, it must stay GREEN at HEAD. Catches a
    #     source edit that breaks a previously-passing test (the scoped verify_cmd
    #     above never runs it). Opt-in; runs AFTER the cheap scoped gate so we don't
    #     pay for the broad suite when the scoped gate already failed.
    if not _foreign_no_regression(worktree, foreign_base, regression_cmd):
        return SelfPrResult(
            skipped_reason="foreign regression_cmd was GREEN on base but RED at HEAD "
            "— the change broke a previously-passing test (pass-to-pass regression)"
        )

    # 7. Delegate to the SAME validated submit path — DRAFT, never merge — but
    #    targeting the foreign remote.
    sub = submit_fn(
        worktree=worktree,
        repo_root=repo_root,
        base=foreign_base,
        draft=True,
        dry_run=dry_run,
        ignore_dirty_prefixes=_FOREIGN_IGNORE_DIRTY,
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
