"""Tests for the soak ACT-phase tool-call ledger (v40 build-capability prereq).

Covers the four contract guarantees:
  1. Opt-in — no env var ⇒ no file, no error.
  2. Emit — env var set ⇒ one JSONL line per execute, with the
     tool-call sequence grouped per ACT cycle.
  3. Safety — run ids are sanitized so they cannot escape the soak dir.
  4. Fail-soft — args that are not JSON-native still hash; a bad mind
     dir degrades to None rather than raising.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chimera.core.act import ActResult
from chimera.core.soak_ledger import (
    ACT_TOOLS_FILENAME,
    TEST_RUNS_FILENAME,
    args_hash,
    build_act_record,
    build_test_run_record,
    is_test_command,
    record_act_tools,
    record_test_run,
    soak_ledger_dir,
    soak_run_id,
)
from chimera.tools.loop_guard import ToolCall

_RUN_ID_ENV = "CHIMERA_SOAK_RUN_ID"


def _result(*, tools: list[ToolCall] | None = None, **kw) -> ActResult:
    base = dict(task_text="t", completed=True, rounds=2, finish_reason="ok")
    base.update(kw)
    r = ActResult(**base)
    if tools is not None:
        r.tool_call_history = tools
    return r


def _call(name, args, *, is_error=None, duration_ms=None) -> ToolCall:
    return ToolCall(name=name, args=args, is_error=is_error, duration_ms=duration_ms)


# ── 1. Opt-in ────────────────────────────────────────────────

def test_no_run_id_is_noop(tmp_path, monkeypatch):
    monkeypatch.delenv(_RUN_ID_ENV, raising=False)
    assert soak_run_id() is None
    out = record_act_tools(
        mind_dir=tmp_path, cycle=1, task_text="t", result=_result()
    )
    assert out is None
    # No soak directory should have been created.
    assert not (tmp_path / "soak").exists()


def test_blank_run_id_is_noop(tmp_path, monkeypatch):
    monkeypatch.setenv(_RUN_ID_ENV, "   ")
    assert soak_run_id() is None
    assert record_act_tools(
        mind_dir=tmp_path, cycle=1, task_text="t", result=_result()
    ) is None


# ── 2. Emit ──────────────────────────────────────────────────

def test_emit_writes_one_line_per_call(tmp_path, monkeypatch):
    monkeypatch.setenv(_RUN_ID_ENV, "v40-2026-05-29-1000")
    tools = [
        ToolCall(name="read_file", args={"path": "a.py"}),
        ToolCall(name="write_file", args={"path": "a.py", "content": "x"}),
    ]
    p1 = record_act_tools(
        mind_dir=tmp_path, cycle=3, task_text="build mind count",
        result=_result(tools=tools, rounds=2, api_call_count=2),
    )
    p2 = record_act_tools(
        mind_dir=tmp_path, cycle=4, task_text="iterate",
        result=_result(tools=[ToolCall(name="shell", args={"cmd": "pytest"})]),
    )
    assert p1 == p2  # same ledger file, appended
    assert p1 == tmp_path / "soak" / "v40-2026-05-29-1000" / ACT_TOOLS_FILENAME

    lines = p1.read_text().strip().splitlines()
    assert len(lines) == 2
    rec0 = json.loads(lines[0])
    assert rec0["cycle"] == 3
    assert rec0["tool_call_count"] == 2
    assert [c["name"] for c in rec0["tool_calls"]] == ["read_file", "write_file"]
    assert rec0["completed"] is True
    assert rec0["run_id"] == "v40-2026-05-29-1000"
    # args_hash present and stable-length.
    assert all(len(c["args_hash"]) == 12 for c in rec0["tool_calls"])

    rec1 = json.loads(lines[1])
    assert rec1["cycle"] == 4
    assert rec1["tool_call_count"] == 1


def test_task_text_is_truncated(tmp_path, monkeypatch):
    monkeypatch.setenv(_RUN_ID_ENV, "v40")
    rec = build_act_record(
        run_id="v40", cycle=1, task_text="x" * 5000, result=_result()
    )
    assert len(rec["task"]) == 200


# ── 2b. Per-call exit + duration (depth) ─────────────────────

def test_per_call_exit_and_duration_recorded():
    tools = [
        _call("read_file", {"path": "a.py"}, is_error=False, duration_ms=12.5),
        _call("shell", {"cmd": "pytest"}, is_error=True, duration_ms=240.0),
    ]
    rec = build_act_record(
        run_id="v40", cycle=1, task_text="t", result=_result(tools=tools)
    )
    calls = rec["tool_calls"]
    assert calls[0]["is_error"] is False
    assert calls[0]["duration_ms"] == 12.5
    assert calls[1]["is_error"] is True
    assert calls[1]["duration_ms"] == 240.0
    # Per-cycle rollups.
    assert rec["tool_error_count"] == 1
    assert rec["tool_total_ms"] == 252.5


def test_undispatched_calls_have_null_outcome():
    # A batch aborted before dispatch leaves is_error/duration_ms None.
    tools = [
        _call("read_file", {"path": "a.py"}, is_error=False, duration_ms=5.0),
        _call("shell", {"cmd": "x"}),  # never dispatched
    ]
    rec = build_act_record(
        run_id="v40", cycle=1, task_text="t", result=_result(tools=tools)
    )
    assert rec["tool_calls"][1]["is_error"] is None
    assert rec["tool_calls"][1]["duration_ms"] is None
    # Rollups ignore the un-dispatched call.
    assert rec["tool_error_count"] == 0
    assert rec["tool_total_ms"] == 5.0


# ── 3. Safety — run-id sanitization ──────────────────────────

def test_run_id_sanitized_cannot_escape(tmp_path, monkeypatch):
    monkeypatch.setenv(_RUN_ID_ENV, "../../etc/passwd")
    rid = soak_run_id()
    assert rid is not None
    assert "/" not in rid and ".." not in rid
    d = soak_ledger_dir(tmp_path, rid)
    # Resolved dir stays under tmp_path/soak.
    assert str(d).startswith(str(tmp_path / "soak"))


def test_soak_ledger_dir_none_without_run_id(tmp_path, monkeypatch):
    monkeypatch.delenv(_RUN_ID_ENV, raising=False)
    assert soak_ledger_dir(tmp_path) is None


# ── 4. Fail-soft ─────────────────────────────────────────────

def test_args_hash_tolerates_non_json(tmp_path):
    # A Path is not JSON-native; default=str must keep hashing working.
    h = args_hash({"p": Path("/tmp/x"), "n": 1})
    assert isinstance(h, str) and len(h) == 12


def test_args_hash_is_order_stable():
    a = args_hash({"a": 1, "b": 2})
    b = args_hash({"b": 2, "a": 1})
    assert a == b


def test_record_failsoft_on_bad_mind_dir(monkeypatch):
    # Point mind_dir at a path whose parent is a file → mkdir raises,
    # but record_act_tools must swallow it and return None.
    monkeypatch.setenv(_RUN_ID_ENV, "v40")
    import tempfile
    with tempfile.NamedTemporaryFile() as fh:
        bad = Path(fh.name) / "under-a-file"
        assert record_act_tools(
            mind_dir=bad, cycle=1, task_text="t", result=_result()
        ) is None


# ── 5. Test-run ledger ───────────────────────────────────────

@pytest.mark.parametrize(
    "argv,expected",
    [
        (["pytest", "-q", "tests/test_cli_mind_count.py"], True),
        (["python", "-m", "pytest", "tests/"], True),
        (["python3", "-m", "pytest"], True),
        (["/usr/bin/pytest", "-x"], True),       # absolute path in argv[0]
        (["python", "script.py"], False),        # not pytest
        (["ls", "-la"], False),
        (["git", "commit"], False),
        ([], False),
    ],
)
def test_is_test_command(argv, expected):
    assert is_test_command(argv) is expected


def test_test_run_passed_flag_and_stdout_tail():
    rec = build_test_run_record(
        run_id="v40",
        argv=["pytest", "-q"],
        exit_code=0,
        duration_ms=1234.5,
        stdout="\n".join(f"line{i}" for i in range(50)),
    )
    assert rec["passed"] is True
    assert rec["exit_code"] == 0
    assert rec["timed_out"] is False
    assert rec["program"] == "pytest"
    # Only the last 20 non-empty lines retained.
    assert len(rec["stdout_tail"]) == 20
    assert rec["stdout_tail"][-1] == "line49"


def test_test_run_failure_not_passed():
    rec = build_test_run_record(
        run_id="v40", argv=["pytest"], exit_code=1, duration_ms=10.0,
        stdout="5 failed",
    )
    assert rec["passed"] is False
    assert rec["exit_code"] == 1


def test_test_run_timeout_never_passed():
    # A timeout has exit_code None and must never count as passed —
    # the verdict-honesty gate relies on this.
    rec = build_test_run_record(
        run_id="v40", argv=["pytest"], exit_code=None, duration_ms=60000.0,
        timed_out=True,
    )
    assert rec["passed"] is False
    assert rec["timed_out"] is True


def test_record_test_run_emits_only_for_test_commands(tmp_path, monkeypatch):
    monkeypatch.setenv(_RUN_ID_ENV, "v40")
    monkeypatch.setenv("CHIMERA_MIND_DIR", str(tmp_path))
    # Non-test command: no file.
    assert record_test_run(argv=["ls"], exit_code=0, duration_ms=1.0) is None
    # Test command: writes to <mind>/soak/<run>/test-runs.jsonl.
    p = record_test_run(
        argv=["pytest", "-q"], exit_code=0, duration_ms=5.0, stdout="1 passed"
    )
    assert p == tmp_path / "soak" / "v40" / TEST_RUNS_FILENAME
    rec = json.loads(p.read_text().strip())
    assert rec["passed"] is True
    assert rec["argv"] == ["pytest", "-q"]


def test_record_test_run_noop_without_run_id(tmp_path, monkeypatch):
    monkeypatch.delenv(_RUN_ID_ENV, raising=False)
    assert record_test_run(argv=["pytest"], exit_code=0, duration_ms=1.0) is None
