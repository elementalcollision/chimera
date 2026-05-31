"""Task proposal generation + dedup (Reggio's PLAN-phase ingredients)."""

from .charter import (
    CharterBundle,
    CharterValidation,
    build_charter_prompt,
    extract_charter,
    generate_charter,
    validate_charter,
)
from .charter_materialize import (
    CharterArtifacts,
    format_charter_packet,
    materialize_charter,
    rewrite_test_imports,
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
    "CharterArtifacts",
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
    "format_charter_packet",
    "generate_charter",
    "materialize_charter",
    "rewrite_test_imports",
    "validate_charter",
]
