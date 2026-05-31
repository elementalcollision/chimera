"""B1 W1 (ADR 0158): the phase-1 build-completion gate.

`check_verify_claim_invalid` ground-truths a "make the change and prove
`chimera verify` is green" task by RE-RUNNING the runner-configured verify
command — so an agent cannot mark the build complete while the gate is still
red (the W1 over-claim: sub-10ms no-op tool calls, file never edited, yet
self-reported done). Symmetric to check_test_claim_valid / check_commit_not_
executed: trust the ground truth, not the self-report.
"""

from __future__ import annotations

from chimera.core.act import (
    _task_demands_verify_green,
    check_verify_claim_invalid,
)

_BUILD_TASK = (
    "**Make the change and prove `chimera verify` is green.** Edit ONLY the "
    "files in SCOPE below. Run `uv run chimera verify --ruff chimera/x.py "
    "--test tests/test_x.py` and keep fixing until it exits 0 (`PASS`)."
)


# ── _task_demands_verify_green ───────────────────────────────────────


def test_demands_matches_the_real_phase1_build_task():
    assert _task_demands_verify_green(_BUILD_TASK)


def test_demands_does_not_match_do_not_commit_task():
    assert not _task_demands_verify_green(
        "Do NOT commit in phase 1 (engines are off). The runner commits in "
        "phase 2."
    )


def test_demands_empty_is_false():
    assert not _task_demands_verify_green("")


# ── soak/env scoping (no-op off-soak or unconfigured) ────────────────


def test_no_op_when_worktree_root_none(tmp_path):
    # off-soak: scan root is None → never fires even with a red gate + cmd
    assert check_verify_claim_invalid(_BUILD_TASK, None, verify_cmd="false") == []


def test_no_op_when_no_verify_cmd(tmp_path, monkeypatch):
    monkeypatch.delenv("CHIMERA_PHASE1_VERIFY_CMD", raising=False)
    assert check_verify_claim_invalid(_BUILD_TASK, tmp_path, verify_cmd=None) == []


def test_no_op_when_task_does_not_demand_verify(tmp_path):
    assert check_verify_claim_invalid(
        "Commit the change with git_commit.", tmp_path, verify_cmd="false",
    ) == []


# ── the gate itself: ground-truth the claim ──────────────────────────


def test_fires_when_gate_is_red(tmp_path):
    reasons = check_verify_claim_invalid(_BUILD_TASK, tmp_path, verify_cmd="false")
    assert len(reasons) == 1
    assert "not done" in reasons[0]
    assert "false" in reasons[0]


def test_passes_when_gate_is_green(tmp_path):
    assert check_verify_claim_invalid(_BUILD_TASK, tmp_path, verify_cmd="true") == []


def test_env_var_supplies_the_command(tmp_path, monkeypatch):
    monkeypatch.setenv("CHIMERA_PHASE1_VERIFY_CMD", "false")
    reasons = check_verify_claim_invalid(_BUILD_TASK, tmp_path)
    assert reasons and "not done" in reasons[0]


def test_unrunnable_command_counts_as_red(tmp_path):
    # `bash -c <missing>` starts bash and exits 127 — a non-zero gate, so the
    # claim is invalid (treated as red, the safe direction). Fail-open ([])
    # is reserved for bash itself being unstartable (OSError), not for a
    # command that runs and fails.
    reasons = check_verify_claim_invalid(
        _BUILD_TASK, tmp_path, verify_cmd="this-prog-does-not-exist-xyz",
    )
    assert reasons and "127" in reasons[0]
