"""Tests for ADR 0186 B.4b/B.4c — trust-gated foreign DRAFT PR + approval gate.

Every gate is unit-tested via the ``submit_fn`` seam (no git/gh). Safety
invariants: the submit path is reached ONLY when every gate passes; it is always
called with ``draft=True`` + the foreign target; the first 5 foreign PRs need an
explicit per-PR approval grant; and the verify_cmd-review gate is fail-closed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chimera.core.foreign_pr_ledger import (
    count_foreign_prs_opened,
    record_foreign_pr_opened,
    record_verify_cmd_review,
)
from chimera.core.self_pr import (
    FOREIGN_PR_APPROVAL_FLOOR,
    _gate_approved_commit,
    _repo_allowed,
    maybe_foreign_pr,
)
from chimera.core.submit_pr import SubmitPrResult

REPO = "elementalcollision/claude-daemon"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Deterministic: clear every foreign-PR env knob (env-leakage hygiene)."""
    for k in ("CHIMERA_FOREIGN_PR", "CHIMERA_FOREIGN_PR_REQUIRE_APPROVAL",
              "CHIMERA_FOREIGN_PR_APPROVED", "CHIMERA_REPO_ALLOWLIST"):
        monkeypatch.delenv(k, raising=False)


def _spy(ok: bool = True):
    calls = []

    def fn(**kwargs):
        calls.append(kwargs)
        return SubmitPrResult(ok=ok, branch="chimera-soak/realtask-x",
                              pr_url="https://github.com/o/r/pull/1" if ok else None)

    fn.calls = calls
    return fn


def _trust(tmp_path: Path, tier: int) -> Path:
    p = tmp_path / "trust_state.json"
    p.write_text(json.dumps({"current_tier": tier}))
    return p


def _worktree_with_gate(tmp_path: Path, *, allowed: bool = True) -> Path:
    wt = tmp_path / "wt"
    (wt / "state").mkdir(parents=True, exist_ok=True)
    (wt / "state" / "critic-gate-log.jsonl").write_text(
        json.dumps({"allowed": allowed}) + "\n"
    )
    return wt


def _call(tmp_path, monkeypatch, *, spy=None, reviewed=True, **over):
    """Drive maybe_foreign_pr with all gates green unless overridden.

    Defaults are built ONLY when the test didn't override them (via pop) — the
    fixtures write to fixed paths, so building an unused default would clobber a
    test's override of the same path.
    """
    monkeypatch.setenv("CHIMERA_FOREIGN_PR", "1")
    state_dir = Path(over.pop("state_dir", None) or (tmp_path / "state"))
    state_dir.mkdir(exist_ok=True)
    foreign_repo = over.pop("foreign_repo", REPO)
    if reviewed:
        record_verify_cmd_review(state_dir, foreign_repo, ts="t0")
    worktree = over.pop("worktree", None) or _worktree_with_gate(tmp_path, allowed=True)
    trust_state_path = over.pop("trust_state_path", None) or _trust(tmp_path, 4)
    spy = spy or _spy()
    kw = dict(
        worktree=worktree,
        repo_root=tmp_path,
        foreign_repo=foreign_repo,
        foreign_base="main",
        verify_cmd="true",  # B.4e gate-approved: a trivially-passing verify_cmd
        state_dir=state_dir,
        trust_state_path=trust_state_path,
        submit_fn=spy,
    )
    kw.update(over)  # remaining: dry_run, run_id, foreign_base, verify_cmd
    return maybe_foreign_pr(**kw), spy


# ── gates (fail-closed) ─────────────────────────────────────


def test_skips_when_foreign_pr_env_off(tmp_path, monkeypatch):
    # Autouse cleared the flag; do NOT set it.
    spy = _spy()
    res = maybe_foreign_pr(
        worktree=_worktree_with_gate(tmp_path), repo_root=tmp_path,
        foreign_repo=REPO, trust_state_path=_trust(tmp_path, 5), submit_fn=spy,
    )
    assert not res.fired and "off by default" in res.skipped_reason
    assert spy.calls == []


def test_self_pr_flag_does_not_imply_foreign(tmp_path, monkeypatch):
    monkeypatch.setenv("CHIMERA_SELF_PR", "1")  # must NOT enable foreign
    spy = _spy()
    res = maybe_foreign_pr(
        worktree=_worktree_with_gate(tmp_path), repo_root=tmp_path,
        foreign_repo=REPO, trust_state_path=_trust(tmp_path, 5), submit_fn=spy,
    )
    assert not res.fired and spy.calls == []


def test_skips_when_repo_not_allowlisted(tmp_path, monkeypatch):
    res, spy = _call(tmp_path, monkeypatch, foreign_repo="evilcorp/malware")
    assert not res.fired and "not in CHIMERA_REPO_ALLOWLIST" in res.skipped_reason
    assert spy.calls == []


def test_skips_when_trust_below_t4(tmp_path, monkeypatch):
    res, spy = _call(tmp_path, monkeypatch, trust_state_path=_trust(tmp_path, 3))
    assert not res.fired and "foreign-PR floor" in res.skipped_reason
    assert spy.calls == []


def test_default_trust_reads_standing_state_dir_not_clone(tmp_path, monkeypatch):
    # B.4 RCA: with no explicit trust_state_path the gate reads STANDING trust
    # from state_dir, NOT the clone's per-run copy. Seed standing T5 + clone T0;
    # the clone copy must be IGNORED and the PR fire.
    monkeypatch.setenv("CHIMERA_FOREIGN_PR", "1")
    monkeypatch.setenv("CHIMERA_FOREIGN_PR_APPROVED", "1")
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "trust_state.json").write_text(json.dumps({"current_tier": 5}))
    wt = _worktree_with_gate(tmp_path, allowed=True)
    (wt / "state" / "trust_state.json").write_text(json.dumps({"current_tier": 0}))
    record_verify_cmd_review(state_dir, REPO, ts="t0")
    spy = _spy()
    res = maybe_foreign_pr(
        worktree=wt, repo_root=wt, foreign_repo=REPO, foreign_base="main",
        verify_cmd="true",
        state_dir=state_dir, submit_fn=spy)  # NO trust_state_path → default
    assert res.fired and len(spy.calls) == 1


def test_default_trust_standing_below_floor_skips(tmp_path, monkeypatch):
    # Standing trust < T4 still blocks (even if the clone copy were high).
    monkeypatch.setenv("CHIMERA_FOREIGN_PR", "1")
    monkeypatch.setenv("CHIMERA_FOREIGN_PR_APPROVED", "1")
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "trust_state.json").write_text(json.dumps({"current_tier": 3}))
    wt = _worktree_with_gate(tmp_path, allowed=True)
    record_verify_cmd_review(state_dir, REPO, ts="t0")
    spy = _spy()
    res = maybe_foreign_pr(
        worktree=wt, repo_root=wt, foreign_repo=REPO, state_dir=state_dir, submit_fn=spy)
    assert not res.fired and "foreign-PR floor" in res.skipped_reason


def test_skips_when_verify_cmd_fails(tmp_path, monkeypatch):
    # B.4e gate-approved: a RED verify_cmd at HEAD blocks the PR. (Approval granted
    # so we reach gate 6.)
    monkeypatch.setenv("CHIMERA_FOREIGN_PR_APPROVED", "1")
    res, spy = _call(tmp_path, monkeypatch, verify_cmd="false")
    assert not res.fired and "verify_cmd did not pass" in res.skipped_reason
    assert spy.calls == []


def test_skips_when_no_verify_cmd(tmp_path, monkeypatch):
    # Fail-closed: no verify_cmd means we cannot confirm the change → no PR.
    monkeypatch.setenv("CHIMERA_FOREIGN_PR_APPROVED", "1")
    res, spy = _call(tmp_path, monkeypatch, verify_cmd=None)
    assert not res.fired and "verify_cmd did not pass" in res.skipped_reason
    assert spy.calls == []


def test_skips_when_verify_cmd_not_reviewed(tmp_path, monkeypatch):
    res, spy = _call(tmp_path, monkeypatch, reviewed=False)
    assert not res.fired and "not operator-reviewed" in res.skipped_reason
    assert spy.calls == []


def test_verify_cmd_not_executed_until_reviewed(tmp_path, monkeypatch):
    # Gate ORDER (B.4e safety): the foreign verify_cmd must NOT be executed before
    # the review gate clears. Spy subprocess.run; an UNREVIEWED repo must skip at
    # the review gate WITHOUT ever running the verify_cmd.
    import chimera.core.self_pr as sp

    ran = []

    class _FakeProc:
        returncode = 0

    monkeypatch.setattr(sp.subprocess, "run",
                        lambda *a, **k: (ran.append(a) or _FakeProc()))
    monkeypatch.setenv("CHIMERA_FOREIGN_PR_APPROVED", "1")
    res, _ = _call(tmp_path, monkeypatch, reviewed=False, verify_cmd="true")
    assert not res.fired and "not operator-reviewed" in res.skipped_reason
    assert ran == []  # verify_cmd never executed — review gate short-circuited it


# ── approval gate (first 5) ─────────────────────────────────


def test_skips_when_approval_required_and_not_granted(tmp_path, monkeypatch):
    # REQUIRE_APPROVAL defaults ON; count 0 < 5; no grant → skip.
    res, spy = _call(tmp_path, monkeypatch)
    assert not res.fired and "needs operator approval" in res.skipped_reason
    assert "1/5" in res.skipped_reason
    assert spy.calls == []


def test_fires_when_approval_granted(tmp_path, monkeypatch):
    monkeypatch.setenv("CHIMERA_FOREIGN_PR_APPROVED", "1")
    res, spy = _call(tmp_path, monkeypatch)
    assert res.fired and res.submit.ok
    assert len(spy.calls) == 1
    call = spy.calls[0]
    assert call["foreign_repo"] == REPO
    assert call["draft"] is True
    assert call["foreign_base"] == "main"


def test_fires_when_approval_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("CHIMERA_FOREIGN_PR_REQUIRE_APPROVAL", "0")
    res, spy = _call(tmp_path, monkeypatch)  # no grant, but approval off
    assert res.fired and len(spy.calls) == 1


def test_regression_gate_blocks_submit(tmp_path, monkeypatch):
    # Gate 6.5 (B.4i): a pass-to-pass regression must block the PR. With
    # regression_cmd set and the no-regression check failing, submit never fires.
    monkeypatch.setenv("CHIMERA_FOREIGN_PR_APPROVED", "1")
    monkeypatch.setattr(
        "chimera.core.self_pr._foreign_no_regression", lambda *a, **k: False
    )
    res, spy = _call(tmp_path, monkeypatch, regression_cmd="pytest -q")
    assert not res.fired and "regression" in res.skipped_reason
    assert spy.calls == []


def test_regression_gate_inert_without_cmd(tmp_path, monkeypatch):
    # Default (no regression_cmd) → gate 6.5 is a no-op; behaviour unchanged.
    monkeypatch.setenv("CHIMERA_FOREIGN_PR_APPROVED", "1")
    res, spy = _call(tmp_path, monkeypatch)
    assert res.fired and len(spy.calls) == 1


def test_ignores_full_operational_footprint(tmp_path, monkeypatch):
    # Regression for the first claude-daemon dry run: validate()'s clean-tree gate
    # tripped on state/ + uv.lock (which an arbitrary foreign repo, unlike chimera,
    # does not .gitignore). The foreign path must tell validate to ignore its whole
    # operational footprint — not just mind/ as the self path does.
    monkeypatch.setenv("CHIMERA_FOREIGN_PR_APPROVED", "1")
    res, spy = _call(tmp_path, monkeypatch)
    assert res.fired
    ignored = set(spy.calls[0]["ignore_dirty_prefixes"])
    assert {"mind/", "state/", "uv.lock"} <= ignored


def test_approval_still_required_at_floor_minus_one(tmp_path, monkeypatch):
    # Boundary: exactly FLOOR-1 prior PRs → the next (FLOOR-th) STILL needs approval.
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    for i in range(FOREIGN_PR_APPROVAL_FLOOR - 1):
        record_foreign_pr_opened(state_dir, REPO, f"r{i}", ts=f"t{i}")
    res, spy = _call(tmp_path, monkeypatch, state_dir=state_dir)  # no grant
    assert not res.fired and "needs operator approval" in res.skipped_reason
    assert f"{FOREIGN_PR_APPROVAL_FLOOR}/{FOREIGN_PR_APPROVAL_FLOOR}" in res.skipped_reason
    assert spy.calls == []


def test_graduates_exactly_at_floor(tmp_path, monkeypatch):
    # Boundary: exactly FLOOR prior PRs → graduated, no grant needed.
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    for i in range(FOREIGN_PR_APPROVAL_FLOOR):
        record_foreign_pr_opened(state_dir, REPO, f"r{i}", ts=f"t{i}")
    res, spy = _call(tmp_path, monkeypatch, state_dir=state_dir)  # no grant
    assert res.fired and len(spy.calls) == 1


def test_records_foreign_pr_on_success(tmp_path, monkeypatch):
    monkeypatch.setenv("CHIMERA_FOREIGN_PR_APPROVED", "1")
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    assert count_foreign_prs_opened(state_dir) == 0
    res, _ = _call(tmp_path, monkeypatch, state_dir=state_dir, run_id="run-42")
    assert res.fired
    assert count_foreign_prs_opened(state_dir) == 1


def test_does_not_record_on_submit_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("CHIMERA_FOREIGN_PR_APPROVED", "1")
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    res, _ = _call(tmp_path, monkeypatch, state_dir=state_dir, spy=_spy(ok=False))
    assert res.fired and not res.submit.ok
    assert count_foreign_prs_opened(state_dir) == 0  # failed PR not counted


def test_dry_run_does_not_record(tmp_path, monkeypatch):
    monkeypatch.setenv("CHIMERA_FOREIGN_PR_APPROVED", "1")
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    res, spy = _call(tmp_path, monkeypatch, state_dir=state_dir, dry_run=True)
    assert res.fired
    assert spy.calls[0]["dry_run"] is True
    assert count_foreign_prs_opened(state_dir) == 0


# ── _repo_allowed: malformed-repo rejection (B.4 review #5) ──


def test_repo_allowed_accepts_well_formed_allowlisted():
    # autouse _clean_env unsets CHIMERA_REPO_ALLOWLIST → default 'elementalcollision'.
    assert _repo_allowed("elementalcollision/claude-daemon")


@pytest.mark.parametrize("bad", [
    "elementalcollision/../evil",      # path traversal (two slashes)
    "elementalcollision/",             # empty name
    "/claude-daemon",                  # empty owner
    "elementalcollision/re po",        # space
    "elementalcollision/a/b",          # extra slash
    "noslash",                         # no slash at all
    "",                                # empty
    "elementalcollision/x;rm -rf",     # shell metachars
])
def test_repo_allowed_rejects_malformed(bad):
    # Even an allowlisted OWNER must not rescue a malformed name (it flows into
    # the push URL / gh --repo).
    assert not _repo_allowed(bad)


def test_repo_allowed_rejects_non_allowlisted_owner():
    assert not _repo_allowed("evilcorp/malware")


# ── _gate_approved_commit: fail-closed edge cases (B.4 review #4) ──


def _gate_log(tmp_path: Path, content: str) -> Path:
    wt = tmp_path / "gw"
    (wt / "state").mkdir(parents=True)
    (wt / "state" / "critic-gate-log.jsonl").write_text(content)
    return wt


def test_gate_approved_missing_log(tmp_path):
    assert _gate_approved_commit(tmp_path / "nope") is False


@pytest.mark.parametrize("content", [
    "",                                       # empty file
    "   \n  \n",                              # whitespace only
    "not json\n",                            # malformed line
    json.dumps({"escalated": True}) + "\n",  # missing "allowed" key
    json.dumps({"allowed": False}) + "\n",   # explicitly blocked
    json.dumps({"allowed": None}) + "\n",    # null
    json.dumps({"allowed": "yes"}) + "\n",   # truthy-but-not-True
])
def test_gate_approved_fail_closed(tmp_path, content):
    assert _gate_approved_commit(_gate_log(tmp_path, content)) is False


def test_gate_approved_true_only_when_last_allowed_true(tmp_path):
    log = (
        json.dumps({"allowed": False}) + "\n"
        + json.dumps({"allowed": True}) + "\n"  # LAST line wins
    )
    assert _gate_approved_commit(_gate_log(tmp_path, log)) is True
