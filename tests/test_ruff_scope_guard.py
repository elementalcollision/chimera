"""ADR 0186 B.4h — the ruff charter-scope guard (pure decision logic).

Confines the agent's `ruff --fix` / `ruff format` to the locked charter allowlist,
so it can never run tree-wide on a foreign repo (the B.4g root cause)."""

from __future__ import annotations

import pytest

from chimera.core.ruff_scope import (
    _is_mutating,
    _operands,
    ruff_scope_violation,
    ruff_subargv,
)

ALLOW = ("tools/noop_probe.py", "tests/test_noop_probe.py")


# ── ruff_subargv: recognise ruff across runner wrappers ─────────────


@pytest.mark.parametrize(
    "argv,expected",
    [
        (["uv", "run", "ruff", "check", "--fix"], ["ruff", "check", "--fix"]),
        (["ruff", "check", "--fix", "x.py"], ["ruff", "check", "--fix", "x.py"]),
        (["uvx", "ruff", "format"], ["ruff", "format"]),
        (["python", "-m", "ruff", "check"], ["ruff", "check"]),
        (["uv", "run", "--extra", "dev", "ruff", "check"], ["ruff", "check"]),
    ],
)
def test_ruff_subargv_detects(argv, expected):
    assert ruff_subargv(argv) == expected


@pytest.mark.parametrize(
    "argv",
    [
        ["uv", "run", "pytest", "-q"],
        ["git", "commit", "-m", "x"],
        ["grep", "-n", "ruff", "file"],  # 'ruff' as a value, program not a runner
        [],
    ],
)
def test_ruff_subargv_ignores_non_ruff(argv):
    assert ruff_subargv(argv) is None


# ── _is_mutating: only file-rewriting forms count ───────────────────


@pytest.mark.parametrize(
    "sub,mutating",
    [
        (["ruff", "check", "--fix"], True),
        (["ruff", "check", "--fix-only", "x.py"], True),
        (["ruff", "--fix", "x.py"], True),  # implicit `check`
        (["ruff", "check"], False),  # report-only
        (["ruff", "check", "x.py"], False),
        (["ruff", "format", "x.py"], True),
        (["ruff", "format", "--check"], False),
        (["ruff", "format", "--diff"], False),
        (["ruff", "version"], False),
    ],
)
def test_is_mutating(sub, mutating):
    assert _is_mutating(sub) is mutating


# ── _operands: skip flags + flag values, honour `--` ────────────────


@pytest.mark.parametrize(
    "sub,operands",
    [
        (["ruff", "check", "--fix"], []),
        (["ruff", "check", "--fix", "a.py", "b.py"], ["a.py", "b.py"]),
        (["ruff", "check", "--fix", "--select", "F401", "a.py"], ["a.py"]),
        (["ruff", "check", "--fix", "--config", "ruff.toml", "a.py"], ["a.py"]),
        (["ruff", "check", "--fix", "--select=F401", "a.py"], ["a.py"]),  # inline value
        (["ruff", "check", "--fix", "--", "a.py"], ["a.py"]),
        (["ruff", "check", "--fix", "."], ["."]),
    ],
)
def test_operands(sub, operands):
    assert _operands(sub) == operands


# ── ruff_scope_violation: the decision ──────────────────────────────


def test_tree_wide_is_blocked():
    v = ruff_scope_violation(["uv", "run", "ruff", "check", "--fix"], ALLOW)
    assert v is not None and "TREE-WIDE" in v


def test_dot_operand_is_blocked():
    v = ruff_scope_violation(["uv", "run", "ruff", "check", "--fix", "."], ALLOW)
    assert v is not None and "out-of-charter" in v


def test_out_of_scope_file_is_blocked():
    v = ruff_scope_violation(
        ["uv", "run", "ruff", "check", "--fix", "daemon/api.py"], ALLOW
    )
    assert v is not None and "daemon/api.py" in v


def test_in_scope_files_allowed():
    assert (
        ruff_scope_violation(
            ["uv", "run", "ruff", "check", "--fix", *ALLOW], ALLOW
        )
        is None
    )


def test_in_scope_with_dotslash_normalised():
    assert (
        ruff_scope_violation(
            ["uv", "run", "ruff", "check", "--fix", "./tools/noop_probe.py"],
            ALLOW,
        )
        is None
    )


def test_flag_value_not_mistaken_for_path():
    # F401 is the value of --select, not an out-of-scope path.
    assert (
        ruff_scope_violation(
            [
                "uv", "run", "ruff", "check", "--fix",
                "--select", "F401", "tools/noop_probe.py",
            ],
            ALLOW,
        )
        is None
    )


def test_report_only_check_never_blocked_even_tree_wide():
    # `ruff check` (no --fix) only reports — safe to run anywhere.
    assert ruff_scope_violation(["uv", "run", "ruff", "check"], ALLOW) is None


def test_format_tree_wide_blocked_but_scoped_ok():
    assert ruff_scope_violation(["uv", "run", "ruff", "format"], ALLOW) is not None
    assert (
        ruff_scope_violation(
            ["uv", "run", "ruff", "format", "tools/noop_probe.py"], ALLOW
        )
        is None
    )


def test_no_allowlist_is_conservative_allow():
    # Outside a scoped soak there is no charter to enforce → do not block.
    assert ruff_scope_violation(["uv", "run", "ruff", "check", "--fix"], ()) is None


def test_non_ruff_command_ignored():
    assert ruff_scope_violation(["uv", "run", "pytest", "-q"], ALLOW) is None


# ── B.4h review M1: --add-noqa is a mutating mode ───────────────────


@pytest.mark.parametrize(
    "sub", [["ruff", "check", "--add-noqa"], ["ruff", "check", "--add-noqa=needed"]]
)
def test_add_noqa_is_mutating(sub):
    assert _is_mutating(sub) is True


def test_add_noqa_tree_wide_blocked():
    v = ruff_scope_violation(["uv", "run", "ruff", "check", "--add-noqa"], ALLOW)
    assert v is not None and "TREE-WIDE" in v


def test_add_noqa_scoped_allowed():
    assert (
        ruff_scope_violation(
            ["uv", "run", "ruff", "check", "--add-noqa", "tools/noop_probe.py"],
            ALLOW,
        )
        is None
    )


# ── B.4h review M2: wrapper flag-values must not defeat detection ────


@pytest.mark.parametrize(
    "argv",
    [
        ["uv", "run", "--with", "ruff", "ruff", "check", "--fix"],
        ["uvx", "--from", "ruff", "ruff", "check", "--fix"],
        ["uv", "run", "python", "-m", "ruff", "check", "--fix"],
        ["uv", "tool", "run", "ruff", "check", "--fix"],
    ],
)
def test_wrapper_value_ruff_still_detected_and_blocked(argv):
    sub = ruff_subargv(argv)
    assert sub is not None and sub[0] == "ruff" and sub[1] == "check"
    assert ruff_scope_violation(argv, ALLOW) is not None


def test_wrapper_with_ruff_dep_running_other_tool_ignored():
    # `uv run --with ruff pytest` runs pytest (ruff is just a dep) → not a ruff cmd.
    assert ruff_subargv(["uv", "run", "--with", "ruff", "pytest"]) is None


# ── B.4h review M3: value-flag completeness (bypass + false-positive) ─


def test_output_file_value_not_an_operand_so_tree_wide_blocked():
    # out.txt is --output-file's value, not a path operand; with no FILE operand
    # ruff falls back to '.', so this is a tree-wide --fix → must block.
    v = ruff_scope_violation(
        ["uv", "run", "ruff", "check", "--fix", "--output-file", "out.txt"], ALLOW
    )
    assert v is not None and "TREE-WIDE" in v


def test_color_value_not_mistaken_for_path():
    # `--color never` must not make 'never' a phantom out-of-charter operand.
    assert (
        ruff_scope_violation(
            ["uv", "run", "ruff", "check", "--fix", "--color", "never",
             "tools/noop_probe.py"],
            ALLOW,
        )
        is None
    )


# ── B.4h review should-fix: --diff previews, never mutates ───────────


def test_check_fix_diff_is_preview_not_blocked():
    assert _is_mutating(["ruff", "check", "--fix", "--diff"]) is False
    assert (
        ruff_scope_violation(["uv", "run", "ruff", "check", "--fix", "--diff"], ALLOW)
        is None
    )


def test_no_fix_disables_mutation():
    assert _is_mutating(["ruff", "check", "--fix", "--no-fix"]) is False


# ── integration: the guard fires through shell_handler ──────────────


def _repo_with_charter(tmp_path):
    import subprocess

    repo = tmp_path / "repo"
    (repo / "mind" / "research").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", repo], check=True, capture_output=True)
    (repo / "mind" / "research" / "realtask-x-design.md").write_text(
        "# scope\n\n## READY-FOR-REMEDIATION\n\n"
        "Allowed scope:\n\n- `tools/noop_probe.py`\n- `tests/test_noop_probe.py`\n"
    )
    return repo


@pytest.mark.asyncio
async def test_shell_handler_blocks_tree_wide_ruff(tmp_path, monkeypatch):
    from chimera.tools.dispatch import DispatchContext
    from chimera.tools.shell import shell_handler

    repo = _repo_with_charter(tmp_path)
    monkeypatch.setenv("CHIMERA_MIND_DIR", str(repo))
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(repo))
    monkeypatch.delenv("CHIMERA_ALLOW_UNSCOPED_RUFF", raising=False)

    with pytest.raises(PermissionError, match="B.4h"):
        await shell_handler(
            {"argv": ["uv", "run", "ruff", "check", "--fix"], "cwd": str(repo)},
            DispatchContext(elevated=True),
        )


@pytest.mark.asyncio
async def test_shell_handler_override_lets_unscoped_ruff_through(tmp_path, monkeypatch):
    # With the operator override set, the guard is inert (it then proceeds to exec,
    # which we don't care about — we only assert the guard did NOT raise).
    from chimera.tools.dispatch import DispatchContext
    from chimera.tools.shell import shell_handler

    repo = _repo_with_charter(tmp_path)
    monkeypatch.setenv("CHIMERA_MIND_DIR", str(repo))
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(repo))
    monkeypatch.setenv("CHIMERA_ALLOW_UNSCOPED_RUFF", "1")

    try:
        await shell_handler(
            {"argv": ["uv", "run", "ruff", "version"], "cwd": str(repo)},
            DispatchContext(elevated=True),
        )
    except PermissionError as exc:  # the scope guard must NOT be the blocker
        assert "B.4h" not in str(exc)
