"""Skill assembly pipeline — Chimera grows its own tools.

Per ADR 0003 deferred-list. The flow is:

  spec    → operator-approved SkillSpec describing what we want
  assemble → Sonnet generates handler code + tool schema + samples
  validate → sandboxed subprocess runs handler on samples
  activate → writes to chimera/tools/dynamic/<name>.py, registers
"""

from .assembly import AssembledSkill, assemble_skill
from .activator import ActivationResult, activate_skill, dynamic_skills_dir, load_dynamic_skills
from .spec import SkillSpec
from .validation import ValidationResult, validate_skill

__all__ = [
    "AssembledSkill",
    "ActivationResult",
    "SkillSpec",
    "ValidationResult",
    "activate_skill",
    "assemble_skill",
    "dynamic_skills_dir",
    "load_dynamic_skills",
    "validate_skill",
]
