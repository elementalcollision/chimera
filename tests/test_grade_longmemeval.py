"""Tests for scripts/grade_longmemeval.py — the footgun guards.

The substantive grading behaviour is exercised end-to-end by the
LongMemEval baseline / spike chips. These tests pin the two guards
that prevent the silent zeroing failure mode documented in ADR 0143:

  * Default judge is ``openai/gpt-4o-mini`` (not a reasoning model).
  * Reasoning-model judges (o1/o3/o4 family) are refused by default
    with an actionable error; override knob exists for the brave.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO_ROOT / "scripts" / "grade_longmemeval.py"


def _load_module():
    """Import the script as a module so we can read its constants."""
    spec = importlib.util.spec_from_file_location("grade_longmemeval", _SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_default_judge_is_not_a_reasoning_model() -> None:
    """ADR 0143 footgun: o4-mini at max_tokens=16 zeros every grade."""
    mod = _load_module()
    assert mod.DEFAULT_JUDGE == "openai/gpt-4o-mini"
    assert mod.DEFAULT_JUDGE not in mod._REASONING_JUDGE_BLOCKLIST


def test_reasoning_judge_blocklist_covers_known_offenders() -> None:
    mod = _load_module()
    # These are the OpenRouter IDs whose hidden chain-of-thought
    # silently eats the max_tokens=16 budget. Update the script's
    # blocklist (not this test alone) if more reasoning models surface.
    for model_id in (
        "openai/o1",
        "openai/o1-mini",
        "openai/o1-preview",
        "openai/o3",
        "openai/o3-mini",
        "openai/o4-mini",
    ):
        assert model_id in mod._REASONING_JUDGE_BLOCKLIST, (
            f"{model_id} should be on the grader's reasoning-judge blocklist "
            f"to prevent the ADR 0143 silent-zero footgun."
        )


def test_script_refuses_reasoning_judge_without_override(
    monkeypatch, tmp_path, capsys
) -> None:
    """Invoking the script with a blocklisted judge exits 2 with guidance."""
    mod = _load_module()

    monkeypatch.delenv("CHIMERA_GRADE_ALLOW_REASONING_JUDGE", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test")  # past the early arg check

    hyp = tmp_path / "h.jsonl"
    ref = tmp_path / "r.json"
    out = tmp_path / "o.jsonl"
    hyp.write_text("")
    ref.write_text("[]")

    monkeypatch.setattr(
        sys,
        "argv",
        ["grade_longmemeval.py", str(hyp), str(ref), str(out), "openai/o4-mini"],
    )

    import asyncio
    try:
        asyncio.run(mod.main())
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected SystemExit(2) on reasoning-judge default")

    err = capsys.readouterr().err
    assert "reasoning model" in err
    assert "ADR 0143" in err
    assert "CHIMERA_GRADE_ALLOW_REASONING_JUDGE" in err
