"""SkillSpec — the operator's brief for a new dynamic skill."""

from __future__ import annotations

import re
from dataclasses import dataclass

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")


@dataclass(frozen=True)
class SkillSpec:
    """A description of a skill Chimera should assemble."""

    name: str           # tool name (snake_case, must match identifier rules)
    description: str    # what the tool does, surfaced to the model
    brief: str          # extended brief used by the assembler

    def __post_init__(self) -> None:
        if not _NAME_RE.match(self.name):
            raise ValueError(
                f"skill name {self.name!r} must be snake_case "
                f"(start with letter, 2–32 chars total)"
            )
        if not self.description.strip():
            raise ValueError("description must be non-empty")
        if not self.brief.strip():
            raise ValueError("brief must be non-empty")
