"""Regression: ping-pong fires where degenerate_loop does not.

Soak v12: detect_degenerate_loop only catches *consecutive identical*
tool calls. detect_ping_pong catches *alternating* cycles (A→B→A→B).
The act.py wiring calls both guards in sequence.

These tests prove they are complementary, not redundant.
"""

from chimera.tools.loop_guard import LoopVerdict, ToolCall, detect_degenerate_loop, detect_ping_pong


def test_ping_pong_fires_where_degenerate_loop_does_not():
    """A->B->A->B->A->B triggers ping_pong ABORT but degenerate_loop OK."""
    a = ToolCall("mcp-peer-alpha-read_file", {"path": "/var/log"})
    b = ToolCall("mcp-peer-alpha-write_file", {"path": "/var/log", "content": "done"})
    history = [a, b, a, b, a, b]

    assert detect_degenerate_loop(history) is LoopVerdict.OK, (
        "degenerate_loop sees no two consecutive identical calls"
    )
    assert detect_ping_pong(history) is LoopVerdict.ABORT, (
        "ping_pong sees the 3-cycle alternating pattern"
    )


def test_both_fire_on_identical_repeats():
    """AAAAAA triggers both detectors (harmless overlap)."""
    call = ToolCall("shell", {"argv": ["ls"]})
    history = [call] * 6
    assert detect_degenerate_loop(history) is LoopVerdict.ABORT
    assert detect_ping_pong(history) is LoopVerdict.ABORT


def test_neither_fires_on_varied_history():
    """A->B->C->A->B (~1.5 cycles) triggers neither."""
    a = ToolCall("shell", {"argv": ["ls"]})
    b = ToolCall("shell", {"argv": ["pwd"]})
    c = ToolCall("shell", {"argv": ["date"]})
    history = [a, b, c, a, b]
    assert detect_degenerate_loop(history) is LoopVerdict.OK
    assert detect_ping_pong(history) is LoopVerdict.OK


def test_integration_act_result_shape():
    """Verify the finish_reason string matches what act.py produces."""
    from chimera.core.act import ActResult
    r = ActResult(
        task_text="test",
        completed=False,
        rounds=6,
        finish_reason="ping_pong_abort",
        failure_reason="aborted after repeated alternating tool-call cycle",
    )
    assert r.finish_reason == "ping_pong_abort"
    assert "alternating" in r.failure_reason
