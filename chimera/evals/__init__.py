"""Eval harness adapters for benchmarking Chimera's memory subsystem (ADR 0135).

Phase 4 #8 of the Honcho-inspired roadmap (ADR 0123). Public exports
are the LongMemEval adapter contract. Loading the upstream
LongMemEval grader (judge model + dataset) is the operator's job;
this module provides the Chimera-side shape the harness calls into.
"""

from .longmemeval import (
    AnswerResult,
    LongMemEvalAdapter,
    LongMemEvalItem,
    load_items,
    run_batch,
)

__all__ = [
    "AnswerResult",
    "LongMemEvalAdapter",
    "LongMemEvalItem",
    "load_items",
    "run_batch",
]
