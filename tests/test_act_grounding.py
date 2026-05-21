"""v4.83 (ADR 0095): grounding-check regression tests.

Fixture case: soak-v4 produced
mind/research/loop-abort-investigation.md naming a function
``should_abort_loop`` that does not appear in
chimera/tools/loop_guard.py (the real function is
``detect_degenerate_loop``). The grounding check must downgrade
completed=True to finish_reason="ungrounded_citation" on this input.
"""

from __future__ import annotations

from pathlib import Path

from chimera.core.grounding import (
    SYNTHESIS_GROUNDING_GUIDANCE,
    check_citation_grounding,
    extract_cited_source_files,
    extract_cited_symbols,
    is_synthesis_task,
    synthesis_guidance_for,
)


# ── synthesis-task detection ────────────────────────────────────────


def test_summarise_is_synthesis():
    assert is_synthesis_task(
        "Read chimera/tools/loop_guard.py and summarise the heuristic."
    )


def test_form_a_verdict_is_synthesis():
    assert is_synthesis_task("Form a verdict on whether the abort logic is sound.")


def test_analyse_is_synthesis():
    assert is_synthesis_task("Analyse the failure mode in act.py and report.")


def test_plain_write_task_is_not_synthesis():
    assert not is_synthesis_task("Write the trace to state/trace.log.")


# ── cited-file extraction ───────────────────────────────────────────


def test_extract_backticked_python_file():
    text = "Read `chimera/tools/loop_guard.py` in full and summarise."
    assert extract_cited_source_files(text) == ["chimera/tools/loop_guard.py"]


def test_extract_bare_python_file():
    text = "Summarise the heuristic in chimera/tools/loop_guard.py."
    assert extract_cited_source_files(text) == ["chimera/tools/loop_guard.py"]


def test_extract_multiple_languages_dedupes():
    text = "Compare `src/foo.ts` with `src/bar.rs` and `src/foo.ts` again."
    out = extract_cited_source_files(text)
    assert out == ["src/foo.ts", "src/bar.rs"]


def test_ignores_non_source_extensions():
    text = "Read `mind/notes.md` and `state/out.json`."
    assert extract_cited_source_files(text) == []


# ── symbol extraction ──────────────────────────────────────────────


def test_extract_def_form():
    text = "The function `def should_abort_loop(history):` resets the counter."
    syms = extract_cited_symbols(text)
    assert "should_abort_loop" in syms


def test_extract_backticked_call_form():
    text = "The agent calls `should_abort_loop(history)` after each round."
    syms = extract_cited_symbols(text)
    assert "should_abort_loop" in syms


def test_extract_function_named_form():
    text = "The function named `detect_degenerate_loop` runs every round."
    syms = extract_cited_symbols(text)
    assert "detect_degenerate_loop" in syms


def test_skips_short_or_english_identifiers():
    text = "Look at `foo`, `bar`, `True`, `the`, `file`."
    assert extract_cited_symbols(text) == []


def test_requires_underscore_or_mixed_case():
    text = "Use `shouldwork` and `should_work` and `ShouldWork`."
    syms = extract_cited_symbols(text)
    assert "should_work" in syms
    assert "ShouldWork" in syms
    assert "shouldwork" not in syms


# ── grounding check ────────────────────────────────────────────────


def test_grounded_symbol_passes(tmp_path: Path):
    src = tmp_path / "src.py"
    src.write_text("def detect_degenerate_loop(history): ...\n")
    ungrounded = check_citation_grounding(
        ["src.py"], ["detect_degenerate_loop"], base_dir=tmp_path,
    )
    assert ungrounded == []


def test_ungrounded_symbol_flagged(tmp_path: Path):
    src = tmp_path / "src.py"
    src.write_text("def detect_degenerate_loop(history): ...\n")
    ungrounded = check_citation_grounding(
        ["src.py"], ["should_abort_loop"], base_dir=tmp_path,
    )
    assert ungrounded == ["should_abort_loop"]


def test_partial_match_is_not_grounded(tmp_path: Path):
    # "abort" appearing inside "abort_logic" must NOT ground "should_abort".
    src = tmp_path / "src.py"
    src.write_text("def abort_logic(): pass\n")
    ungrounded = check_citation_grounding(
        ["src.py"], ["should_abort"], base_dir=tmp_path,
    )
    assert ungrounded == ["should_abort"]


def test_missing_source_file_returns_no_false_positives(tmp_path: Path):
    # If we can't read any cited file, we cannot prove a citation is
    # ungrounded — fail open rather than flag everything.
    ungrounded = check_citation_grounding(
        ["does_not_exist.py"], ["foo_bar"], base_dir=tmp_path,
    )
    assert ungrounded == []


def test_empty_inputs_return_empty():
    assert check_citation_grounding([], ["foo"], base_dir=Path("/tmp")) == []
    assert check_citation_grounding(["foo.py"], [], base_dir=Path("/tmp")) == []


# ── synthesis-guidance prompt ──────────────────────────────────────


def test_synthesis_guidance_for_synthesis_task_with_source():
    text = "Read `chimera/tools/loop_guard.py` and summarise the heuristic."
    assert synthesis_guidance_for(text) == SYNTHESIS_GROUNDING_GUIDANCE


def test_no_synthesis_guidance_for_plain_write():
    text = "Write the result to state/out.log."
    assert synthesis_guidance_for(text) == ""


def test_no_synthesis_guidance_when_no_source_file_cited():
    text = "Summarise the project status in 3 bullets."
    assert synthesis_guidance_for(text) == ""


# ── end-to-end soak-v4 fixture ─────────────────────────────────────


def test_soak_v4_fixture_is_flagged(tmp_path: Path):
    """The exact failure from soak-v4: synthesis cited ``should_abort_loop``
    but the file only defines ``detect_degenerate_loop``."""
    src_dir = tmp_path / "chimera" / "tools"
    src_dir.mkdir(parents=True)
    (src_dir / "loop_guard.py").write_text(
        "def detect_degenerate_loop(history, *, warn_at=3, abort_at=5):\n"
        "    '''counts CONSECUTIVE IDENTICAL tool calls'''\n"
        "    ...\n"
    )
    task = (
        "Read `chimera/tools/loop_guard.py` in full and summarise the "
        "exact heuristic for `detect_degenerate_loop`."
    )
    synthesis = (
        "The function `should_abort_loop(history)` incorrectly flags "
        "every invocation where a tool_use block is followed by a "
        "subsequent API call. Patching it to reset the streak counter "
        "to zero on `tool_result` would fix the false positive."
    )
    cited_files = extract_cited_source_files(task)
    assert cited_files == ["chimera/tools/loop_guard.py"]
    syms = extract_cited_symbols(synthesis)
    assert "should_abort_loop" in syms
    # detect_degenerate_loop is grounded; should_abort_loop is not.
    ungrounded = check_citation_grounding(
        cited_files, syms, base_dir=tmp_path,
    )
    assert "should_abort_loop" in ungrounded
    assert "detect_degenerate_loop" not in ungrounded
