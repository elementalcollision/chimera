"""R4 (ADR 0150): the atomic git_commit tool.

The tool stages the named paths and creates ONE commit by routing both
operations through the gated shell_handler, so every commit gate (allow-list,
engines-off, T0 trust, ADR 0146 scope check) still applies. These tests pin the
happy path, [agent] auto-prefixing, the staged-index path, the engines-off
refusal surfacing as text (not a crash), registration, and arg validation.
"""

from __future__ import annotations

import asyncio
import subprocess

import pytest

from chimera.tools.dispatch import DispatchContext
from chimera.tools.git_commit import (
    _normalize_message,
    git_commit_handler,
    register_git_commit_tool,
)
from chimera.tools.registry import ToolRegistry


def _git(root, *args) -> None:
    subprocess.run(
        ["git", *args], cwd=str(root), check=True,
        capture_output=True, text=True,
    )


def _init_repo(root) -> None:
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@t.t")
    _git(root, "config", "user.name", "t")
    (root / "seed.txt").write_text("seed\n")
    _git(root, "add", "seed.txt")
    _git(root, "commit", "-qm", "seed")


def _scope_roots_to(monkeypatch, root) -> None:
    """Make ``root`` the shell-tool's allowed cwd root, deterministically.

    shell_handler resolves its allowed cwd roots from CHIMERA_MIND_DIR /
    CHIMERA_STATE_DIR (or cwd/mind, cwd/state). Pointing both under ``root``
    makes ``root`` their shared parent → the default cwd. We set them
    explicitly (not via chdir) so a leaked env var from another test cannot
    change the roots — the CI-only failure this guards against. The
    git_commit calls then OMIT cwd and default to ``root`` (the worktree),
    matching production use.
    """
    monkeypatch.setenv("CHIMERA_MIND_DIR", str(root / "mind"))
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(root / "state"))


def _head_subject(root) -> str:
    return subprocess.run(
        ["git", "log", "-1", "--format=%s"], cwd=str(root),
        capture_output=True, text=True,
    ).stdout.strip()


def _run(coro):
    return asyncio.run(coro)


# ── _normalize_message ──────────────────────────────────────────────


def test_normalize_adds_agent_prefix():
    assert _normalize_message("create the module") == "[agent] create the module"


def test_normalize_preserves_existing_prefix():
    assert _normalize_message("[agent] already tagged") == "[agent] already tagged"


# ── git_commit_handler (real temp repo) ─────────────────────────────


def test_stages_paths_and_commits(tmp_path, monkeypatch):
    monkeypatch.setenv("CHIMERA_ENGINES_ENABLED", "1")
    _scope_roots_to(monkeypatch, tmp_path)
    _init_repo(tmp_path)
    (tmp_path / "deliverable.py").write_text("x = 1\n")
    ctx = DispatchContext()
    out = _run(git_commit_handler(
        {"message": "create deliverable", "paths": ["deliverable.py"]},
        ctx,
    ))
    assert out.startswith("committed:")
    subject = _head_subject(tmp_path)
    assert subject == "[agent] create deliverable"
    # The file is in the new commit.
    show = subprocess.run(
        ["git", "show", "--name-only", "--format=", "HEAD"],
        cwd=str(tmp_path), capture_output=True, text=True,
    ).stdout
    assert "deliverable.py" in show


def test_commits_already_staged_index_without_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("CHIMERA_ENGINES_ENABLED", "1")
    _scope_roots_to(monkeypatch, tmp_path)
    _init_repo(tmp_path)
    (tmp_path / "d.py").write_text("x = 1\n")
    _git(tmp_path, "add", "d.py")  # agent staged in a prior step
    out = _run(git_commit_handler(
        {"message": "[agent] land it"}, DispatchContext(),
    ))
    assert out.startswith("committed:")
    assert _head_subject(tmp_path) == "[agent] land it"


def test_engines_off_refusal_surfaces_as_text_not_crash(tmp_path, monkeypatch):
    # Phase-1 engines-off block: the shell gate raises PermissionError; the tool
    # must surface the reason, not propagate the exception.
    monkeypatch.setenv("CHIMERA_ENGINES_ENABLED", "0")
    _scope_roots_to(monkeypatch, tmp_path)
    _init_repo(tmp_path)
    (tmp_path / "d.py").write_text("x = 1\n")
    out = _run(git_commit_handler(
        {"message": "should be blocked", "paths": ["d.py"]},
        DispatchContext(),
    ))
    assert "refused by a commit gate" in out
    assert "CHIMERA_ENGINES_ENABLED=0" in out
    # No commit landed.
    n = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"], cwd=str(tmp_path),
        capture_output=True, text=True,
    ).stdout.strip()
    assert n == "1"  # only the seed commit


def test_empty_message_rejected(tmp_path):
    with pytest.raises(ValueError):
        _run(git_commit_handler({"message": "   "}, DispatchContext()))


def test_bad_paths_type_rejected():
    with pytest.raises(ValueError):
        _run(git_commit_handler({"message": "x", "paths": "notalist"}, DispatchContext()))


# ── registration ────────────────────────────────────────────────────


def test_registers_into_registry():
    reg = ToolRegistry()
    register_git_commit_tool(reg)
    schemas = {s["function"]["name"] for s in reg.schemas()}
    assert "git_commit" in schemas


def test_register_core_tools_includes_git_commit():
    from chimera.tools import register_core_tools
    reg = ToolRegistry()
    register_core_tools(reg)
    schemas = {s["function"]["name"] for s in reg.schemas()}
    assert "git_commit" in schemas
    assert "shell" in schemas  # sanity: core set still present


# ── ADR 0162: the in-loop critic gate, through the real commit path ──


def _no_provider(monkeypatch):
    # Force the gate's reviewer/escalator builder to find no provider, so the
    # fail-closed path is exercised hermetically (no live LLM).
    import chimera.core.critic_gate as cg
    monkeypatch.setattr(cg, "_build_reviewer", lambda *a, **k: None)


def _clean_calibration(tmp_path):
    # Enforcement requires a clean calibration record (false_approve == 0).
    import chimera.core.critic_gate as cg
    cg.write_calibration_record(tmp_path, total=27, false_approve=0,
                                false_reject=3, accuracy=0.89)


def test_critic_gate_blocks_commit_when_enforced_and_failclosed(tmp_path, monkeypatch):
    monkeypatch.setenv("CHIMERA_ENGINES_ENABLED", "1")
    monkeypatch.setenv("CHIMERA_CRITIC_ENFORCE", "1")
    monkeypatch.delenv("CHIMERA_ALLOW_CRITIC_REJECT", raising=False)
    _scope_roots_to(monkeypatch, tmp_path)
    _no_provider(monkeypatch)
    _init_repo(tmp_path)
    _clean_calibration(tmp_path)  # calibration OK → reach the fail-closed reviewer
    (tmp_path / "d.py").write_text("x = 1\n")
    out = _run(git_commit_handler(
        {"message": "land it", "paths": ["d.py"]}, DispatchContext(),
    ))
    assert "refused by a commit gate" in out
    assert "ADR 0162" in out and "needs human review" in out


def test_critic_gate_blocks_commit_when_calibration_unverified(tmp_path, monkeypatch):
    # Enforce ON but NO calibration record → blocked before any review.
    monkeypatch.setenv("CHIMERA_ENGINES_ENABLED", "1")
    monkeypatch.setenv("CHIMERA_CRITIC_ENFORCE", "1")
    monkeypatch.delenv("CHIMERA_ALLOW_CRITIC_REJECT", raising=False)
    _scope_roots_to(monkeypatch, tmp_path)
    _init_repo(tmp_path)
    (tmp_path / "d.py").write_text("x = 1\n")
    out = _run(git_commit_handler(
        {"message": "land it", "paths": ["d.py"]}, DispatchContext(),
    ))
    assert "refused by a commit gate" in out
    assert "critic-calibrate" in out
    n = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"], cwd=str(tmp_path),
        capture_output=True, text=True,
    ).stdout.strip()
    assert n == "1"
    # No commit landed beyond the seed.
    n = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"], cwd=str(tmp_path),
        capture_output=True, text=True,
    ).stdout.strip()
    assert n == "1"


def test_critic_gate_override_allows_commit(tmp_path, monkeypatch):
    monkeypatch.setenv("CHIMERA_ENGINES_ENABLED", "1")
    monkeypatch.setenv("CHIMERA_CRITIC_ENFORCE", "1")
    monkeypatch.setenv("CHIMERA_ALLOW_CRITIC_REJECT", "1")  # operator escape valve
    _scope_roots_to(monkeypatch, tmp_path)
    _no_provider(monkeypatch)
    _init_repo(tmp_path)
    (tmp_path / "d.py").write_text("x = 1\n")
    out = _run(git_commit_handler(
        {"message": "land it", "paths": ["d.py"]}, DispatchContext(),
    ))
    assert out.startswith("committed:")
    assert _head_subject(tmp_path) == "[agent] land it"


def test_critic_gate_inert_when_not_enforced(tmp_path, monkeypatch):
    # Default (no CHIMERA_CRITIC_ENFORCE): the gate must not touch the commit,
    # even with no provider — proves the feature is off-by-default.
    monkeypatch.setenv("CHIMERA_ENGINES_ENABLED", "1")
    monkeypatch.delenv("CHIMERA_CRITIC_ENFORCE", raising=False)
    _scope_roots_to(monkeypatch, tmp_path)
    _no_provider(monkeypatch)
    _init_repo(tmp_path)
    (tmp_path / "d.py").write_text("x = 1\n")
    out = _run(git_commit_handler(
        {"message": "land it", "paths": ["d.py"]}, DispatchContext(),
    ))
    assert out.startswith("committed:")
