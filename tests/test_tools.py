"""Tests for the tool registry, dispatch pipeline, and shell tool."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chimera.tools import (
    DispatchContext,
    Dispatcher,
    SAFE_COMMANDS,
    ToolDenied,
    ToolRegistry,
    register_shell_tool,
)
from chimera.tools.dispatch import PolicyDecision, add_global_deny, clear_global_deny
from chimera.tools.shell import shell_handler


# ── Registry ────────────────────────────────────────────────


async def _trivial_handler(args, context):
    return "ok"


def _make_schema(name: str) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": "test",
            "parameters": {"type": "object", "properties": {}},
        },
    }


def test_register_and_retrieve():
    reg = ToolRegistry()
    reg.register(name="t", toolset="core", schema=_make_schema("t"), handler=_trivial_handler)
    entry = reg.get("t")
    assert entry is not None
    assert entry.toolset == "core"
    assert "t" in reg.names()


def test_double_register_without_override_raises():
    reg = ToolRegistry()
    reg.register(name="t", toolset="core", schema=_make_schema("t"), handler=_trivial_handler)
    with pytest.raises(ValueError):
        reg.register(name="t", toolset="core", schema=_make_schema("t"), handler=_trivial_handler)


def test_override_allows_re_register():
    reg = ToolRegistry()
    reg.register(name="t", toolset="core", schema=_make_schema("t"), handler=_trivial_handler)
    reg.register(
        name="t", toolset="core", schema=_make_schema("t"), handler=_trivial_handler, override=True
    )
    assert reg.get("t") is not None


def test_check_fn_cached_uses_ttl():
    calls = {"n": 0}

    def probe() -> bool:
        calls["n"] += 1
        return True

    reg = ToolRegistry(check_ttl_seconds=10.0)
    reg.register(
        name="t",
        toolset="core",
        schema=_make_schema("t"),
        handler=_trivial_handler,
        check_fn=probe,
    )
    # First call probes; subsequent calls within TTL hit the cache.
    assert reg.is_available("t")
    assert reg.is_available("t")
    assert reg.is_available("t")
    assert calls["n"] == 1


def test_check_fn_exception_treated_as_unavailable():
    def bad_probe() -> bool:
        raise RuntimeError("boom")

    reg = ToolRegistry()
    reg.register(
        name="t",
        toolset="core",
        schema=_make_schema("t"),
        handler=_trivial_handler,
        check_fn=bad_probe,
    )
    assert reg.is_available("t") is False


def test_schemas_excludes_unavailable_by_default():
    reg = ToolRegistry()
    reg.register(
        name="t_off",
        toolset="core",
        schema=_make_schema("t_off"),
        handler=_trivial_handler,
        check_fn=lambda: False,
    )
    reg.register(name="t_on", toolset="core", schema=_make_schema("t_on"), handler=_trivial_handler)
    visible = [s["function"]["name"] for s in reg.schemas()]
    assert visible == ["t_on"]
    visible_all = [s["function"]["name"] for s in reg.schemas(include_unavailable=True)]
    assert set(visible_all) == {"t_off", "t_on"}


# ── Dispatch policy pipeline ────────────────────────────────


@pytest.fixture(autouse=True)
def _clear_global_deny():
    clear_global_deny()
    yield
    clear_global_deny()


def test_policy_unknown_tool_denied():
    reg = ToolRegistry()
    d = Dispatcher(reg)
    r = d.check_policy("nope", DispatchContext())
    assert r.decision is PolicyDecision.DENY
    assert r.layer == "registry"


def test_policy_global_deny():
    reg = ToolRegistry()
    reg.register(name="t", toolset="core", schema=_make_schema("t"), handler=_trivial_handler)
    add_global_deny("t")
    r = Dispatcher(reg).check_policy("t", DispatchContext())
    assert not r.allowed and r.layer == "global_deny"


def test_policy_context_deny():
    reg = ToolRegistry()
    reg.register(name="t", toolset="core", schema=_make_schema("t"), handler=_trivial_handler)
    r = Dispatcher(reg).check_policy("t", DispatchContext(deny=frozenset({"t"})))
    assert not r.allowed and r.layer == "context_deny"


def test_policy_context_allow_list_excludes_others():
    reg = ToolRegistry()
    reg.register(name="t", toolset="core", schema=_make_schema("t"), handler=_trivial_handler)
    reg.register(name="u", toolset="core", schema=_make_schema("u"), handler=_trivial_handler)
    d = Dispatcher(reg)
    ctx = DispatchContext(allow=frozenset({"u"}))
    assert d.check_policy("t", ctx).layer == "context_allow"
    assert d.check_policy("u", ctx).allowed


def test_policy_requires_env(monkeypatch):
    monkeypatch.delenv("CHIMERA_TEST_REQUIRED", raising=False)
    reg = ToolRegistry()
    reg.register(
        name="t",
        toolset="core",
        schema=_make_schema("t"),
        handler=_trivial_handler,
        requires_env=("CHIMERA_TEST_REQUIRED",),
    )
    assert Dispatcher(reg).check_policy("t", DispatchContext()).layer == "requires_env"
    monkeypatch.setenv("CHIMERA_TEST_REQUIRED", "1")
    assert Dispatcher(reg).check_policy("t", DispatchContext()).allowed


def test_policy_availability_via_check_fn():
    reg = ToolRegistry()
    reg.register(
        name="t",
        toolset="core",
        schema=_make_schema("t"),
        handler=_trivial_handler,
        check_fn=lambda: False,
    )
    assert Dispatcher(reg).check_policy("t", DispatchContext()).layer == "availability"


@pytest.mark.asyncio
async def test_dispatch_truncates_long_results():
    async def big_handler(args, ctx):
        return "A" * 50_000

    reg = ToolRegistry()
    reg.register(
        name="big",
        toolset="core",
        schema=_make_schema("big"),
        handler=big_handler,
        max_result_size_chars=1000,
    )
    out = await Dispatcher(reg).dispatch("big", {}, DispatchContext())
    assert len(out) <= 1000 + len("\n[truncated]")
    assert out.endswith("[truncated]")


@pytest.mark.asyncio
async def test_dispatch_raises_tool_denied_on_deny():
    reg = ToolRegistry()
    reg.register(name="t", toolset="core", schema=_make_schema("t"), handler=_trivial_handler)
    add_global_deny("t")
    with pytest.raises(ToolDenied):
        await Dispatcher(reg).dispatch("t", {}, DispatchContext())


# ── Shell tool ──────────────────────────────────────────────


@pytest.fixture
def shell_env(tmp_path: Path, monkeypatch):
    """Point CHIMERA_MIND_DIR + CHIMERA_STATE_DIR at temp paths."""
    mind = tmp_path / "mind"
    state = tmp_path / "state"
    mind.mkdir()
    state.mkdir()
    monkeypatch.setenv("CHIMERA_MIND_DIR", str(mind))
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(state))
    return mind, state


def test_shell_safe_commands_is_nonempty():
    assert "ls" in SAFE_COMMANDS
    assert "cat" in SAFE_COMMANDS
    assert len(SAFE_COMMANDS) >= 10


def test_shell_allowlist_includes_v4_108_additions():
    """v4.108 (soak v13): du/diff/sort/uniq/comm landed for the
    soak-v10-surfaced phase-2 work needs. They must be members of
    SAFE_COMMANDS whenever they're present on PATH (the runner
    filters via _resolved_allowlist), which is true on every
    standard Linux/macOS installation.
    """
    import shutil
    for cmd in ("du", "diff", "sort", "uniq", "comm"):
        if shutil.which(cmd) is None:
            # Skip — host doesn't have the binary; the runtime
            # filter excludes it from SAFE_COMMANDS by design.
            continue
        assert cmd in SAFE_COMMANDS, (
            f"{cmd!r} on PATH but missing from SAFE_COMMANDS "
            f"(check RAW_ALLOWLIST in chimera/tools/shell.py)"
        )


@pytest.mark.asyncio
async def test_shell_runs_safe_command(shell_env):
    mind, _ = shell_env
    (mind / "hello.txt").write_text("howdy\n")
    # v4.4: default cwd is now the repo root (mind+state's common parent),
    # so an explicit "mind" cwd is needed to see hello.txt.
    out = await shell_handler(
        {"argv": ["ls", "."], "cwd": "mind"}, DispatchContext()
    )
    assert "hello.txt" in out
    assert "[exit=0]" in out


@pytest.mark.asyncio
async def test_shell_wrapper_rejection_teaches_argv_form():
    """A `bash -c "..."` attempt (the agent's common mistake in self-determination
    soaks) is refused with a CORRECTIVE message that shows the right argv form,
    not a bare 'not in allow-list'."""
    with pytest.raises(PermissionError) as ei:
        await shell_handler(
            {"argv": ["bash", "-c", "ruff check --fix x.py"]}, DispatchContext()
        )
    msg = str(ei.value)
    assert "single binary" in msg
    assert "argv=" in msg                # shows the correct form
    assert "uv" in msg and "ruff" in msg  # the worked example
    # sh is treated the same way.
    with pytest.raises(PermissionError) as ei2:
        await shell_handler({"argv": ["sh", "-c", "echo hi"]}, DispatchContext())
    assert "NOT a shell" in str(ei2.value)


@pytest.mark.asyncio
async def test_shell_uv_run_tool_hints_the_uv_run_form():
    """A bare dev tool (`ruff`) — the agent's next move after dropping `bash` —
    is refused with a hint to use the `uv run` form, in one hop."""
    with pytest.raises(PermissionError) as ei:
        await shell_handler(
            {"argv": ["ruff", "check", "--fix", "x.py"]}, DispatchContext()
        )
    msg = str(ei.value)
    assert "uv" in msg and "run" in msg
    assert 'argv=["uv", "run", \'ruff\'' in msg or "uv\", \"run\", 'ruff'" in msg \
        or "'ruff'" in msg  # hints the uv run <tool> form
    # pytest gets the same treatment.
    with pytest.raises(PermissionError) as ei2:
        await shell_handler({"argv": ["pytest", "-q"]}, DispatchContext())
    assert "uv" in str(ei2.value) and "runs via" in str(ei2.value)


@pytest.mark.asyncio
async def test_shell_non_wrapper_unknown_command_keeps_plain_message():
    """A non-wrapper, non-uv-run unknown binary still gets the plain refusal."""
    with pytest.raises(PermissionError) as ei:
        await shell_handler({"argv": ["curl", "https://x"]}, DispatchContext())
    assert "not in shell allow-list" in str(ei.value)


@pytest.mark.asyncio
async def test_shell_calls_test_run_ledger_with_exit_and_duration(shell_env, monkeypatch):
    """v40 wiring: shell_handler passes argv + exit_code + duration_ms +
    timed_out to record_test_run on a normal (non-timeout) completion.
    (The test-command filtering itself is unit-tested in test_soak_ledger.)"""
    captured = {}

    def _spy(**kwargs):
        captured.update(kwargs)
        return None

    monkeypatch.setattr("chimera.core.soak_ledger.record_test_run", _spy)
    out = await shell_handler({"argv": ["ls", "."], "cwd": "mind"}, DispatchContext())
    assert "[exit=0]" in out
    assert captured["argv"] == ["ls", "."]
    assert captured["exit_code"] == 0
    assert captured["timed_out"] is False
    assert captured["duration_ms"] >= 0.0


@pytest.mark.asyncio
async def test_shell_rejects_unlisted_command_without_elevation(shell_env):
    with pytest.raises(PermissionError):
        await shell_handler({"argv": ["bash", "-c", "echo nope"]}, DispatchContext())


@pytest.mark.asyncio
async def test_shell_allows_unlisted_with_elevation(shell_env):
    out = await shell_handler(
        {"argv": ["bash", "-c", "echo elevated"]}, DispatchContext(elevated=True)
    )
    assert "elevated" in out
    assert "[exit=0]" in out


# ── ADR 0151 R5 forced-stall lever ──────────────────────────────────


@pytest.mark.asyncio
async def test_force_stall_blocks_commit_in_soak(shell_env, monkeypatch):
    """CHIMERA_SOAK_FORCE_STALL=1 inside a soak refuses git commit so phase 2
    idles to max iterations (the forced-stall A/B). engines ON, trust not T0."""
    monkeypatch.setenv("CHIMERA_ENGINES_ENABLED", "1")
    monkeypatch.setenv("CHIMERA_SOAK_RUN_ID", "force-stall-test")
    monkeypatch.setenv("CHIMERA_SOAK_FORCE_STALL", "1")
    with pytest.raises(PermissionError, match="CHIMERA_SOAK_FORCE_STALL"):
        await shell_handler(
            {"argv": ["git", "commit", "-m", "[agent] x"]}, DispatchContext(),
        )


@pytest.mark.asyncio
async def test_force_stall_noop_outside_soak(shell_env, monkeypatch):
    """The lever is double-gated: without CHIMERA_SOAK_RUN_ID it must NOT fire
    (it can never block a normal `chimera run`). git is allow-listed, so the
    commit proceeds to subprocess and fails for an ordinary reason — never the
    force-stall PermissionError."""
    monkeypatch.setenv("CHIMERA_ENGINES_ENABLED", "1")
    monkeypatch.delenv("CHIMERA_SOAK_RUN_ID", raising=False)
    monkeypatch.setenv("CHIMERA_SOAK_FORCE_STALL", "1")
    try:
        out = await shell_handler(
            {"argv": ["git", "commit", "--allow-empty", "-m", "x"]},
            DispatchContext(),
        )
    except PermissionError as exc:  # pragma: no cover - must not be force-stall
        assert "CHIMERA_SOAK_FORCE_STALL" not in str(exc)
    else:
        assert "CHIMERA_SOAK_FORCE_STALL" not in out


@pytest.mark.asyncio
async def test_force_stall_off_by_default(shell_env, monkeypatch):
    """In a soak but with the lever unset, git commit is NOT force-blocked."""
    monkeypatch.setenv("CHIMERA_ENGINES_ENABLED", "1")
    monkeypatch.setenv("CHIMERA_SOAK_RUN_ID", "no-stall")
    monkeypatch.delenv("CHIMERA_SOAK_FORCE_STALL", raising=False)
    try:
        out = await shell_handler(
            {"argv": ["git", "commit", "--allow-empty", "-m", "x"]},
            DispatchContext(),
        )
    except PermissionError as exc:  # pragma: no cover
        assert "CHIMERA_SOAK_FORCE_STALL" not in str(exc)
    else:
        assert "CHIMERA_SOAK_FORCE_STALL" not in out


def test_shell_default_cwd_is_common_parent_of_mind_and_state(shell_env, tmp_path):
    """v4.4 / L-2: default cwd is the parent of mind/+state/, so relative
    paths 'state/x' and 'mind/x' both resolve to the right place."""
    from chimera.tools.shell import _default_cwd, _resolve_cwd
    assert _default_cwd() == tmp_path.resolve()
    # Relative 'state/...' from default cwd should land under tmp_path/state.
    assert _resolve_cwd("state") == (tmp_path / "state").resolve()
    assert _resolve_cwd("mind") == (tmp_path / "mind").resolve()


def test_shell_default_cwd_falls_back_when_no_common_parent(monkeypatch, tmp_path):
    """When mind and state don't share a parent, default cwd falls back to mind."""
    mind = tmp_path / "alpha" / "mind"
    state = tmp_path / "beta" / "state"
    mind.mkdir(parents=True)
    state.mkdir(parents=True)
    monkeypatch.setenv("CHIMERA_MIND_DIR", str(mind))
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(state))
    from chimera.tools.shell import _allowed_roots, _default_cwd
    assert len(_allowed_roots()) == 2  # no common parent → no third root
    assert _default_cwd() == mind.resolve()


@pytest.mark.asyncio
async def test_shell_ls_at_default_cwd_sees_both_mind_and_state(shell_env, tmp_path):
    """Sanity: running an allow-listed command at the default cwd lists
    both mind/ and state/ as siblings."""
    out = await shell_handler({"argv": ["ls", "."]}, DispatchContext())
    assert "mind" in out
    assert "state" in out


@pytest.mark.asyncio
async def test_shell_rejects_cwd_outside_roots(shell_env, tmp_path, tmp_path_factory):
    # v4.4: must be outside tmp_path entirely, since tmp_path is now the
    # common parent of mind+state and therefore an allowed root.
    outside = tmp_path_factory.mktemp("truly-outside")
    with pytest.raises(ValueError, match="outside allowed roots"):
        await shell_handler(
            {"argv": ["ls", "."], "cwd": str(outside)}, DispatchContext()
        )


@pytest.mark.asyncio
async def test_shell_rejects_empty_argv():
    with pytest.raises(ValueError):
        await shell_handler({"argv": []}, DispatchContext())


@pytest.mark.asyncio
async def test_shell_rejects_non_string_argv_items():
    with pytest.raises(ValueError):
        await shell_handler({"argv": ["ls", 42]}, DispatchContext())


def test_resolved_allowlist_filters_missing_tools(monkeypatch):
    """v4.80: tools absent from PATH must not appear in the advertised
    allow-list, so the model never wastes a round calling them."""
    import chimera.tools.shell as shell_mod

    def fake_which(cmd: str) -> str | None:
        if cmd == "rg":
            return None
        return f"/usr/bin/{cmd}"

    monkeypatch.setattr(shell_mod.shutil, "which", fake_which)
    resolved = shell_mod._resolved_allowlist()
    assert "rg" not in resolved
    assert "ls" in resolved
    assert "grep" in resolved


@pytest.mark.asyncio
async def test_shell_permission_error_reflects_resolved_allowlist(shell_env):
    """PermissionError surface must show the trimmed allow-list — what the
    model can actually call — not the raw advertised set."""
    import chimera.tools.shell as shell_mod

    with pytest.raises(PermissionError) as ei:
        await shell_handler({"argv": ["bash", "-c", "echo no"]}, DispatchContext())
    msg = str(ei.value)
    assert "bash" in msg
    for cmd in sorted(shell_mod.SAFE_COMMANDS):
        assert repr(cmd) in msg or cmd in msg


@pytest.mark.asyncio
async def test_shell_handles_missing_program(shell_env):
    with pytest.raises(FileNotFoundError):
        await shell_handler(
            {"argv": ["definitely_not_a_real_program_xyz"]},
            DispatchContext(elevated=True),
        )


@pytest.mark.asyncio
async def test_shell_timeout(shell_env):
    out = await shell_handler(
        {"argv": ["sleep", "5"], "timeout_s": 0.2},
        DispatchContext(elevated=True),
    )
    assert "[timeout" in out


# ── End-to-end via dispatcher ───────────────────────────────


# ── Engines-off git commit/push guard (soak v20) ───────────


@pytest.mark.asyncio
async def test_shell_blocks_git_commit_when_engines_off(shell_env, monkeypatch):
    monkeypatch.setenv("CHIMERA_ENGINES_ENABLED", "0")
    with pytest.raises(PermissionError, match="CHIMERA_ENGINES_ENABLED=0"):
        await shell_handler(
            {"argv": ["git", "commit", "-m", "foo"]}, DispatchContext()
        )


@pytest.mark.asyncio
async def test_shell_blocks_git_push_when_engines_off(shell_env, monkeypatch):
    monkeypatch.setenv("CHIMERA_ENGINES_ENABLED", "0")
    with pytest.raises(PermissionError, match="CHIMERA_ENGINES_ENABLED=0"):
        await shell_handler(
            {"argv": ["git", "push"]}, DispatchContext()
        )


@pytest.mark.asyncio
async def test_shell_allows_git_status_when_engines_off(shell_env, monkeypatch):
    """Only commit/push are blocked; read-only git subcommands pass."""
    monkeypatch.setenv("CHIMERA_ENGINES_ENABLED", "0")
    # git status against an arbitrary cwd may exit non-zero (not a repo),
    # but the call must not be rejected by the guard.
    out = await shell_handler({"argv": ["git", "status"]}, DispatchContext())
    assert "$ git status" in out


@pytest.mark.asyncio
async def test_shell_allows_git_commit_when_engines_on(shell_env, monkeypatch):
    """When engines are on, the guard is inactive — git commit reaches
    subprocess (and fails naturally because shell_env isn't a repo)."""
    monkeypatch.setenv("CHIMERA_ENGINES_ENABLED", "1")
    out = await shell_handler(
        {"argv": ["git", "commit", "-m", "foo"]}, DispatchContext()
    )
    assert "$ git commit -m foo" in out


@pytest.mark.asyncio
async def test_shell_allows_git_commit_when_engines_unset(shell_env, monkeypatch):
    monkeypatch.delenv("CHIMERA_ENGINES_ENABLED", raising=False)
    out = await shell_handler(
        {"argv": ["git", "commit", "-m", "foo"]}, DispatchContext()
    )
    assert "$ git commit -m foo" in out


# ── Trust-T0 git commit/push gate (v4.117 / ADR 0117) ──────


def _write_trust_state(state_dir: Path, tier: int) -> None:
    (state_dir / "trust_state.json").write_text(
        json.dumps({"current_tier": tier})
    )


@pytest.mark.asyncio
async def test_shell_blocks_git_commit_at_trust_T0(shell_env, monkeypatch):
    _, state = shell_env
    monkeypatch.delenv("CHIMERA_ENGINES_ENABLED", raising=False)
    _write_trust_state(state, 0)
    with pytest.raises(PermissionError, match="trust state is T0"):
        await shell_handler(
            {"argv": ["git", "commit", "-m", "foo"]}, DispatchContext()
        )


@pytest.mark.asyncio
async def test_shell_blocks_git_push_at_trust_T0(shell_env, monkeypatch):
    _, state = shell_env
    monkeypatch.delenv("CHIMERA_ENGINES_ENABLED", raising=False)
    _write_trust_state(state, 0)
    with pytest.raises(PermissionError, match="trust state is T0"):
        await shell_handler({"argv": ["git", "push"]}, DispatchContext())


@pytest.mark.asyncio
async def test_shell_allows_git_status_at_trust_T0(shell_env, monkeypatch):
    """Only commit/push are gated by trust tier; read-only git is fine."""
    _, state = shell_env
    monkeypatch.delenv("CHIMERA_ENGINES_ENABLED", raising=False)
    _write_trust_state(state, 0)
    out = await shell_handler({"argv": ["git", "status"]}, DispatchContext())
    assert "$ git status" in out


@pytest.mark.asyncio
async def test_shell_allows_git_commit_above_T0(shell_env, monkeypatch):
    """T1+ passes the trust gate; subprocess fires (and fails naturally
    because shell_env isn't a repo)."""
    _, state = shell_env
    monkeypatch.delenv("CHIMERA_ENGINES_ENABLED", raising=False)
    _write_trust_state(state, 1)
    out = await shell_handler(
        {"argv": ["git", "commit", "-m", "foo"]}, DispatchContext()
    )
    assert "$ git commit -m foo" in out


@pytest.mark.asyncio
async def test_shell_fails_open_when_trust_state_unreadable(
    shell_env, monkeypatch
):
    """No trust_state.json → don't block boot / first-run."""
    _, state = shell_env
    monkeypatch.delenv("CHIMERA_ENGINES_ENABLED", raising=False)
    assert not (state / "trust_state.json").exists()
    out = await shell_handler(
        {"argv": ["git", "commit", "-m", "foo"]}, DispatchContext()
    )
    assert "$ git commit -m foo" in out


@pytest.mark.asyncio
async def test_shell_fails_open_when_trust_state_malformed(
    shell_env, monkeypatch
):
    _, state = shell_env
    monkeypatch.delenv("CHIMERA_ENGINES_ENABLED", raising=False)
    (state / "trust_state.json").write_text("not json {{{")
    out = await shell_handler(
        {"argv": ["git", "commit", "-m", "foo"]}, DispatchContext()
    )
    assert "$ git commit -m foo" in out


@pytest.mark.asyncio
async def test_register_shell_tool_then_dispatch(shell_env):
    reg = ToolRegistry()
    register_shell_tool(reg)
    (shell_env[0] / "marker.txt").write_text("ok\n")
    out = await Dispatcher(reg).dispatch("shell", {"argv": ["ls", "."], "cwd": "mind"}, DispatchContext())
    assert "marker.txt" in out
