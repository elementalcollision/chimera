"""v4.97 (ADR 0102) — `chimera submit-pr` validations + push/PR seams."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


from chimera.core.submit_pr import (
    HIGH_ENTROPY_PATTERN,
    _check_fix_without_test,
    _dirty_paths,
    _entropy_hits,
    _foreign_push_env,
    _has_secret_path,
    revert_out_of_scope_residue,
    submit_pr,
    validate,
)


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(
        ["git", *args], cwd=str(cwd), check=True,
        capture_output=True, text=True,
    )


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git("init", "-q", "-b", "main", cwd=path)
    _git("config", "user.email", "test@example.com", cwd=path)
    _git("config", "user.name", "Test", cwd=path)
    (path / "README.md").write_text("hello\n")
    _git("add", ".", cwd=path)
    _git("commit", "-q", "-m", "initial", cwd=path)


def _make_soak_worktree(repo: Path, branch: str = "chimera-soak/v9-test") -> Path:
    _git("checkout", "-q", "-b", branch, cwd=repo)
    return repo


def _commit(repo: Path, path: str, content: str, message: str) -> str:
    fp = repo / path
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(content)
    _git("add", path, cwd=repo)
    _git("commit", "-q", "-m", message, cwd=repo)
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(repo),
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    return sha


# --- B.4g: scope-invariant revert (foreign worktree) -----------------------


def _setup_foreign_residue(tmp_path: Path) -> Path:
    """A foreign clone where HEAD == base + the 2 allowlisted files, then a
    tree-wide `ruff --fix`-style sprawl + scratch file + operational dirs left
    UNCOMMITTED on top — exactly the first claude-daemon dry-run shape."""
    repo = tmp_path / "clone"
    _init_repo(repo)  # commits README.md (a pre-existing tracked file)
    # Pre-existing source file with an unused import (the kind ruff strips):
    (repo / "daemon").mkdir()
    (repo / "daemon" / "api.py").write_text("import os\nimport sys\n\nx = sys.argv\n")
    _git("add", ".", cwd=repo)
    _git("commit", "-q", "-m", "baseline", cwd=repo)
    # The agent's CORRECT scoped commit (the allowlist, already in HEAD):
    (repo / "tools").mkdir()
    (repo / "tools" / "noop_probe.py").write_text("def noop_probe() -> None:\n    return None\n")
    _git("add", "tools/noop_probe.py", cwd=repo)
    _git("commit", "-q", "-m", "[agent] add noop_probe", cwd=repo)
    # OUT-OF-SCOPE residue left uncommitted: a ruff-style edit to a tracked file,
    # a scratch file, and a churned lockfile:
    (repo / "daemon" / "api.py").write_text("import sys\n\nx = sys.argv\n")  # 'import os' stripped
    (repo / "noop.py").write_text('"""No-op module."""\n')                  # untracked scratch
    (repo / "uv.lock").write_text("# regenerated lock drift\n")             # untracked drift
    # Operational dirs the soak writes (must be KEPT for forensics):
    (repo / "mind").mkdir()
    (repo / "mind" / "SESSION_LOG.md").write_text("cycle 1\n")
    (repo / "state").mkdir()
    (repo / "state" / "trust_state.json").write_text("{}\n")
    return repo


def test_revert_out_of_scope_residue_strips_sprawl_keeps_scope_and_operational(tmp_path):
    repo = _setup_foreign_residue(tmp_path)
    reverted = revert_out_of_scope_residue(
        repo, keep_prefixes=("mind/", "state/", ".venv/")
    )
    # It reported the out-of-scope paths (visible, not masked):
    assert "daemon/api.py" in reverted
    assert "noop.py" in reverted
    assert "uv.lock" in reverted
    # ...and did NOT touch operational paths:
    assert not any(p.startswith(("mind/", "state/")) for p in reverted)
    # The tracked ruff edit was reverted to HEAD (unused import restored):
    assert "import os" in (repo / "daemon" / "api.py").read_text()
    # The untracked scratch + drift were removed:
    assert not (repo / "noop.py").exists()
    assert not (repo / "uv.lock").exists()
    # The committed allowlist survives, and operational dirs are kept:
    assert (repo / "tools" / "noop_probe.py").exists()
    assert (repo / "mind" / "SESSION_LOG.md").exists()
    assert (repo / "state" / "trust_state.json").exists()
    # The worktree is now clean except the ignored operational paths → PR-able:
    assert _dirty_paths(repo, ("mind/", "state/", ".venv/")) == []


def test_revert_out_of_scope_residue_noop_when_clean(tmp_path):
    repo = tmp_path / "clean"
    _init_repo(repo)
    assert revert_out_of_scope_residue(repo, keep_prefixes=("mind/",)) == []


# --- unit helpers ----------------------------------------------------------


def test_has_secret_path_blocklist():
    assert _has_secret_path(".env")
    assert _has_secret_path(".envrc")
    assert _has_secret_path("state/trust_state.json")
    assert _has_secret_path("foo/api_token.py")
    assert _has_secret_path("config/secret_key.yaml")
    assert _has_secret_path("creds/credentials.json")
    assert not _has_secret_path("chimera/core/act.py")
    assert not _has_secret_path("tests/test_foo.py")


def test_entropy_hits_catches_token_like():
    diff = (
        "diff --git a/x.py b/x.py\n"
        "+++ b/x.py\n"
        "+API_KEY = 'sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcdef'\n"
        "-old = 'short'\n"  # not added
        " context line with AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\n"  # context
    )
    hits = _entropy_hits(diff)
    assert hits, "should detect base64-ish token in added line"
    # Context line should NOT contribute (does not start with '+').
    assert all("ABCDEF" in h or len(h) >= 40 for h in hits)


def test_entropy_pattern_skips_short_strings():
    assert HIGH_ENTROPY_PATTERN.search("short") is None
    assert HIGH_ENTROPY_PATTERN.search("a" * 40) is not None


def test_check_fix_without_test_v492_gate():
    # chimera/ touched, no tests/ → flagged
    assert _check_fix_without_test(["chimera/core/act.py"]) == ["chimera/core/act.py"]
    # chimera/ + tests/ → ok
    assert _check_fix_without_test(
        ["chimera/core/act.py", "tests/test_act.py"]
    ) == []
    # __init__/version excluded (bookkeeping)
    assert _check_fix_without_test(["chimera/__init__.py"]) == []
    # no chimera/ → ok
    assert _check_fix_without_test(["docs/adr/0102.md"]) == []


# --- end-to-end validate() over a real git tree ---------------------------


def test_validate_rejects_non_soak_branch(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _git("checkout", "-q", "-b", "feature/foo", cwd=repo)
    _commit(repo, "chimera/x.py", "x=1\n", "[agent] add x")
    _commit(repo, "tests/test_x.py", "def test_x(): pass\n", "[agent] test x")

    branch, commits, errors = validate(repo, base="main")
    assert any("does not match soak pattern" in e for e in errors)


def test_validate_rejects_dirty_worktree(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _make_soak_worktree(repo)
    _commit(repo, "chimera/x.py", "x=1\n", "[agent] add x")
    _commit(repo, "tests/test_x.py", "def t(): pass\n", "[agent] test")
    # Dirty the tree:
    (repo / "chimera" / "x.py").write_text("x=2\n")

    _, _, errors = validate(repo, base="main")
    assert any("uncommitted changes" in e for e in errors)


def test_validate_rejects_non_agent_commit(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _make_soak_worktree(repo)
    _commit(repo, "chimera/x.py", "x=1\n", "[agent] add x")
    _commit(repo, "tests/test_x.py", "def t(): pass\n", "[agent] test")
    # Non-allow-listed subject:
    _commit(repo, "notes.md", "wip\n", "random hacking around")

    _, _, errors = validate(repo, base="main")
    assert any("neither [agent] nor an allow-listed" in e for e in errors)


def test_validate_rejects_env_file(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _make_soak_worktree(repo)
    _commit(repo, ".env", "SECRET=hunter2\n", "[agent] add env")

    _, _, errors = validate(repo, base="main")
    assert any("secret-shaped path" in e and ".env" in e for e in errors)


def test_validate_rejects_high_entropy(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _make_soak_worktree(repo)
    # Both source + test, to bypass the fix_without_test gate.
    _commit(
        repo, "chimera/x.py",
        "TOKEN = 'AKIA1234567890ABCDEFGHIJKLMNOPQRSTUVWXYZ0123'\n",
        "[agent] add x",
    )
    _commit(repo, "tests/test_x.py", "def t(): pass\n", "[agent] test")

    _, _, errors = validate(repo, base="main", allow_entropy=False)
    assert any("high-entropy" in e for e in errors)

    # With --allow-entropy the check is skipped.
    _, _, errors2 = validate(repo, base="main", allow_entropy=True)
    assert not any("high-entropy" in e for e in errors2)


def test_validate_rejects_fix_without_test(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _make_soak_worktree(repo)
    _commit(repo, "chimera/x.py", "x=1\n", "[agent] add x")
    # No tests/ touched.

    _, _, errors = validate(repo, base="main")
    assert any("fix_without_test" in e for e in errors)


def test_validate_happy_path(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _make_soak_worktree(repo)
    _commit(repo, "chimera/x.py", "x=1\n", "[agent] add x")
    _commit(repo, "tests/test_x.py", "def t(): pass\n", "[agent] test x")

    branch, commits, errors = validate(repo, base="main")
    assert branch == "chimera-soak/v9-test"
    assert len(commits) == 2
    assert errors == [], errors


# --- submit_pr() integration with mocked push + gh -----------------------


def test_submit_pr_dry_run_writes_audit(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _make_soak_worktree(repo)
    _commit(repo, "chimera/x.py", "x=1\n", "[agent] add x")
    _commit(repo, "tests/test_x.py", "def t(): pass\n", "[agent] test x")

    audit = tmp_path / "audit.jsonl"
    pushed: list[list[str]] = []
    gh_called: list[list[str]] = []

    result = submit_pr(
        worktree=repo, repo_root=repo,
        dry_run=True,
        audit_path=audit,
        push_runner=lambda cmd: (pushed.append(cmd) or (True, "")),
        gh_runner=lambda cmd: (gh_called.append(cmd) or (True, "url", "")),
    )
    assert result.ok
    assert result.dry_run
    assert not result.pushed
    assert pushed == []
    assert gh_called == []
    rows = [json.loads(ln) for ln in audit.read_text().splitlines() if ln.strip()]
    assert len(rows) == 1
    assert rows[0]["event"] == "submit_pr.dry_run"


def test_submit_pr_happy_path_opens_pr(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _make_soak_worktree(repo)
    _commit(repo, "chimera/x.py", "x=1\n", "[agent] add x")
    _commit(repo, "tests/test_x.py", "def t(): pass\n", "[agent] test x")

    audit = tmp_path / "audit.jsonl"
    captured_gh: list[list[str]] = []

    result = submit_pr(
        worktree=repo, repo_root=repo,
        audit_path=audit,
        push_runner=lambda cmd: (True, ""),
        gh_runner=lambda cmd: (
            captured_gh.append(cmd) or
            (True, "https://github.com/o/r/pull/42", "")
        ),
    )
    assert result.ok, result.validation_errors
    assert result.pushed
    assert result.pr_url == "https://github.com/o/r/pull/42"
    # Default is draft.
    assert "--draft" in captured_gh[0]
    rows = [json.loads(ln) for ln in audit.read_text().splitlines() if ln.strip()]
    assert rows[-1]["event"] == "submit_pr.success"
    assert rows[-1]["pr_url"] == "https://github.com/o/r/pull/42"


# --- ADR 0186 B.4b: foreign-repo targeting ------------------------------


def test_submit_pr_foreign_targets_repo(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _make_soak_worktree(repo)
    _commit(repo, "chimera/x.py", "x=1\n", "[agent] add x")
    _commit(repo, "tests/test_x.py", "def t(): pass\n", "[agent] test x")

    audit = tmp_path / "audit.jsonl"
    pushed: list[list[str]] = []
    captured_gh: list[list[str]] = []

    result = submit_pr(
        worktree=repo, repo_root=repo,
        foreign_repo="elementalcollision/claude-daemon",
        foreign_base="develop",
        audit_path=audit,
        push_runner=lambda cmd: (pushed.append(cmd) or (True, "")),
        gh_runner=lambda cmd: (
            captured_gh.append(cmd) or (True, "https://github.com/elementalcollision/claude-daemon/pull/7", "")
        ),
    )
    assert result.ok, result.validation_errors
    # Push goes to the explicit HTTPS URL, NOT origin, and only the soak branch.
    push = pushed[0]
    assert "origin" not in push
    assert "https://github.com/elementalcollision/claude-daemon.git" in push
    assert push[-1] == f"{result.branch}:{result.branch}"
    # gh targets the foreign repo, on its base, still draft.
    gh = captured_gh[0]
    assert "--repo" in gh and "elementalcollision/claude-daemon" in gh
    assert gh[gh.index("--base") + 1] == "develop"
    assert "--draft" in gh
    # Audit tags the foreign target.
    rows = [json.loads(ln) for ln in audit.read_text().splitlines() if ln.strip()]
    assert rows[-1]["event"] == "submit_pr.success"
    assert rows[-1]["foreign"] is True
    assert rows[-1]["target_repo"] == "elementalcollision/claude-daemon"


def test_submit_pr_self_path_unchanged_when_not_foreign(tmp_path: Path) -> None:
    # Regression: foreign_repo unset → push to origin, no --repo, base unchanged.
    repo = tmp_path / "repo"
    _init_repo(repo)
    _make_soak_worktree(repo)
    _commit(repo, "chimera/x.py", "x=1\n", "[agent] add x")
    _commit(repo, "tests/test_x.py", "def t(): pass\n", "[agent] test x")

    pushed: list[list[str]] = []
    captured_gh: list[list[str]] = []
    result = submit_pr(
        worktree=repo, repo_root=repo, base="main",
        audit_path=tmp_path / "a.jsonl",
        push_runner=lambda cmd: (pushed.append(cmd) or (True, "")),
        gh_runner=lambda cmd: (captured_gh.append(cmd) or (True, "url", "")),
    )
    assert result.ok
    assert "origin" in pushed[0]
    assert "--repo" not in captured_gh[0]
    assert captured_gh[0][captured_gh[0].index("--base") + 1] == "main"


def test_validate_foreign_skips_chimera_specific_gates(tmp_path: Path) -> None:
    # B.4e: validate(foreign=True) skips the chimera-layout fix-without-test gate
    # (chimera/ source touched without a tests/ counterpart) that self-mode enforces.
    repo = tmp_path / "repo"
    _init_repo(repo)
    _make_soak_worktree(repo)
    _commit(repo, "chimera/x.py", "x = 1\n", "[agent] add x (no test)")
    _, _, self_errors = validate(repo, base="main", foreign=False)
    assert any("fix_without_test" in e for e in self_errors), self_errors
    _, _, foreign_errors = validate(repo, base="main", foreign=True)
    assert not any("fix_without_test" in e for e in foreign_errors), foreign_errors


def test_foreign_push_env_strips_provider_keys_keeps_vcs_auth(monkeypatch) -> None:
    # The foreign push/PR subprocess env strips LLM/provider secrets but KEEPS
    # the VCS auth tokens git/gh need (review #3 — the naive full-strip would
    # drop GH_TOKEN and break auth).
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
    monkeypatch.setenv("GH_TOKEN", "gho_xxx")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_yyy")
    env = _foreign_push_env()
    assert "ANTHROPIC_API_KEY" not in env
    assert "OPENROUTER_API_KEY" not in env
    assert env.get("GH_TOKEN") == "gho_xxx"        # VCS auth preserved
    assert env.get("GITHUB_TOKEN") == "ghp_yyy"
    assert "PATH" in env                            # operational var preserved


def test_submit_pr_validation_failure_skips_push(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _make_soak_worktree(repo)
    # fix_without_test violation:
    _commit(repo, "chimera/x.py", "x=1\n", "[agent] add x")

    audit = tmp_path / "audit.jsonl"
    push_calls: list = []
    gh_calls: list = []

    result = submit_pr(
        worktree=repo, repo_root=repo,
        audit_path=audit,
        push_runner=lambda cmd: (push_calls.append(cmd) or (True, "")),
        gh_runner=lambda cmd: (gh_calls.append(cmd) or (True, "", "")),
    )
    assert not result.ok
    assert push_calls == []
    assert gh_calls == []
    rows = [json.loads(ln) for ln in audit.read_text().splitlines() if ln.strip()]
    assert rows[-1]["event"] == "submit_pr.reject"


def test_submit_pr_push_failure_short_circuits(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _make_soak_worktree(repo)
    _commit(repo, "chimera/x.py", "x=1\n", "[agent] add x")
    _commit(repo, "tests/test_x.py", "def t(): pass\n", "[agent] test x")

    audit = tmp_path / "audit.jsonl"
    gh_calls: list = []

    result = submit_pr(
        worktree=repo, repo_root=repo,
        audit_path=audit,
        push_runner=lambda cmd: (False, "remote rejected: no-push://"),
        gh_runner=lambda cmd: (gh_calls.append(cmd) or (True, "", "")),
    )
    assert not result.ok
    assert gh_calls == []
    assert any("git push failed" in e for e in result.validation_errors)


def test_submit_pr_no_draft_flag(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)
    _make_soak_worktree(repo)
    _commit(repo, "chimera/x.py", "x=1\n", "[agent] add x")
    _commit(repo, "tests/test_x.py", "def t(): pass\n", "[agent] test x")

    captured: list[list[str]] = []
    submit_pr(
        worktree=repo, repo_root=repo,
        draft=False,
        audit_path=tmp_path / "a.jsonl",
        push_runner=lambda cmd: (True, ""),
        gh_runner=lambda cmd: (captured.append(cmd) or (True, "url", "")),
    )
    assert "--draft" not in captured[0]


def test_entropy_skips_identifiers_flags_secrets():
    """The entropy heuristic must not false-positive on long snake_case
    identifiers (e.g. test function names ≥40 chars) while still catching real
    base64/hex secrets (Create self-PR finding, 2026-06-02)."""
    from chimera.core.submit_pr import _entropy_hits
    ident_diff = "+    def test_parse_line_with_tabs_only_in_fields(self):\n"
    assert _entropy_hits(ident_diff) == []
    secret_diff = '+    KEY = "AKIAIOSFODNN7EXAMPLEwJalrXUtnFEMIK7MDENGbPxRfiCY"\n'
    assert _entropy_hits(secret_diff) != []


def test_fix_without_test_accepts_existing_test(tmp_path):
    """A lint cleanup of source that ALREADY has a test file is covered even with
    no test change (2026-06-03 e2e: source ruff cleanup blocked the self-PR)."""
    from chimera.core.submit_pr import _check_fix_without_test
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_kfm_tool.py").write_text("def test_x(): pass\n")
    changed = ["chimera/server/kfm_tool.py"]
    assert _check_fix_without_test(changed, tmp_path) == []   # existing test → covered
    # Net-new source with NO test file is still flagged.
    assert _check_fix_without_test(["chimera/server/newmod.py"], tmp_path) == \
        ["chimera/server/newmod.py"]
    # A changed test still passes everything (original behaviour).
    assert _check_fix_without_test(
        ["chimera/server/newmod.py", "tests/test_newmod.py"], tmp_path) == []
