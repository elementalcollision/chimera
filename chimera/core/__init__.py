"""Chimera core: agent loop, KFM state, escalation."""

from .escalation import (
    EscalationPlan,
    build_correction_prompt,
    build_escalation_plan,
    next_tier_up,
)
from .kfm import (
    KFM_STATES,
    LEGAL_TRANSITIONS,
    TRANSITION_AUTHORITY,
    TransitionResult,
    check_transition,
)
from .loop import ChimeraLoop, CycleReport, LoopConfig
from .mind import (
    HeartbeatState,
    InboxTask,
    append_session_log,
    load_heartbeat,
    mark_inbox_tasks_done,
    parse_inbox,
    save_heartbeat,
)

__all__ = [
    "ChimeraLoop",
    "CycleReport",
    "LoopConfig",
    "HeartbeatState",
    "InboxTask",
    "EscalationPlan",
    "KFM_STATES",
    "LEGAL_TRANSITIONS",
    "TRANSITION_AUTHORITY",
    "TransitionResult",
    "append_session_log",
    "build_correction_prompt",
    "build_escalation_plan",
    "check_transition",
    "load_heartbeat",
    "mark_inbox_tasks_done",
    "next_tier_up",
    "parse_inbox",
    "save_heartbeat",
]
