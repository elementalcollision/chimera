"""Task proposal generation + dedup (Reggio's PLAN-phase ingredients)."""

from .charter import (
    CharterBundle,
    CharterValidation,
    build_charter_prompt,
    extract_charter,
    generate_charter,
    validate_charter,
)
from .dedup import cluster_key, dedup, fingerprint
from .generate import (
    MAX_PROPOSED_TASKS_PER_PLAN,
    PLAN_PROMPT_TEMPLATE,
    ProposedTask,
    build_plan_prompt,
    extract_proposals,
)

__all__ = [
    "MAX_PROPOSED_TASKS_PER_PLAN",
    "PLAN_PROMPT_TEMPLATE",
    "CharterBundle",
    "CharterValidation",
    "ProposedTask",
    "build_charter_prompt",
    "build_plan_prompt",
    "cluster_key",
    "dedup",
    "extract_charter",
    "extract_proposals",
    "fingerprint",
    "generate_charter",
    "validate_charter",
]
