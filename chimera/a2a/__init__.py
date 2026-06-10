"""Agent-to-Agent (A2A) — identity, peer discovery, handshake.

v1.5 was a Xenocomm-MCP-client spike. v2.1 adds the identity handshake
that lets two Chimeras attest to each other before any policy-gated
work happens.

- :class:`AgentIdentity` — what this Chimera advertises to peers
- :func:`list_xenocomm_tools` — Xenocomm tools discovered via MCP
- :func:`list_peer_chimeras` — server names of peer Chimeras discovered
- :func:`fetch_peer_identity` — call a peer's ``chimera-identity`` tool
"""

from .identity import AgentIdentity
from .peers import (
    fetch_peer_identity,
    fetch_peer_kfm,
    list_peer_chimeras,
    list_xenocomm_tools,
)
from .alignment import (
    AlignmentCeremony,
    AlignmentReport,
    AlignmentResult,
    CeremonyResult,
    CeremonyVerdict,
    capability_alignment,
    drift_alignment,
    kfm_state_alignment,
    schema_alignment,
    version_alignment,
)
from .emergence import (
    EvolutionKind,
    EvolutionRecord,
    ObservationRecord,
    detect_protocol_drift,
    forget_peer,
    journal_dir,
    list_for_peer,
    record_observation,
    record_observations_from_registry,
)
from .model_peers import (
    CONSULT_CAPABILITY,
    consult_selected_peer,
    model_peers_enabled,
    register_model_peers,
)
from .peer_dispatch import PeerAwareDispatcher, PeerCallRefused
from .peer_selection import (
    PeerCandidate,
    choose,
    peer_selection_enabled,
    select_peer,
)
from .peer_trust_journal import (
    TrustDecisionRecord,
    latest_per_peer,
    list_decisions,
    record_decision,
    trust_journal_dir,
)
from .trust_policy import (
    PeerStateCache,
    PeerTrustPolicy,
    PolicyDecision,
    PolicyResult,
    is_always_allowed_peer_tool,
    peer_name_from_tool,
)
from .registry import (
    PeerEntry,
    forget,
    list_peers,
    register,
    registry_dir,
    sweep_stale,
)
from .emergence_sync import EmergenceSyncResult, serialize_journal, sync_remote_emergence
from .remote_sync import SyncResult, sweep_remote_stale, sync_remote_peers

__all__ = [
    "AgentIdentity",
    "AlignmentCeremony",
    "AlignmentReport",
    "AlignmentResult",
    "CeremonyResult",
    "CeremonyVerdict",
    "capability_alignment",
    "drift_alignment",
    "kfm_state_alignment",
    "schema_alignment",
    "version_alignment",
    "EvolutionKind",
    "EvolutionRecord",
    "ObservationRecord",
    "detect_protocol_drift",
    "forget_peer",
    "journal_dir",
    "list_for_peer",
    "record_observation",
    "record_observations_from_registry",
    "PeerEntry",
    "fetch_peer_identity",
    "fetch_peer_kfm",
    "forget",
    "list_peer_chimeras",
    "list_peers",
    "list_xenocomm_tools",
    "CONSULT_CAPABILITY",
    "consult_selected_peer",
    "model_peers_enabled",
    "register_model_peers",
    "PeerAwareDispatcher",
    "PeerCallRefused",
    "PeerCandidate",
    "choose",
    "peer_selection_enabled",
    "select_peer",
    "PeerStateCache",
    "PeerTrustPolicy",
    "PolicyDecision",
    "PolicyResult",
    "is_always_allowed_peer_tool",
    "peer_name_from_tool",
    "TrustDecisionRecord",
    "latest_per_peer",
    "list_decisions",
    "record_decision",
    "trust_journal_dir",
    "register",
    "registry_dir",
    "sweep_stale",
    "SyncResult",
    "sync_remote_peers",
    "sweep_remote_stale",
    "EmergenceSyncResult",
    "serialize_journal",
    "sync_remote_emergence",
]
