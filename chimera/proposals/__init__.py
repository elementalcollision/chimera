"""Task proposal generation + dedup (Reggio's PLAN-phase ingredients)."""

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
    "ProposedTask",
    "build_plan_prompt",
    "cluster_key",
    "dedup",
    "extract_proposals",
    "fingerprint",
]
