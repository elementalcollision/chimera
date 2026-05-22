# Ping-Pong Wiring Investigation

## Problem

`chimera/core/act.py` calls `detect_degenerate_loop` on the tool-call
history after each round. That detector catches consecutive identical
(name + args) repeats -- e.g. `shell({"argv": ["ls"]})` x5. It does
**not** catch *alternating* (ping-pong) cycles such as:

    A -> B -> A -> B -> A -> B   where A != B

The broader problem is that ActResult and the runner treat
`finish_reason="degenerate_loop_abort"` as the sole loop-abort signal.
A peer-peer ping-pong (Chimera-A calls Chimera-B via MCP, Chimera-B
responds, Chimera-A calls again, ad infinitum) produces no two
consecutive identical calls and therefore never triggers the guard.

## What exists already

| Component | Location | Status |
|---|---|---|
| `detect_ping_pong()` | `chimera/tools/loop_guard.py:55` | Implemented, tested |
| `detect_ping_pong` export | `chimera/tools/__init__.py:15` | Exported in `__all__` |
| `detect_ping_pong` unit tests | `tests/test_guards.py:68` | 8 tests, all passing |
| `detect_ping_pong` **call site** | `chimera/core/act.py` | **NOT wired** |

The function signature:

```python
def detect_ping_pong(
    history: list[ToolCall],
    *,
    min_cycle_length: int = 2,
    max_cycle_length: int = 3,
    abort_at_repeats: int = 2,
) -> LoopVerdict:
```

It inspects the tail of `history` for a repeating pattern of length 2-3
and returns `LoopVerdict.ABORT` when the same cycle appears
`abort_at_repeats + 1` times (default: 3 full cycles -> ABORT).

## What `act.py` does today

The relevant loop body (lines ~1638-1652):

```python
batch_args: list[dict[str, Any]] = []
for tu in response.tool_uses:
    args = normalize_tool_input(tu.input)
    batch_args.append(args)
    history.append(ToolCall(name=tu.name, args=args))

verdict = detect_degenerate_loop(history)
if verdict is LoopVerdict.ABORT:
    return ActResult(
        task_text=task_text,
        completed=False,
        rounds=round_idx + 1,
        finish_reason="degenerate_loop_abort",
        ...
    )
```

The import (line ~68):

```python
from ..tools import (
    DispatchContext,
    Dispatcher,
    LoopVerdict,
    ToolCall,
    ToolDenied,
    detect_degenerate_loop,
    extract_target_paths,
    normalize_tool_input,
)
```

## What needs to change (minimal diff)

**One import add** (line ~68 of `chimera/core/act.py`):

Add `detect_ping_pong` to the existing `from ..tools import (...)` block.

**Three lines added** after the `detect_degenerate_loop` verdict check
(line ~1651):

```python
# Also check for alternating (ping-pong) cycles that
# detect_degenerate_loop cannot see.
ping_verdict = detect_ping_pong(history)
if ping_verdict is LoopVerdict.ABORT:
    return ActResult(
        task_text=task_text,
        completed=False,
        rounds=round_idx + 1,
        finish_reason="ping_pong_abort",
        write_targets=write_targets,
        tool_call_history=history,
        final_text=final_text,
        failure_reason="aborted after repeated alternating tool-call cycle",
        api_call_count=api_call_count,
    )
```

**Optionally** add `"ping_pong_abort"` to any finish-reason switch in
the runner/phase logic that currently handles `"degenerate_loop_abort"`.

---

## READY-FOR-REMEDIATION

**(a)** Wire `detect_ping_pong` into `chimera/core/act.py` as a second
loop guard called immediately after `detect_degenerate_loop` on every
round, returning `ping_pong_abort` on matching alternating cycles.

**(b)** Exact lines of `chimera/core/act.py` that need to change:

| Line | Action |
|---|---|
| **~68** | Add `detect_ping_pong,` to the `from ..tools import (...)` list |
| **~1651** | Insert the 10-line `ping_verdict = detect_ping_pong(history); if ping_verdict is LoopVerdict.ABORT: return ActResult(...)` block after `if verdict is LoopVerdict.ABORT:` |

**(c)** Pseudocode test that distinguishes ping-pong from degenerate-loop
firing:

```python
# File: tests/test_act_guards.py (or appended to tests/test_guards.py)

from chimera.tools.loop_guard import detect_degenerate_loop, detect_ping_pong

def test_ping_pong_fires_where_degenerate_loop_does_not():
    """A->B->A->B->A->B triggers ping_pong ABORT but degenerate_loop OK."""
    a = ToolCall("mcp-peer-alpha-read_file", {"path": "/var/log"})
    b = ToolCall("mcp-peer-alpha-write_file", {"path": "/var/log", "content": "done"})
    history = [a, b, a, b, a, b]

    assert detect_degenerate_loop(history) is LoopVerdict.OK, (
        "degenerate_loop sees no two consecutive identical calls -- wrong for ping-pong"
    )
    assert detect_ping_pong(history) is LoopVerdict.ABORT, (
        "ping_pong sees the 3-cycle alternating pattern -- correct"
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
```

The critical discriminant test is `test_ping_pong_fires_where_degenerate_loop_does_not`:
it proves the two guards are *complementary* -- not redundant.
