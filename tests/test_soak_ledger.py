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
    args_hash,
    build_act_record,
    record_act_tools,
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
