"""Tests for the skill assembly pipeline (assemble → validate → activate)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from chimera.memory import open_and_init
from chimera.providers import ChatChunk, ChatResponse, Provider
from chimera.providers.tiers import Provider as ProviderKind
from chimera.skills import (
    AssembledSkill,
    SkillSpec,
    activate_skill,
    assemble_skill,
    load_dynamic_skills,
    validate_skill,
)
from chimera.skills.assembly import parse_assembly_response
from chimera.skills.validation import static_lint
from chimera.tools import ToolRegistry


class _ScriptedProvider(Provider):
    name = "scripted"

    def __init__(self, response: ChatResponse) -> None:
        self._response = response

    async def stream(self, *a, **kw):  # pragma: no cover
        if False:
            yield ChatChunk(text="")

    async def complete_with_tools(self, *a, **kw) -> ChatResponse:
        return self._response


@pytest.fixture
def db(tmp_path: Path):
    c = open_and_init(tmp_path / "chimera.db")
    yield c
    c.close()


@pytest.fixture
def skills_dir(tmp_path: Path):
    """Use a temp dir so tests don't pollute chimera/tools/dynamic/."""
    d = tmp_path / "dynamic"
    d.mkdir()
    (d / "__init__.py").write_text("")
    return d


# ── SkillSpec validation ─────────────────────────────────────


def test_spec_rejects_bad_name():
    with pytest.raises(ValueError):
        SkillSpec(name="BadName", description="d", brief="b")
    with pytest.raises(ValueError):
        SkillSpec(name="2bad", description="d", brief="b")


def test_spec_accepts_good_name():
    s = SkillSpec(name="sum_two_ints", description="d", brief="b")
    assert s.name == "sum_two_ints"


# ── parse_assembly_response ──────────────────────────────────


_VALID_RESPONSE = '''Here we go.

```schema
{"type": "function", "function": {"name": "sum_two_ints", "description": "Sum two ints", "parameters": {"type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}}, "required": ["a", "b"]}}}
```

```python
async def handle(args, context):
    a = int(args["a"])
    b = int(args["b"])
    return f"result: {a + b}"
```

```samples
[
  {"input": {"a": 2, "b": 3}, "expected_substring": "result: 5"},
  {"input": {"a": 0, "b": 0}, "expected_substring": "result: 0"},
  {"input": {"a": -1, "b": 1}, "expected_substring": "result: 0"}
]
```
'''


def test_parse_assembly_extracts_all_three_blocks():
    spec = SkillSpec(name="sum_two_ints", description="Sum two ints", brief="add a and b")
    out = parse_assembly_response(_VALID_RESPONSE, spec)
    assert out.ok is True
    assert out.schema["function"]["name"] == "sum_two_ints"
    assert "async def handle" in out.handler_code
    assert len(out.samples) == 3


def test_parse_assembly_fails_on_missing_block():
    spec = SkillSpec(name="test_skill", description="d", brief="b")
    out = parse_assembly_response("just prose, no blocks", spec)
    assert out.ok is False
    assert "missing" in out.failure_reason


def test_parse_assembly_fails_on_malformed_json():
    spec = SkillSpec(name="test_skill", description="d", brief="b")
    bad = """```schema
{not valid json
```

```python
async def handle(args, context): return "hi"
```

```samples
[]
```"""
    out = parse_assembly_response(bad, spec)
    assert out.ok is False
    assert "schema JSON parse" in out.failure_reason


# ── static_lint ──────────────────────────────────────────────


def test_static_lint_blocks_subprocess():
    code = "import subprocess\nasync def handle(args, context): return 'x'"
    assert static_lint(code) is not None


def test_static_lint_blocks_eval():
    code = "async def handle(args, context):\n    return str(eval('1+1'))"
    assert static_lint(code) is not None


def test_static_lint_blocks_network():
    code = "import urllib.request\nasync def handle(args, context): return 'x'"
    assert static_lint(code) is not None


def test_static_lint_passes_clean_handler():
    code = "async def handle(args, context):\n    return f\"{args}\""
    assert static_lint(code) is None


# ── assemble_skill (with scripted provider) ──────────────────


@pytest.mark.asyncio
async def test_assemble_skill_happy_path(db):
    spec = SkillSpec(
        name="sum_two_ints",
        description="Sum two integers",
        brief="Return 'result: <a+b>' for inputs a and b.",
    )
    fake = _ScriptedProvider(
        ChatResponse(
            text=_VALID_RESPONSE,
            tool_uses=[],
            stop_reason="stop",
            model_id="sonnet",
            provider="scripted",
            input_tokens=100,
            output_tokens=200,
        )
    )
    result = await assemble_skill(
        spec,
        providers={ProviderKind.ANTHROPIC: fake, ProviderKind.OPENROUTER: fake},
        db=db,
        cycle=1,
    )
    assert result.ok is True
    assert result.spec is spec
    assert result.api_call_count == 1
    rows = db.execute(
        "SELECT task_type, outcome FROM ladder_outcomes"
    ).fetchall()
    assert rows[0]["task_type"] == "skill_assembly"


# ── validate_skill (sandboxed subprocess) ────────────────────


@pytest.mark.asyncio
async def test_validate_clean_handler_passes():
    spec = SkillSpec(name="sum_two_ints", description="d", brief="b")
    assembled = parse_assembly_response(_VALID_RESPONSE, spec)
    assert assembled.ok
    result = await validate_skill(assembled, timeout_s=5.0)
    assert result.ok is True
    assert result.passed == 3
    assert result.score == 1.0


@pytest.mark.asyncio
async def test_validate_handler_with_forbidden_pattern_fails():
    spec = SkillSpec(name="bad_skill", description="d", brief="b")
    bad = AssembledSkill(
        spec=spec,
        ok=True,
        schema={"type": "function", "function": {"name": "bad_skill"}},
        handler_code="import subprocess\nasync def handle(args, context):\n    return 'x'",
        samples=[{"input": {}, "expected_substring": "x"}],
    )
    result = await validate_skill(bad)
    assert result.ok is False
    assert "forbidden pattern" in result.failure_reason


@pytest.mark.asyncio
async def test_validate_failing_sample_drops_score():
    spec = SkillSpec(name="wrong_skill", description="d", brief="b")
    assembled = AssembledSkill(
        spec=spec,
        ok=True,
        schema={"type": "function", "function": {"name": "wrong_skill"}},
        handler_code="async def handle(args, context):\n    return 'always_wrong'",
        samples=[
            {"input": {}, "expected_substring": "always_wrong"},
            {"input": {}, "expected_substring": "DEFINITELY_NOT_HERE"},
        ],
    )
    result = await validate_skill(assembled, pass_threshold=0.6)
    assert result.passed == 1
    assert result.total == 2
    assert result.score == 0.5
    assert result.ok is False  # 0.5 < 0.6


# ── activate_skill ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_activate_writes_file_and_registers(db, skills_dir):
    spec = SkillSpec(
        name="sum_two_ints", description="Sum two integers", brief="Add a and b."
    )
    assembled = parse_assembly_response(_VALID_RESPONSE, spec)
    validation = await validate_skill(assembled)
    assert validation.ok

    reg = ToolRegistry()
    result = activate_skill(assembled, validation, registry=reg, skills_dir=skills_dir)
    assert result.ok is True
    assert result.tool_name == "sum_two_ints"
    assert Path(result.path).exists()
    entry = reg.get("sum_two_ints")
    assert entry is not None
    assert entry.toolset == "dynamic"
    # Clean up: the skill module is now in sys.modules with chimera.tools.dynamic prefix.
    sys.modules.pop("chimera.tools.dynamic.sum_two_ints", None)


def test_activate_refuses_when_validation_failed(skills_dir):
    spec = SkillSpec(name="bad_validation", description="d", brief="b")
    assembled = AssembledSkill(spec=spec, ok=False, failure_reason="nope")
    from chimera.skills.validation import ValidationResult
    result = activate_skill(
        assembled,
        ValidationResult(ok=False, score=0.0, passed=0, total=0, failure_reason="bad"),
        skills_dir=skills_dir,
    )
    assert result.ok is False


@pytest.mark.asyncio
async def test_activate_caps_at_max_dynamic_skills(db, skills_dir, monkeypatch):
    import chimera.skills.activator as activator_mod

    monkeypatch.setattr(activator_mod, "MAX_DYNAMIC_SKILLS", 1)
    # First skill activates successfully.
    spec1 = SkillSpec(name="first_skill", description="d", brief="b")
    assembled1 = parse_assembly_response(
        _VALID_RESPONSE.replace("sum_two_ints", "first_skill"), spec1
    )
    val1 = await validate_skill(assembled1)
    r1 = activate_skill(assembled1, val1, registry=ToolRegistry(), skills_dir=skills_dir)
    assert r1.ok is True

    # Second skill hits the cap.
    spec2 = SkillSpec(name="second_skill", description="d", brief="b")
    assembled2 = parse_assembly_response(
        _VALID_RESPONSE.replace("sum_two_ints", "second_skill"), spec2
    )
    val2 = await validate_skill(assembled2)
    r2 = activate_skill(assembled2, val2, registry=ToolRegistry(), skills_dir=skills_dir)
    assert r2.ok is False
    assert "cap" in r2.failure_reason


# ── load_dynamic_skills ──────────────────────────────────────


def test_load_dynamic_skills_registers_all(skills_dir, monkeypatch):
    """End-to-end: write a couple of skill modules + invoke loader."""
    import chimera.skills.activator as activator_mod

    monkeypatch.setattr(activator_mod, "dynamic_skills_dir", lambda: skills_dir)

    # Write a minimal skill module.
    (skills_dir / "ping.py").write_text(
        '''
from chimera.tools import default_registry

async def handle(args, context):
    return "pong"

SCHEMA = {"type": "function", "function": {"name": "ping", "description": "pong", "parameters": {"type": "object", "properties": {}}}}

def register(registry=None):
    reg = registry or default_registry()
    reg.register(name="ping", toolset="dynamic", schema=SCHEMA, handler=handle, override=True)
''',
        encoding="utf-8",
    )
    reg = ToolRegistry()
    loaded = load_dynamic_skills(reg)
    assert "ping" in loaded
    assert reg.get("ping") is not None
