"""Tests for the code_exec tool."""

from __future__ import annotations

from pathlib import Path

import pytest

from chimera.tools import DispatchContext, ToolRegistry, register_code_exec_tool
from chimera.tools.code_exec import code_exec_handler


@pytest.fixture
def shell_env(tmp_path: Path, monkeypatch):
    mind = tmp_path / "mind"
    state = tmp_path / "state"
    mind.mkdir()
    state.mkdir()
    monkeypatch.setenv("CHIMERA_MIND_DIR", str(mind))
    monkeypatch.setenv("CHIMERA_STATE_DIR", str(state))
    return mind, state


def test_register_code_exec_idempotent():
    reg = ToolRegistry()
    register_code_exec_tool(reg)
    register_code_exec_tool(reg)
    assert reg.get("code_exec") is not None


@pytest.mark.asyncio
async def test_code_exec_runs_simple_snippet(shell_env):
    out = await code_exec_handler(
        {"code": "print(6 * 7)"}, DispatchContext()
    )
    assert "42" in out
    assert "[exit=0]" in out


@pytest.mark.asyncio
async def test_code_exec_captures_stderr(shell_env):
    out = await code_exec_handler(
        {"code": "import sys\nprint('hi'); print('boom', file=sys.stderr)"},
        DispatchContext(),
    )
    assert "hi" in out
    assert "[stderr]" in out
    assert "boom" in out
    assert "[exit=0]" in out


@pytest.mark.asyncio
async def test_code_exec_nonzero_exit(shell_env):
    out = await code_exec_handler(
        {"code": "raise SystemExit(2)"}, DispatchContext()
    )
    assert "[exit=2]" in out


@pytest.mark.asyncio
async def test_code_exec_timeout(shell_env):
    out = await code_exec_handler(
        {"code": "import time\nwhile True:\n    time.sleep(0.05)", "timeout_s": 0.3},
        DispatchContext(),
    )
    assert "[timeout" in out


@pytest.mark.asyncio
async def test_code_exec_isolated_mode_drops_pythonpath(shell_env, monkeypatch):
    """``python -I`` should ignore PYTHONPATH."""
    monkeypatch.setenv("PYTHONPATH", "/nonexistent/will/poison")
    out = await code_exec_handler(
        {"code": "import sys\nprint('\\n'.join(sys.path[:3]))"},
        DispatchContext(),
    )
    assert "/nonexistent/will/poison" not in out


@pytest.mark.asyncio
async def test_code_exec_rejects_empty_code():
    with pytest.raises(ValueError):
        await code_exec_handler({"code": ""}, DispatchContext())


@pytest.mark.asyncio
async def test_code_exec_rejects_cwd_outside_roots(shell_env, tmp_path):
    # v4.74: parent of mind+state is now an allowed root, so an
    # "outside" dir must live OUTSIDE that parent — use a parallel
    # sibling of tmp_path, not a child.
    outside = tmp_path.parent / "really-outside-tree"
    outside.mkdir(exist_ok=True)
    try:
        with pytest.raises(ValueError, match="outside allowed roots"):
            await code_exec_handler(
                {"code": "print(1)", "cwd": str(outside)}, DispatchContext()
            )
    finally:
        outside.rmdir()


@pytest.mark.asyncio
async def test_code_exec_can_write_to_mind(shell_env):
    """Snippet with explicit cwd='mind' can create files there."""
    mind, _ = shell_env
    out = await code_exec_handler(
        {"code": "open('marker.txt', 'w').write('here')", "cwd": "mind"},
        DispatchContext(),
    )
    assert "[exit=0]" in out
    assert (mind / "marker.txt").read_text() == "here"


@pytest.mark.asyncio
async def test_code_exec_cwd_mind_does_not_double_prefix(shell_env):
    """v4.74 regression: passing cwd='mind' must not produce mind/mind/.

    Reproduces the 2026-05-20 long-cycle bug where Chimera wrote four
    files into mind/mind/* because _resolve_cwd joined the relative path
    "mind" onto roots[0] (already the resolved mind/ directory).
    """
    mind, _ = shell_env
    # Pretend mind+state share a common parent (tmp_path). When the model
    # passes cwd="mind", it should resolve to mind itself, NOT mind/mind.
    out = await code_exec_handler(
        {
            "code": (
                "from pathlib import Path\n"
                "Path('research').mkdir(exist_ok=True)\n"
                "Path('research/marker.txt').write_text('here')\n"
            ),
            "cwd": "mind",
        },
        DispatchContext(),
    )
    assert "[exit=0]" in out, out
    # The file lands at mind/research/marker.txt, not mind/mind/research/marker.txt.
    assert (mind / "research" / "marker.txt").read_text() == "here"
    assert not (mind / "mind").exists(), \
        f"double-prefix regression: {mind / 'mind'} was created"


@pytest.mark.asyncio
async def test_code_exec_cwd_state_does_not_double_prefix(shell_env):
    """Symmetric check for cwd='state' — same root, same bug shape."""
    _, state = shell_env
    out = await code_exec_handler(
        {
            "code": "from pathlib import Path; Path('marker.txt').write_text('s')",
            "cwd": "state",
        },
        DispatchContext(),
    )
    assert "[exit=0]" in out, out
    assert (state / "marker.txt").read_text() == "s"
    assert not (state / "state").exists()
