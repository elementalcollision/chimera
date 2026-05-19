"""Activation — write the validated handler to ``chimera/tools/dynamic/``
and register it with the tool registry.

A hard cap (default 20) on dynamic skills prevents runaway growth per
pillar-creativity.md Pattern 4 (Reggio's MAX_DYNAMIC_SKILLS).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from ..tools import ToolRegistry, default_registry
from .assembly import AssembledSkill
from .validation import ValidationResult

MAX_DYNAMIC_SKILLS: int = 20


@dataclass
class ActivationResult:
    ok: bool
    path: str | None = None
    tool_name: str | None = None
    failure_reason: str | None = None


def dynamic_skills_dir() -> Path:
    """Path to chimera/tools/dynamic/. Created if missing."""
    here = Path(__file__).resolve().parent.parent / "tools" / "dynamic"
    here.mkdir(parents=True, exist_ok=True)
    init_path = here / "__init__.py"
    if not init_path.exists():
        init_path.write_text(
            "\"\"\"Auto-generated dynamic skills. Don't edit by hand.\"\"\"\n",
            encoding="utf-8",
        )
    return here


_MODULE_TEMPLATE = """\
\"\"\"Auto-generated skill: {name}

Brief was:
{brief_block}

Schema:
{schema_block}
\"\"\"

from __future__ import annotations

from chimera.tools import default_registry


{handler_code}

SCHEMA = {schema_repr}


def register(registry=None) -> None:
    \"\"\"Idempotent registration for the {name!r} dynamic skill.\"\"\"
    reg = registry or default_registry()
    reg.register(
        name={name!r},
        toolset="dynamic",
        schema=SCHEMA,
        handler=handle,
        description={description!r},
        override=True,
    )
"""


def activate_skill(
    assembled: AssembledSkill,
    validation: ValidationResult,
    *,
    registry: ToolRegistry | None = None,
    skills_dir: Path | None = None,
) -> ActivationResult:
    """Persist + register a validated skill."""
    if not validation.ok:
        return ActivationResult(
            ok=False, failure_reason=f"validation not ok: {validation.failure_reason}"
        )

    skills_dir = (skills_dir or dynamic_skills_dir()).resolve()
    existing = [p for p in skills_dir.glob("*.py") if p.stem != "__init__"]
    if len(existing) >= MAX_DYNAMIC_SKILLS:
        return ActivationResult(
            ok=False,
            failure_reason=(
                f"dynamic skill cap reached ({MAX_DYNAMIC_SKILLS}); "
                "delete an unused skill first"
            ),
        )

    name = assembled.spec.name
    target = skills_dir / f"{name}.py"
    brief_block = "\n".join("# " + line for line in assembled.spec.brief.splitlines())
    schema_block = "\n".join("# " + line for line in json.dumps(assembled.schema, indent=2).splitlines())
    contents = _MODULE_TEMPLATE.format(
        name=name,
        brief_block=brief_block,
        schema_block=schema_block,
        handler_code=assembled.handler_code.strip(),
        schema_repr=repr(assembled.schema),
        description=assembled.spec.description,
    )
    target.write_text(contents, encoding="utf-8")

    # Import + register so the new skill is immediately callable.
    module_name = f"chimera.tools.dynamic.{name}"
    spec = importlib.util.spec_from_file_location(module_name, target)
    if spec is None or spec.loader is None:
        return ActivationResult(
            ok=False, failure_reason="failed to build importlib spec", path=str(target)
        )
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
        module.register(registry)
    except Exception as exc:
        target.unlink(missing_ok=True)
        sys.modules.pop(module_name, None)
        return ActivationResult(
            ok=False, failure_reason=f"import/register raised: {exc}", path=str(target)
        )

    return ActivationResult(ok=True, path=str(target), tool_name=name)


def load_dynamic_skills(registry: ToolRegistry | None = None) -> list[str]:
    """Import all files under ``chimera/tools/dynamic/`` and call their register().

    Returns the list of skill names actually registered. Skip-fails any
    module that raises during import or registration.
    """
    reg = registry or default_registry()
    skills_dir = dynamic_skills_dir()
    registered: list[str] = []
    for path in sorted(skills_dir.glob("*.py")):
        if path.stem == "__init__":
            continue
        module_name = f"chimera.tools.dynamic.{path.stem}"
        if module_name in sys.modules:
            # Already loaded; ensure registered.
            try:
                sys.modules[module_name].register(reg)
                registered.append(path.stem)
            except Exception:
                pass
            continue
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
            module.register(reg)
            sys.modules[module_name] = module
            registered.append(path.stem)
        except Exception:
            sys.modules.pop(module_name, None)
            continue
    return registered
