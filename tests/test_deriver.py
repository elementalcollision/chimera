"""Tests for the Honcho-inspired Deriver (ADR 0124)."""

from __future__ import annotations

import json


from chimera.engines.deriver import (
    DERIVER_PROMPT,
    ReflectionConclusions,
    build_deriver_prompt,
    parse_conclusions,
)


# ── Schema / defaults ─────────────────────────────────────────────


def test_reflection_conclusions_defaults():
    c = ReflectionConclusions()
    assert c.summary == ""
    assert c.lessons_learned == []
    assert c.improvements_for_tomorrow == []
    assert c.themes == []
    assert c.is_empty()


def test_reflection_conclusions_to_dict_round_trip():
    c = ReflectionConclusions(
        summary="shipped two PRs",
        lessons_learned=["measure twice"],
        improvements_for_tomorrow=["cache the index"],
        themes=["budget", "tooling"],
    )
    d = c.to_dict()
    assert d["summary"] == "shipped two PRs"
    assert d["lessons_learned"] == ["measure twice"]
    assert d["themes"] == ["budget", "tooling"]
    assert not c.is_empty()


# ── Happy path ────────────────────────────────────────────────────


def test_parse_conclusions_clean_json():
    payload = json.dumps({
        "summary": "Shipped Phase 1 of ADR 0123.",
        "lessons_learned": ["tier defaults matter", "tests first"],
        "improvements_for_tomorrow": ["wire Context.to_openai sooner"],
        "themes": ["honcho", "budget"],
    })
    c = parse_conclusions(payload)
    assert c.summary == "Shipped Phase 1 of ADR 0123."
    assert "tier defaults matter" in c.lessons_learned
    assert len(c.improvements_for_tomorrow) == 1
    assert c.themes == ["honcho", "budget"]


# ── Defensive parsing ─────────────────────────────────────────────


def test_parse_conclusions_strips_markdown_fence():
    fenced = (
        "Sure, here you go:\n\n"
        "```json\n"
        '{"summary": "fenced output", "lessons_learned": [], '
        '"improvements_for_tomorrow": [], "themes": []}\n'
        "```\n"
    )
    c = parse_conclusions(fenced)
    assert c.summary == "fenced output"


def test_parse_conclusions_handles_preamble_prose():
    text = (
        "Here is the JSON object you requested:\n"
        '{"summary": "preamble drained", "lessons_learned": ["read the chart"], '
        '"improvements_for_tomorrow": [], "themes": []}'
    )
    c = parse_conclusions(text)
    assert c.summary == "preamble drained"
    assert c.lessons_learned == ["read the chart"]


def test_parse_conclusions_empty_input_returns_empty():
    assert parse_conclusions("").is_empty()
    assert parse_conclusions("   \n  ").is_empty()


def test_parse_conclusions_malformed_json_returns_empty():
    assert parse_conclusions("{not valid json").is_empty()
    assert parse_conclusions("just prose, no braces").is_empty()


def test_parse_conclusions_non_object_top_level_returns_empty():
    assert parse_conclusions("[1, 2, 3]").is_empty()
    assert parse_conclusions('"a string"').is_empty()


def test_parse_conclusions_missing_fields_still_parses():
    """Partial schemas yield partial conclusions; the rest stays empty."""
    c = parse_conclusions('{"summary": "only summary"}')
    assert c.summary == "only summary"
    assert c.lessons_learned == []
    assert c.themes == []
    assert not c.is_empty()


def test_parse_conclusions_wrong_type_fields_coerce_to_empty_lists():
    payload = json.dumps({
        "summary": "ok",
        "lessons_learned": "not a list",   # wrong type
        "improvements_for_tomorrow": 42,    # wrong type
        "themes": [1, "good-theme", None, "another"],  # mixed; drop non-strings
    })
    c = parse_conclusions(payload)
    assert c.lessons_learned == []
    assert c.improvements_for_tomorrow == []
    assert c.themes == ["good-theme", "another"]


def test_parse_conclusions_summary_non_string_falls_back_to_empty():
    payload = json.dumps({"summary": ["not", "a", "string"]})
    c = parse_conclusions(payload)
    assert c.summary == ""


def test_parse_conclusions_caps_list_length_at_five():
    payload = json.dumps({
        "summary": "x",
        "themes": [f"theme-{i}" for i in range(20)],
    })
    c = parse_conclusions(payload)
    assert len(c.themes) == 5
    assert c.themes[0] == "theme-0"


# ── Prompt template ────────────────────────────────────────────────


def test_build_deriver_prompt_substitutes_chronicle():
    prompt = build_deriver_prompt("Today I shipped Phase 1.")
    assert "Today I shipped Phase 1." in prompt
    assert "STRICT JSON" in prompt
    assert "summary" in prompt


def test_build_deriver_prompt_handles_empty():
    prompt = build_deriver_prompt("")
    assert "(empty)" in prompt


def test_deriver_prompt_constant_is_a_template_string():
    """Sanity: the constant uses {day_so_far} placeholder."""
    assert "{day_so_far}" in DERIVER_PROMPT


# ── ADR 0124 doc presence ─────────────────────────────────────────


def test_adr_0124_present():
    from pathlib import Path
    adr = (
        Path(__file__).parent.parent
        / "docs" / "adr" / "0124-deriver-style-extraction.md"
    )
    assert adr.exists()
    body = adr.read_text()
    assert "ReflectionConclusions" in body
    assert "0123" in body  # cross-references the Phase 1 ADR
