"""Tests for chimera.core.doctor (v3.6)."""

from __future__ import annotations

from pathlib import Path

import pytest

from chimera.core import ConfigError, assert_no_errors, run_checks


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("CHIMERA_MIND_DIR", str(tmp_path / "mind"))
    for env in (
        "CHIMERA_MCP_SERVERS",
        "CHIMERA_PEER_TOKENS",
        "CHIMERA_PEER_TOKEN",
        "ANTHROPIC_API_KEY",
        "OPENROUTER_API_KEY",
    ):
        monkeypatch.delenv(env, raising=False)


def _by_name(results, name):
    return next(r for r in results if r.name == name)


def test_run_checks_returns_ok_for_default_local_dev():
    results = run_checks()
    assert _by_name(results, "state_dir").status == "ok"
    assert _by_name(results, "mind_dir").status == "ok"
    assert _by_name(results, "chimera.db").status == "ok"
    assert _by_name(results, "graph: kuzu").status == "ok"


def test_missing_provider_keys_warn_not_error():
    results = run_checks()
    anth = _by_name(results, "ANTHROPIC_API_KEY")
    openr = _by_name(results, "OPENROUTER_API_KEY")
    assert anth.status == "warn"
    assert openr.status == "warn"


def test_invalid_mcp_servers_json_is_error(monkeypatch):
    monkeypatch.setenv("CHIMERA_MCP_SERVERS", "{not json")
    results = run_checks()
    assert _by_name(results, "CHIMERA_MCP_SERVERS").status == "error"
    with pytest.raises(ConfigError):
        assert_no_errors(results)


def test_mcp_servers_non_object_is_error(monkeypatch):
    monkeypatch.setenv("CHIMERA_MCP_SERVERS", "[]")
    assert _by_name(run_checks(), "CHIMERA_MCP_SERVERS").status == "error"


def test_peer_tokens_valid_json_object_is_ok(monkeypatch):
    monkeypatch.setenv("CHIMERA_PEER_TOKENS", '{"tok-a": "peer-1"}')
    assert _by_name(run_checks(), "CHIMERA_PEER_TOKENS").status == "ok"


def test_http_auth_warns_when_no_tokens():
    assert _by_name(run_checks(), "http auth").status == "warn"


def test_http_auth_ok_when_single_token_set(monkeypatch):
    monkeypatch.setenv("CHIMERA_PEER_TOKEN", "secret")
    assert _by_name(run_checks(), "http auth").status == "ok"


def test_assert_no_errors_passes_for_clean_config():
    # Provider keys are warns, not errors → passes.
    results = assert_no_errors()
    assert results  # non-empty


# ── v4.67 (ADR 0086): cost_caps check ──────────────────────────────


def test_cost_caps_ok_with_empty_db():
    """Fresh state dir → empty DB → no spend → check returns ok.
    (The dir-writability + sqlite checks run before cost_caps and
    create an empty chimera.db, so we land on the $0-spend branch.)"""
    r = _by_name(run_checks(), "cost_caps")
    assert r.status == "ok"
    # Either branch is fine: no-db OR empty-db reports zero spend.
    assert "no chimera.db" in r.message or "$0.00" in r.message


def test_cost_caps_ok_when_under_50_pct(monkeypatch, tmp_path):
    """Seed a small spend; check should be ok and report percentage."""
    from chimera.memory import open_and_init, record_api_call
    state_dir = tmp_path / "state_seeded"
    state_dir.mkdir(parents=True, exist_ok=True)
    db = open_and_init(state_dir / "chimera.db")
    record_api_call(
        db, cycle=1, provider="openrouter",
        model_id="deepseek/deepseek-v4-pro",
        input_tokens=1_000_000, output_tokens=0,  # ~$0.44 → 2% of $20
    )
    db.commit()
    db.close()
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(state_dir))
    r = _by_name(run_checks(), "cost_caps")
    assert r.status == "ok", r.message
    assert "60m spend" in r.message


def test_cost_caps_warn_when_above_50_pct(monkeypatch, tmp_path):
    """Spend ~75% of cap → warn."""
    from chimera.memory import open_and_init, record_api_call
    state_dir = tmp_path / "state_warn"
    state_dir.mkdir(parents=True, exist_ok=True)
    db = open_and_init(state_dir / "chimera.db")
    # 1M opus input = $15 = 75% of the $20 default cap.
    record_api_call(
        db, cycle=1, provider="anthropic", model_id="claude-opus-4-7",
        input_tokens=1_000_000, output_tokens=0,
    )
    db.commit()
    db.close()
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(state_dir))
    r = _by_name(run_checks(), "cost_caps")
    assert r.status == "warn", r.message


def test_cost_caps_warn_with_over_marker(monkeypatch, tmp_path):
    """Spend > cap → warn with explicit OVER prefix."""
    from chimera.memory import open_and_init, record_api_call
    state_dir = tmp_path / "state_over"
    state_dir.mkdir(parents=True, exist_ok=True)
    db = open_and_init(state_dir / "chimera.db")
    record_api_call(
        db, cycle=1, provider="anthropic", model_id="claude-opus-4-7",
        input_tokens=2_000_000, output_tokens=0,  # $30 > $20
    )
    db.commit()
    db.close()
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(state_dir))
    r = _by_name(run_checks(), "cost_caps")
    assert r.status == "warn"
    assert "OVER" in r.message


def test_cost_caps_warn_when_rolling_cap_disabled(monkeypatch, tmp_path):
    """Operator explicitly disabled the cap → warn (not silent ok)."""
    state_dir = tmp_path / "state_disabled"
    state_dir.mkdir(parents=True, exist_ok=True)
    from chimera.memory import open_and_init
    db = open_and_init(state_dir / "chimera.db")
    db.close()
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(state_dir))
    monkeypatch.setenv("CHIMERA_ROLLING_HOUR_CAP_USD", "0")
    r = _by_name(run_checks(), "cost_caps")
    assert r.status == "warn"
    assert "disabled" in r.message.lower()


# ── v4.75: trust_state observer-mode warning ───────────────────────


def _write_heartbeat(mind_dir: Path, cycle: int) -> None:
    mind_dir.mkdir(parents=True, exist_ok=True)
    (mind_dir / "HEARTBEAT.md").write_text(
        f"---\ncycle: {cycle}\ntrust_tier: T0\nstatus: dormant\n---\nbody\n"
    )


def test_trust_state_ok_when_fresh_no_cycles(tmp_path):
    # No trust_state.json, no heartbeat → fresh install → ok.
    r = _by_name(run_checks(), "trust_state")
    assert r.status == "ok"


def test_trust_state_warn_when_missing_after_cycles(monkeypatch, tmp_path):
    state_dir = tmp_path / "state_t0"
    mind_dir = tmp_path / "mind_t0"
    state_dir.mkdir(parents=True, exist_ok=True)
    _write_heartbeat(mind_dir, cycle=7)
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(state_dir))
    monkeypatch.setenv("CHIMERA_MIND_DIR", str(mind_dir))
    r = _by_name(run_checks(), "trust_state")
    assert r.status == "warn"
    assert "trust promote" in r.message


def test_trust_state_warn_when_t0_after_cycles(monkeypatch, tmp_path):
    import json as _json
    state_dir = tmp_path / "state_locked"
    mind_dir = tmp_path / "mind_locked"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "trust_state.json").write_text(_json.dumps({
        "current_tier": 0,
        "tier_entered_at": "2026-05-20T00:00:00+00:00",
        "last_readiness": 0.0,
        "history": [],
    }))
    _write_heartbeat(mind_dir, cycle=10)
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(state_dir))
    monkeypatch.setenv("CHIMERA_MIND_DIR", str(mind_dir))
    r = _by_name(run_checks(), "trust_state")
    assert r.status == "warn"
    assert "observer mode" in r.message


def test_trust_state_ok_when_promoted(monkeypatch, tmp_path):
    import json as _json
    state_dir = tmp_path / "state_unlocked"
    mind_dir = tmp_path / "mind_unlocked"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "trust_state.json").write_text(_json.dumps({
        "current_tier": 2,
        "tier_entered_at": "2026-05-20T00:00:00+00:00",
        "last_readiness": 0.7,
        "history": [],
    }))
    _write_heartbeat(mind_dir, cycle=10)
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(state_dir))
    monkeypatch.setenv("CHIMERA_MIND_DIR", str(mind_dir))
    r = _by_name(run_checks(), "trust_state")
    assert r.status == "ok"
    assert "T2" in r.message


# ── v4.75: orphan WAL detection + checkpoint ───────────────────────


def test_wal_check_ok_when_no_wal_file(tmp_path, monkeypatch):
    """Fresh DB with no WAL → ok."""
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(tmp_path / "state_nowal"))
    r = _by_name(run_checks(), "wal")
    assert r.status == "ok"


def test_wal_check_warns_on_large_orphan_wal(tmp_path, monkeypatch):
    """Simulate a SIGKILL'd writer: a ≥1 MiB WAL with no live DB writer."""
    state_dir = tmp_path / "state_orphan"
    state_dir.mkdir(parents=True)
    db_path = state_dir / "chimera.db"
    import sqlite3
    sqlite3.connect(str(db_path)).close()
    (state_dir / "chimera.db-wal").write_bytes(b"\0" * (2 * 1024 * 1024))
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(state_dir))
    from chimera.core import doctor as _doctor
    monkeypatch.setattr(_doctor, "_has_active_writer", lambda _p: False)
    r = _by_name(run_checks(), "wal")
    assert r.status == "warn"
    assert "orphan WAL" in r.message
    assert "wal_checkpoint" in r.message


def test_checkpoint_wal_truncates_dirty_wal(tmp_path):
    """checkpoint_wal() leaves the WAL file at 0 bytes after committed writes."""
    from chimera.core import checkpoint_wal
    from chimera.memory import open_and_init, record_api_call
    state_dir = tmp_path / "state_fix"
    state_dir.mkdir(parents=True)
    conn = open_and_init(state_dir / "chimera.db")
    record_api_call(
        conn, cycle=1, provider="anthropic",
        model_id="claude-opus-4-7", input_tokens=100, output_tokens=10,
    )
    conn.commit()
    conn.close()
    ok, msg = checkpoint_wal(state_dir)
    assert ok, msg
    wal = state_dir / "chimera.db-wal"
    if wal.exists():
        assert wal.stat().st_size == 0, f"WAL not truncated: {wal.stat().st_size}"


def test_checkpoint_wal_noop_when_db_missing(tmp_path):
    from chimera.core import checkpoint_wal
    ok, msg = checkpoint_wal(tmp_path / "does_not_exist")
    assert ok is True
    assert "nothing to do" in msg


def test_shell_allowlist_warns_when_tool_missing_from_path(monkeypatch):
    """v4.80: doctor surfaces the gap when an advertised allow-list entry
    isn't on PATH so the operator can install it or accept the trim."""
    import chimera.core.doctor as doc_mod

    real_which = doc_mod.__dict__.get("shutil")  # not imported at module top
    import shutil as _shutil

    def fake_which(cmd: str) -> str | None:
        if cmd == "rg":
            return None
        return f"/usr/bin/{cmd}"

    monkeypatch.setattr(_shutil, "which", fake_which)
    result = _by_name(run_checks(), "shell_allowlist")
    assert result.status == "warn"
    assert "rg" in result.message


def test_shell_allowlist_ok_when_all_present(monkeypatch):
    import shutil as _shutil
    monkeypatch.setattr(_shutil, "which", lambda cmd: f"/usr/bin/{cmd}")
    result = _by_name(run_checks(), "shell_allowlist")
    assert result.status == "ok"


def test_cost_caps_never_returns_error(monkeypatch, tmp_path):
    """Cost-cap state is operational, not config — even absurd spend
    should warn, not error."""
    from chimera.memory import open_and_init, record_api_call
    state_dir = tmp_path / "state_huge"
    state_dir.mkdir(parents=True, exist_ok=True)
    db = open_and_init(state_dir / "chimera.db")
    record_api_call(
        db, cycle=1, provider="anthropic", model_id="claude-opus-4-7",
        input_tokens=100_000_000, output_tokens=10_000_000,
    )
    db.commit()
    db.close()
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(state_dir))
    r = _by_name(run_checks(), "cost_caps")
    assert r.status != "error"


def test_concurrent_soak_runners_ok_when_none_alive(monkeypatch):
    """v4.89: with no soak runners alive, the check is silent."""
    import subprocess

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    r = _by_name(run_checks(), "soak_runners")
    assert r.status == "ok"


def test_concurrent_soak_runners_warn_when_multiple_alive(monkeypatch):
    """v4.89: surface the leftover-runner state class identified in soak v6
    Failure A (mind/postmortems/soak-v6-2026-05-22.md)."""
    import subprocess

    stdout = (
        "12345 /bin/bash scripts/long_cycle_soak_v6.sh\n"
        "12399 /bin/bash scripts/long_cycle_soak_v6.sh\n"
    )

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    r = _by_name(run_checks(), "soak_runners")
    assert r.status == "warn"
    assert "12345" in r.message and "12399" in r.message

# ---- v4.112: orphan worktree detection ----------------------------------


def _make_worktree(wt_dir, name, branch, mtime_age_hours):
    import time as _time, os as _os
    entry = wt_dir / name
    entry.mkdir(parents=True, exist_ok=True)
    (entry / "HEAD").write_text("ref: refs/heads/" + branch + "\n")
    (entry / "gitdir").write_text("/tmp/worktrees/" + name + "\n")
    old = _time.time() - (mtime_age_hours * 3600)
    _os.utime(entry / "gitdir", (old, old))
    _os.utime(entry, (old, old))
    return entry


def _orphan_check(tmp_path, monkeypatch, **env):
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("CHIMERA_MIND_DIR", str(tmp_path / "mind"))
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    from chimera.core.doctor import _check_orphan_worktrees
    return _check_orphan_worktrees(tmp_path)


def test_orphan_worktrees_clean_repo_returns_ok(tmp_path, monkeypatch):
    r = _orphan_check(tmp_path, monkeypatch)
    assert r.status == "ok"
    assert "no .git/worktrees/" in r.message


def test_orphan_worktrees_fresh_soak_returns_ok(tmp_path, monkeypatch):
    wt_dir = tmp_path / ".git" / "worktrees"
    _make_worktree(wt_dir, "soak-v12-fix", "chimera-soak/v12-fix-graph", 0.5)
    r = _orphan_check(tmp_path, monkeypatch)
    assert r.status == "ok", r.message


def test_orphan_worktrees_aged_soak_returns_warn(tmp_path, monkeypatch):
    wt_dir = tmp_path / ".git" / "worktrees"
    _make_worktree(wt_dir, "soak-v9-stale", "chimera-soak/v9-bar", 48)
    r = _orphan_check(tmp_path, monkeypatch)
    assert r.status == "warn", r.message
    assert "git worktree remove" in r.message


def test_orphan_worktrees_threshold_env_knob(tmp_path, monkeypatch):
    wt_dir = tmp_path / ".git" / "worktrees"
    _make_worktree(wt_dir, "soak-v14-old", "chimera-soak/v14-old", 2)
    r = _orphan_check(tmp_path, monkeypatch, CHIMERA_DOCTOR_WORKTREE_AGE_HOURS="1")
    assert r.status == "warn", r.message
    assert "git worktree remove" in r.message


def test_orphan_worktrees_non_soak_branch_ignored(tmp_path, monkeypatch):
    wt_dir = tmp_path / ".git" / "worktrees"
    _make_worktree(wt_dir, "main-dev", "main", 200)
    r = _orphan_check(tmp_path, monkeypatch)
    assert r.status == "ok", r.message


def test_orphan_worktrees_malformed_metadata_returns_ok(tmp_path, monkeypatch):
    wt_dir = tmp_path / ".git" / "worktrees"
    entry = wt_dir / "bogus"
    entry.mkdir(parents=True, exist_ok=True)
    r = _orphan_check(tmp_path, monkeypatch)
    assert r.status == "ok", r.message


# ── v4.??: uv_installed check ──────────────────────────────────────

# ── v31: main worktree branch drift ─────────────────────────────────
#
# The detector at chimera.core.doctor.detect_main_worktree_branch_drift
# uses `git rev-parse --git-dir` vs `--git-common-dir` to distinguish
# the primary worktree from `git worktree add`-ed secondaries; they
# are equal only in the primary. Earlier the discriminator was
# `--show-toplevel` vs cwd, which is equal in every worktree (each
# worktree reports its own toplevel) — that bug shipped to main and
# was caught by the v35 soak postmortem (2026-05-28). The mock helper
# below therefore takes both git-dir and git-common-dir stdout values;
# defaults reflect "primary worktree" (.git == .git). Tests later in
# this file create real `git worktree add`-ed secondaries as
# integration coverage so a future mock-only regression cannot mask
# the bug again.

def _drift_check(monkeypatch, rev_parse_stdout, head_stdout,
                 rev_parse_rc=0, head_rc=0, repo_root=None,
                 git_dir_stdout=".git\n", git_common_dir_stdout=".git\n",
                 git_dir_rc=0, git_common_dir_rc=0):
    """Call _check_main_worktree_branch_drift with mocked git subprocess.

    Defaults represent a primary worktree where git-dir == git-common-dir
    (both ".git"). Pass differing stdouts to simulate a secondary worktree.
    """
    import subprocess as _subprocess

    def fake_run(*args, **kwargs):
        argv = args[0] if args else []
        if "--git-dir" in argv:
            return _subprocess.CompletedProcess(
                args=args, returncode=git_dir_rc,
                stdout=git_dir_stdout, stderr="",
            )
        elif "--git-common-dir" in argv:
            return _subprocess.CompletedProcess(
                args=args, returncode=git_common_dir_rc,
                stdout=git_common_dir_stdout, stderr="",
            )
        elif "--show-toplevel" in argv:
            return _subprocess.CompletedProcess(
                args=args, returncode=rev_parse_rc,
                stdout=rev_parse_stdout, stderr="",
            )
        else:
            return _subprocess.CompletedProcess(
                args=args, returncode=head_rc,
                stdout=head_stdout, stderr="",
            )

    monkeypatch.setattr("subprocess.run", fake_run)
    from chimera.core.doctor import _check_main_worktree_branch_drift
    if repo_root is None:
        # Default: cwd == git toplevel (both point at the same tmp_path)
        repo_root = Path(rev_parse_stdout.strip())
    return _check_main_worktree_branch_drift(repo_root)


def test_worktree_branch_drift_ok_when_on_main(tmp_path, monkeypatch):
    r = _drift_check(monkeypatch,
        rev_parse_stdout=str(tmp_path) + "\n",
        head_stdout="main\n")
    assert r.status == "ok"


def test_worktree_branch_drift_warns_when_on_feature_branch(tmp_path, monkeypatch):
    r = _drift_check(monkeypatch,
        rev_parse_stdout=str(tmp_path) + "\n",
        head_stdout="chip/v31-fix\n")
    assert r.status == "warn"
    assert "chip/v31-fix" in r.message
    assert "git checkout main" in r.message


def test_worktree_branch_drift_ok_when_in_secondary_worktree(tmp_path, monkeypatch):
    """A secondary worktree has git-dir != git-common-dir. The detector
    must return ok regardless of the branch checked out there."""
    r = _drift_check(monkeypatch,
        rev_parse_stdout=str(tmp_path) + "\n",
        head_stdout="chimera-soak/v31-xyz\n",
        repo_root=tmp_path,
        git_dir_stdout=str(tmp_path / ".git" / "worktrees" / "secondary") + "\n",
        git_common_dir_stdout=str(tmp_path / ".git") + "\n")
    assert r.status == "ok"
    assert "secondary worktree" in r.message


def test_worktree_branch_drift_ok_when_git_fails(tmp_path, monkeypatch):
    r = _drift_check(monkeypatch,
        rev_parse_stdout="", rev_parse_rc=128,
        head_stdout="",
        repo_root=tmp_path)
    assert r.status == "ok"


def test_worktree_branch_drift_ok_when_git_dir_fails(tmp_path, monkeypatch):
    """If git-dir / git-common-dir queries fail, fall back to ok (conservative)."""
    r = _drift_check(monkeypatch,
        rev_parse_stdout=str(tmp_path) + "\n",
        head_stdout="chip/whatever\n",
        repo_root=tmp_path,
        git_dir_stdout="", git_dir_rc=128)
    assert r.status == "ok"


def test_worktree_branch_drift_ok_when_detached_head(tmp_path, monkeypatch):
    r = _drift_check(monkeypatch,
        rev_parse_stdout=str(tmp_path) + "\n",
        head_stdout="HEAD\n")
    assert r.status == "ok"
    assert "detached" in r.message


# ── integration: real `git worktree add` (v35 postmortem regression) ──
#
# These tests create actual git repositories on disk and exercise
# `git worktree add` to validate that detect_main_worktree_branch_drift
# correctly identifies primary vs secondary worktrees. They are the
# regression coverage for the v35 soak postmortem (2026-05-28) where
# a mock-only test suite masked a real-world detector bug.

def _git(cwd, *args):
    """Run a git command at cwd, return stdout stripped. Fail loudly."""
    import subprocess as _subprocess
    result = _subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


def _init_real_repo(repo_path):
    """Create an isolated git repo at repo_path with one commit on main."""
    repo_path.mkdir(parents=True, exist_ok=True)
    _git(repo_path, "init", "-q", "-b", "main")
    _git(repo_path, "config", "user.email", "test@example.com")
    _git(repo_path, "config", "user.name", "Test")
    _git(repo_path, "config", "commit.gpgsign", "false")
    (repo_path / "README.md").write_text("test\n")
    _git(repo_path, "add", "README.md")
    _git(repo_path, "commit", "-q", "-m", "initial")


def test_real_primary_worktree_on_main_is_not_drifted(tmp_path):
    """Primary worktree on main → drifted=False."""
    from chimera.core.doctor import detect_main_worktree_branch_drift
    repo = tmp_path / "primary"
    _init_real_repo(repo)
    signal = detect_main_worktree_branch_drift(repo)
    assert signal.drifted is False
    assert signal.branch == "main"


def test_real_primary_worktree_on_feature_branch_is_drifted(tmp_path):
    """Primary worktree on a non-main branch → drifted=True (the papercut)."""
    from chimera.core.doctor import detect_main_worktree_branch_drift
    repo = tmp_path / "primary"
    _init_real_repo(repo)
    _git(repo, "checkout", "-q", "-b", "chip/example")
    signal = detect_main_worktree_branch_drift(repo)
    assert signal.drifted is True
    assert signal.branch == "chip/example"
    assert "not main" in signal.reason


def test_real_secondary_worktree_on_branch_is_not_drifted(tmp_path):
    """Secondary `git worktree add`-ed branch must NOT be flagged as drifted.

    Regression test for the v35 soak postmortem (2026-05-28): the previous
    detector used `--show-toplevel == cwd` which is true in every worktree,
    so it falsely identified every secondary as the primary and refused
    every `chimera run` from inside chip worktrees.
    """
    from chimera.core.doctor import detect_main_worktree_branch_drift
    repo = tmp_path / "primary"
    _init_real_repo(repo)
    secondary = tmp_path / "secondary"
    _git(repo, "worktree", "add", "-b", "chimera-soak/v35-test", str(secondary), "main")
    signal = detect_main_worktree_branch_drift(secondary)
    assert signal.drifted is False, (
        f"secondary worktree on a non-main branch must not be flagged as drifted; "
        f"got reason={signal.reason!r}"
    )
    assert "secondary worktree" in signal.reason


def test_worktree_branch_drift_in_registry(monkeypatch):
    from chimera.core.doctor import CheckResult as _CR
    import chimera.core.doctor as _doctor
    sentinel = _CR("worktree_branch_drift", "ok", "sentinel")
    monkeypatch.setattr(_doctor, "_check_main_worktree_branch_drift", lambda _: sentinel)
    results = run_checks()
    assert sentinel in results


def test_check_uv_installed_returns_ok_when_present(monkeypatch):
    """Monkeypatch shutil.which('uv') to return a path; check is ok."""
    import shutil
    monkeypatch.setattr(shutil, "which", lambda cmd: "/usr/local/bin/uv" if cmd == "uv" else None)
    r = _by_name(run_checks(), "uv_installed")
    assert r.status == "ok"
    assert "/usr/local/bin/uv" in r.message


# ── ADR 0141 Layer 3: pre-commit hook installer ─────────────────────────

def _fake_repo(tmp_path):
    """Materialize a tmp dir that looks like a git repo (`.git/`)."""
    (tmp_path / ".git").mkdir()
    return tmp_path


def test_install_hook_writes_executable_with_sentinel(tmp_path):
    from chimera.hooks import HOOK_SENTINEL, install_pre_commit_hook
    repo = _fake_repo(tmp_path)
    result = install_pre_commit_hook(repo)
    assert result.status == "installed", result.message
    assert result.path is not None and result.path.exists()
    content = result.path.read_text()
    assert HOOK_SENTINEL in content
    assert "chip-branch-jump detected" in content
    assert "mind/CHRONICLE.md" in content
    # Executable bit set for user
    import stat as _stat
    mode = result.path.stat().st_mode
    assert mode & _stat.S_IXUSR, "hook should be user-executable"


def test_install_hook_is_idempotent(tmp_path):
    from chimera.hooks import install_pre_commit_hook
    repo = _fake_repo(tmp_path)
    r1 = install_pre_commit_hook(repo)
    assert r1.status == "installed"
    first_mtime = r1.path.stat().st_mtime
    r2 = install_pre_commit_hook(repo)
    assert r2.status == "already_installed", r2.message
    # No rewrite — mtime unchanged
    assert r2.path.stat().st_mtime == first_mtime


def test_install_hook_refuses_to_clobber_foreign_hook(tmp_path):
    from chimera.hooks import install_pre_commit_hook
    repo = _fake_repo(tmp_path)
    hooks_dir = repo / ".git" / "hooks"
    hooks_dir.mkdir(parents=True)
    foreign = hooks_dir / "pre-commit"
    foreign.write_text("#!/bin/sh\n# someone-else's hook\nexit 0\n")
    result = install_pre_commit_hook(repo)
    assert result.status == "foreign_hook"
    # Foreign content untouched
    assert "someone-else's hook" in foreign.read_text()


def test_install_hook_reports_no_git_dir(tmp_path):
    from chimera.hooks import install_pre_commit_hook
    # No .git/ in tmp_path
    result = install_pre_commit_hook(tmp_path)
    assert result.status == "no_git_dir"
    assert "not a directory" in result.message or "not a git" in result.message


def test_check_uv_installed_returns_error_when_missing(monkeypatch):
    """Monkeypatch shutil.which('uv') to return None; check is error."""
    import shutil
    monkeypatch.setattr(shutil, "which", lambda cmd: None)
    r = _by_name(run_checks(), "uv_installed")
    assert r.status == "error"
    assert "install" in r.message.lower()


def test_check_uv_installed_never_raises_on_exception(monkeypatch):
    """Monkeypatch shutil.which to raise OSError; function catches it."""
    import shutil
    monkeypatch.setattr(shutil, "which", lambda cmd: (_ for _ in ()).throw(OSError("mock error")))
    from chimera.core.doctor import _check_uv_installed
    r = _check_uv_installed()
    assert r.status == "error"
    # OSError swallowed — no exception propagated


def test_check_uv_installed_in_registry(monkeypatch):
    """Verify _check_uv_installed is invoked by run_checks."""
    from chimera.core.doctor import CheckResult as _CR
    import chimera.core.doctor as _doctor
    sentinel = _CR("uv_installed", "ok", "sentinel")
    monkeypatch.setattr(_doctor, "_check_uv_installed", lambda: sentinel)
    results = run_checks()
    assert sentinel in results


# ADR 0120 — soak runner liveness check
def test_soak_liveness_ok_when_no_logs(tmp_path, monkeypatch):
    from chimera.core.doctor import _check_soak_runner_liveness
    r = _check_soak_runner_liveness(tmp_path)
    assert r.status == "ok"


def test_soak_liveness_ok_when_log_is_fresh(tmp_path):
    from chimera.core.doctor import _check_soak_runner_liveness
    (tmp_path / "long_cycle_v22_2026-05-23-2039.log").write_text("fresh")
    r = _check_soak_runner_liveness(tmp_path)
    assert r.status == "ok", r.message


def test_soak_liveness_warns_when_log_stale_and_runner_alive(tmp_path, monkeypatch):
    """Stale log + matching runner-alive output → warn."""
    import os, time
    from chimera.core.doctor import _check_soak_runner_liveness
    log = tmp_path / "long_cycle_v22_2026-05-23-2039.log"
    log.write_text("stale")
    # Age the log 30 min into the past
    old = time.time() - (30 * 60)
    os.utime(log, (old, old))

    # Mock subprocess.run to report a v22 runner alive
    import chimera.core.doctor as doc
    class _FakeResult:
        stdout = "12345 bash scripts/long_cycle_soak_v22.sh\n"
    monkeypatch.setattr(doc.subprocess if hasattr(doc, 'subprocess') else __import__('subprocess'),
                        "run", lambda *a, **k: _FakeResult())
    # pgrep must be available
    import shutil
    monkeypatch.setattr(shutil, "which", lambda c: "/usr/bin/pgrep" if c == "pgrep" else None)
    r = _check_soak_runner_liveness(tmp_path)
    assert r.status == "warn"
    assert "stalled" in r.message
    assert "ADR 0120" in r.message


def test_soak_liveness_ok_when_log_stale_but_no_runner(tmp_path, monkeypatch):
    """Stale log but no matching live runner → ok (runner already exited)."""
    import os, time
    log = tmp_path / "long_cycle_v22_2026-05-23-2039.log"
    log.write_text("stale")
    old = time.time() - (30 * 60)
    os.utime(log, (old, old))

    import subprocess
    class _FakeResult:
        stdout = ""  # no runners alive
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _FakeResult())
    import shutil
    monkeypatch.setattr(shutil, "which", lambda c: "/usr/bin/pgrep" if c == "pgrep" else None)
    from chimera.core.doctor import _check_soak_runner_liveness
    r = _check_soak_runner_liveness(tmp_path)
    assert r.status == "ok"


def test_soak_liveness_in_registry(monkeypatch):
    """Verify _check_soak_runner_liveness is invoked by run_checks."""
    from chimera.core.doctor import CheckResult as _CR
    import chimera.core.doctor as _doctor
    sentinel = _CR("soak_liveness", "ok", "sentinel")
    monkeypatch.setattr(_doctor, "_check_soak_runner_liveness", lambda _: sentinel)
    results = run_checks()
    assert sentinel in results

# ── combined ok + warn: branch drift (parametrised) ─────────────────

import pytest as _pytest

@_pytest.mark.parametrize(
    "branch,expected_status",
    [("main", "ok"), ("chip/v31-fix", "warn")],
)
def test_worktree_branch_drift_ok_and_warn(tmp_path, monkeypatch, branch, expected_status):
    import subprocess as _subprocess

    def fake_run(*args, **kwargs):
        argv = args[0] if args else []
        if "--show-toplevel" in argv:
            stdout = str(tmp_path) + "\n"
        elif "--git-dir" in argv or "--git-common-dir" in argv:
            # Primary worktree: git-dir == git-common-dir.
            stdout = ".git\n"
        else:
            stdout = branch + "\n"
        return _subprocess.CompletedProcess(args=args, returncode=0, stdout=stdout, stderr="")
    monkeypatch.setattr("subprocess.run", fake_run)
    from chimera.core.doctor import _check_main_worktree_branch_drift
    from pathlib import Path
    r = _check_main_worktree_branch_drift(tmp_path)
    assert r.status == expected_status
