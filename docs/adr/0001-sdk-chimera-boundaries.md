# ADR 0001 — SDK Chimera Boundaries

**Status:** Accepted (pending Phase 0 sign-off)
**Date:** 2026-05-18
**Context:** Phase 0 Research Spike — closes Task 0.7.

## Context

Chimera is a "chimera orchestrator" — a thin Python core that pulls best-of-breed components from multiple agent SDKs. No single SDK is the spine. This ADR fixes, per concern, which SDK or pattern wins and why. It is the contract Phase 1+ code must respect; deviations require a follow-up ADR.

Anchored on Phase 0 deliverables:
- [pillar-adaptability.md](../research/pillar-adaptability.md)
- [pillar-creativity.md](../research/pillar-creativity.md)
- [pillar-ontology-drift.md](../research/pillar-ontology-drift.md)
- [pillar-positioning.md](../research/pillar-positioning.md)
- [tool-layer-survey.md](../research/tool-layer-survey.md)

User decisions baked in:
- Both drift detectors adopted (behavioral + stagnation) — orthogonal axes.
- Cognitive modes / voice polymorphism = **inspiration only**. Chimera has its own composite voice; no 6-mode scheduler in v1.
- Single orchestrator with role-typed F/M/K methods — no multi-process operator split until Xenocomm/A2A.
- `drift-monitor` library is **fallback-only** for MVP.

## Decisions

### Per-concern ownership

| Concern | Owner | Why |
|---|---|---|
| **Agent loop / orchestration** | Custom thin Python (`chimera/core`) | No single SDK does multi-LLM + chimera tool layer well. Thin orchestrator keeps switching costs low. |
| **LLM provider abstraction** | Custom (`chimera/providers/`) wrapping official `anthropic` SDK + raw `httpx` for OpenRouter | OpenRouter exposes an OpenAI-shaped API; using two narrow adapters is simpler than a third-party wrapper. |
| **Model tier ladder + routing** | Port of Leonardo's `MODEL_TIERS` + `LadderRung` (`leonardo-daemon/daemon/config.py:62`) | User-canonicalized routing baseline. |
| **Tool registry** | Hermes pattern — `registry.register(name, toolset, schema, handler, check_fn, ...)`, AST auto-discovery, TTL-cached `check_fn` | Most composable and auditable design surveyed. Re-implemented; no Hermes dependency. |
| **Tool dispatch policy** | OpenClaw pattern — multi-layer policy pipeline (global / provider / agent / session) applied **pre-dispatch** | Decouples *can run* from *is available*. Critical for safe sub-agent delegation. |
| **Tool sandbox** | In-process for read-only tools; subprocess (later container) for execution tools. Shell tool gets a strict allow-list at MVP. | Concentric ring expansion (PLAN §Phase 3). |
| **MCP client** | Official `mcp` Python SDK | Standard protocol; no reason to roll our own. |
| **MCP server (Chimera exposing itself)** | Deferred to v2 — only relevant for Xenocomm/A2A. | Out of v1 scope. |
| **KFM functional ontology** | Port of `village/services/clerk/src/clerk/kfm.py` — pure stateless `check_transition()`, table-driven authority | Canonical operationalization of the Agentic_Evolution thesis. |
| **F/M/K operators** | **Single orchestrator with role-typed methods** (per user decision). Not separate processes. | docker-compose single-user scope. Revisit at Xenocomm time. |
| **Behavioral drift detector** | Port of `leonardo-daemon/safeguards/drift.py` **fallback path only** (vocabulary set + tool-count dict). Three-instrument design preserved; `drift-monitor` library not depended on. | User decision; minimal MVP dependency surface. |
| **Stagnation drift detector** | Port of `autoresearch-unified/tui/orchestrator.py:582 _detect_stagnation()` | Orthogonal to behavioral drift; cheap heuristic. |
| **Drift response policy** | `chimera/drift_policy.py` — typed signals → `{NUDGE, OBSERVE, DEMOTE_PLAN, KILL_SESSION}` actions, KFM-aware | Synthesized from Phase 0; see [pillar-ontology-drift.md Pattern 4](../research/pillar-ontology-drift.md). |
| **Memory / persistence** | See [ADR 0002](0002-memory-strategy.md) | Separate decision. |
| **Voice / prompt style** | Custom single composite voice (per user decision). Leonardo's 13-voice system is **inspiration only**, not adopted as a runtime. | User decision. |
| **Cognitive modes (Leonardo)** | Not adopted in v1. | User decision; reconsider in v2 if value emerges from creativity layer. |
| **Hardware probing** | Adopt autoresearch's `get_hardware_summary()` pattern; container-aware. | [pillar-adaptability.md Pattern 1](../research/pillar-adaptability.md). |
| **History formatting for prompts** | Adopt autoresearch's `format_history_for_prompt()` + strategy classification. | [pillar-adaptability.md Pattern 2](../research/pillar-adaptability.md). |
| **Proposal generation + dedup** | Adopt claude-daemon's `MAX_PROPOSED_TASKS_PER_PLAN = 3` + fingerprint/cluster-verb dedup. | [pillar-creativity.md Patterns 1–2](../research/pillar-creativity.md). |
| **Skill/tool assembly pipeline** | Adopt claude-daemon's discover → evaluate → assemble → validate → activate (Phase 3+, not MVP). | [pillar-creativity.md Pattern 4](../research/pillar-creativity.md). |
| **Activity log + circuit breaker + skip-memo** | Adopt village's patterns. Activity log is the heartbeat. Circuit breakers wrap every peer call. | [pillar-positioning.md Patterns 1, 5, 6](../research/pillar-positioning.md). |
| **Signal handling / graceful shutdown** | Adopt village's `install_drain_handlers` + 30s drain timeout. | [pillar-positioning.md Pattern 3](../research/pillar-positioning.md). |
| **A2A / inter-agent comms** | Out of v1 scope. xenocomm_sdk is a v2 candidate. | Plan §Phase 5. |
| **Croissant serialization for ontology** | Deferred to ADR 0002 / v1+. | [pillar-ontology-drift.md](../research/pillar-ontology-drift.md). |

### Module layout (consequence of the above)

```
chimera/
  core/                # agent loop, plan state, KFM transitions
    loop.py
    kfm.py             # ← port of village/services/clerk/src/clerk/kfm.py
  providers/
    base.py
    anthropic.py
    openrouter.py
    tiers.py           # ← port of leonardo-daemon/daemon/config.py MODEL_TIERS
  tools/
    registry.py        # Hermes-style register() + TTL check_fn cache
    dispatch.py        # OpenClaw-style policy pipeline pre-dispatch
    shell.py           # MVP tool: strict allow-list
  drift/
    behavioral.py      # fallback-only port of leonardo-daemon/safeguards/drift.py
    stagnation.py      # port of autoresearch _detect_stagnation
    policy.py          # signal → {NUDGE, OBSERVE, DEMOTE_PLAN, KILL_SESSION}
  positioning/
    activity_log.py    # village-style heartbeat-as-proof-of-work
    drain.py           # signal handlers
    circuit.py         # circuit-breaker for peer calls
  prompts/
    voice.py           # single composite Chimera voice
    history.py         # autoresearch format_history_for_prompt
    hardware.py        # autoresearch get_hardware_summary, container-aware
  proposals/
    generate.py        # claude-daemon-style 0-3 proposals
    dedup.py           # fingerprint + cluster-verb
  memory/
    # populated per ADR 0002
```

## Consequences

- **No hard dependency on Hermes, OpenClaw, Leonardo, Village, or autoresearch packages.** Every adopted pattern is re-implemented in `chimera/` with attribution citations in the source code. Source repos remain reference-only in `research/_clones/` (gitignored).
- **Two dependencies that ARE adopted:**
  - `anthropic` (official Python SDK) — for Anthropic provider.
  - `mcp` (official Python SDK) — for the MCP client.
  - Plus `httpx`, `pydantic` v2, and `pytest` for testing.
- **`drift-monitor` is NOT a dependency** — fallback path only. Upgrade path documented in `chimera/drift/behavioral.py` docstring.
- **The Reggio feedback loop is an open input from the user (Open Question #2 across pillars).** ADR is silent on it for now; will be addressed in a follow-up ADR once user inspection completes.
- **TS control plane** (PLAN §Phase 5) is the only non-Python surface in v1; deferred until core loop is stable.

## Open Items (deferred to follow-up ADRs)

1. **ADR 0003 (Reggio loop)** — once the user inspects, encode the feedback mechanism that connects task execution back to goal/lesson state.
2. **ADR 0004 (Tool sandbox elevation)** — exact mechanism for elevating a shell command past the MVP allow-list (subprocess flags, container `--cap-add`, or seccomp profile).
3. **ADR 0005 (Sub-agent spawn semantics)** — once Phase 3 task 3.4 is reached, codify how a cross-model sub-agent inherits a parent's tool policy.

## References

- All Phase 0 research deliverables under `docs/research/`.
- `PLAN.md` § Architecture Decisions.
