# Pillar: Functional Ontology + Drift

## TL;DR

Chimera should adopt four patterns from across the source set:

1. **KFM lifecycle ontology** — represent every agentic entity (skills, tools, sub-agents, plans, models) as a node in a 7-state machine (`NEW → EXPERIMENTAL → CANDIDATE → STABLE → DEPRECATED → ARCHIVED → KILLED`), authority gated by F/M/K operator types. Pure table-driven, stateless transition check.
2. **Multi-instrument behavioral drift detector** (from Leonardo) — composite score across **vocabulary decay**, **tool-usage distribution shift**, and **semantic center-of-gravity movement**, with configurable thresholds and graduated response.
3. **Stagnation drift detector** (from autoresearch) — orthogonal to behavioral drift; catches the agent stuck in a single strategy bucket, responds with a non-disruptive prompt nudge.
4. **Graduated drift response** — combine Leonardo's lockdown-style (Tier-0 demotion) with autoresearch's nudge-style. Behavioral drift → trust-tier demotion; stagnation drift → prompt-time nudge. Different drift kinds get different responses.

The thesis (Agentic_Evolution) is the descriptive theory; village's `clerk/kfm.py` is the canonical operationalization; Leonardo's `safeguards/drift.py` is the canonical detector. Croissant is **deferred** — evaluated as a serialization candidate only once the agentic entity schema is firm.

---

## Pattern 1: KFM Lifecycle Ontology — 7-State Machine

**Theoretical source:** `research/_clones/Agentic_Evolution/README.md` §3 (Ontology of Evolving Agents), §7 (KFM-AE Model), §8.2 (PRD Principle 1: Explicit Lifecycle State Tracking).

**Code source:** `research/_clones/village/services/clerk/src/clerk/kfm.py:39–100`.

**What it does:**
Every "agentic entity" in the system (software artifact, AI model, data structure, autonomous agent — per thesis §3.1) is tagged with a `kfm_lifecycle_state` from a fixed enum:

```python
KFM_STATES = ("NEW", "EXPERIMENTAL", "CANDIDATE", "STABLE", "DEPRECATED", "ARCHIVED", "KILLED")
```

Transitions are **table-driven** and **linear** in the current implementation (no cycles, no skip-ahead). Each transition is authorized by exactly one operator type from `OperatorType = Literal["f", "m", "k", "bootstrap"]`:

| From | To | Operator | Meaning |
|---|---|---|---|
| NEW | EXPERIMENTAL | F | Formation — agent enters mutation phase |
| EXPERIMENTAL | CANDIDATE | M | First review — proven enough to promote |
| CANDIDATE | STABLE | M | Second review — integration approved |
| STABLE | DEPRECATED | K | Begin decommission |
| DEPRECATED | ARCHIVED | K | Cold storage |
| ARCHIVED | KILLED | K | Terminal |

`check_transition(from_state, to_state, operator_type)` is a **pure** function — never raises, never touches a DB, returns a structured result. State writes happen in a separate router layer (`clerk.routers.agents`) that calls the checker first.

**Why we adopt:**
- **Direct mapping from theory to code.** The thesis explicitly calls for "STATE = {EXPERIMENTAL, INTEGRATING, STABLE, DEPRECATED, ARCHIVED, KILLED}" (§8.2 PRD-1); village added `NEW` and `CANDIDATE` as the two pre-EXPERIMENTAL/pre-STABLE staging states. This is a faithful operationalization, not a metaphor.
- **Pure transition function** makes the ontology testable, replayable, and trivially shareable across services (Constable, Clerk, future Chimera modules).
- **Operator-typed authority** prevents any single agent from unilaterally promoting itself — it must convince an M-Operator or be demoted by a K-Operator. Anti-runaway property by construction.
- **Event-sourced.** Transitions emit a `village.agent.state-transitioned` event (`from_state`, `to_state`, `authorized_by_operator`); downstream consumers project their own views.

**How it fits Chimera:**
- Wrap **every** Chimera-owned entity in a KFM record: skills, tools, sub-agents, MCP server connections, prompts, even individual plans.
- The orchestrator owns the F/M/K operators as internal roles, not separate processes. Frequency-based promotion (e.g., "tool used 10× without error → M proposes EXPERIMENTAL → CANDIDATE") implements the thesis's "fitness criteria" (§8.2 PRD-2).
- Ontology state IS the routing/permission signal: Chimera's tool gate (Pattern in 0.6) refuses to invoke a `DEPRECATED` tool, prefers a `STABLE` one over `EXPERIMENTAL` when both are available.
- Use the exact transition table as a starting set; extend with non-linear transitions only via explicit ADR.

---

## Pattern 2: Multi-Instrument Behavioral Drift Detector

**Source:** `Claude_Primary/leonardo/leonardo-daemon/safeguards/drift.py:1–280` (full module is 411 lines).

**What it does:**
A composite drift detector — Layer 5 of Leonardo's safety envelope — that monitors agent behavioral consistency across sessions using three orthogonal instruments from a separate `drift_monitor` library:

| Instrument | Weight | Measures | Threshold |
|---|---|---|---|
| `GhostLexicon` | 0.35 | Vocabulary decay — specialized terms disappearing from agent output | 0.30 |
| `BehavioralFootprint` | 0.35 | Tool-usage distribution shifts | 0.30 |
| `SemanticDrift` | 0.30 | Conceptual center-of-gravity movement (keyword-overlap fallback when embeddings off) | 0.15 |

Per call, the agent feeds `observe(text, metadata={"tools": [...]})`. Every `assessment_interval = 10` observations (after a `min_observations = 5` warmup), the detector calls `_assess_full()` which reads each instrument and combines via `DriftScorer(weights=...)` into a single `composite_score ∈ [0.0, 1.0]`. Two thresholds gate response:

- **`warning_threshold = 0.15`** → log warning, no enforcement
- **`lockdown_threshold = 0.30`** → trigger **Tier-0 lockdown** via TrustManager (Leonardo's trust-tier system)

**Boundary marking** is the key operational concept: before a session rotation, context compression, or memory reset, the agent calls `mark_boundary()`. The instruments snapshot their pre-boundary state and compare future observations against the snapshot — this is what makes drift measurable across context discontinuities.

The module has a **fallback path** for when the `drift_monitor` library isn't installed: it tracks `_fallback_vocab` (set) and `_fallback_tool_counts` (dict) and computes simplified scores. Means Chimera can ship without the dependency and upgrade later.

**Why we adopt:**
- **Three orthogonal axes** is exactly the right number — vocabulary captures *what* the agent talks about, behavioral footprint captures *what it does*, semantic drift captures *how it reasons*. Compositionality is the strength.
- **Composite score with weights** beats any-of-N alarm — minor drift on one axis doesn't lock down the agent; sustained drift across axes does.
- **Boundary-anchored** rather than rolling — survives the compression boundaries that are inevitable in long-running agents.
- **Lockdown-as-response is the right call for behavioral drift** — if the agent is no longer itself, you cannot trust it to course-correct itself; demote and re-anchor externally.
- **Fallback path** means we don't depend on the `drift_monitor` library as a hard requirement.

**How it fits Chimera:**
- Adopt the three-instrument architecture verbatim as Chimera's "identity drift" subsystem.
- Wire `observe()` calls into the agent loop after every tool call and every model response.
- Connect lockdown to the KFM ontology (Pattern 1): a lockdown demotes the running session's *plan* to `DEPRECATED`, forcing a re-anchor (new plan in `EXPERIMENTAL`). Drift response and lifecycle become the same mechanism.
- Vendor or fork `drift_monitor` only if needed; the fallback path is sufficient for MVP.

---

## Pattern 3: Stagnation Drift Detector (proposal-space drift)

**Source:** `research/_clones/autoresearch-unified/tui/orchestrator.py:582–615`, `orchestrator.py:665–667`.

**What it does:**
A second, complementary drift detector — but operating on the **proposal/strategy** axis rather than the **identity** axis. `_detect_stagnation()` examines the last 15 experiments: if fewer than 2 have been kept, it counts how many were `learning_rate`-category changes. If ≥8/15 were learning-rate tuning with ≤2 keeps, it returns a **nudge string**: "try a fundamentally different approach: batch size changes, architectural modifications, or schedule shape changes." The nudge is appended to the user prompt **as content, not as a hard constraint** — the LLM can ignore it if it has a good reason.

**Why we adopt:**
- **Detects a different failure mode** than behavioral drift. The agent can be entirely "itself" (no lexicon decay, no semantic shift, no tool-footprint change) and still be **stuck in a strategy local minimum**. Leonardo's drift detector won't catch this; autoresearch's will.
- **Stateless heuristic** — no model, no memory, no embeddings. Costs nothing.
- **Nudge response is correct for strategy drift** — the agent is still trustworthy; it just needs to be reminded of its option space. Lockdown would be overkill and counterproductive.

**How it fits Chimera:**
- Implement `detect_stagnation(history, window=N)` as a pure function over the last N proposals.
- Calibrate the bucket-saturation threshold to Chimera's task domain (the 8/15 LR threshold is HPO-specific).
- Wire the nudge into the prompt-construction step, not the model call — auditable and toggleable.
- **Together with Pattern 2:** two-axis drift surveillance — identity drift (behavioral) and strategy drift (stagnation). Different signals, different responses.

---

## Pattern 4: Graduated Drift Response (the synthesis)

**Source:** synthesis from `Agentic_Evolution/README.md` §8.2 PRD-3 ("Configurable Selection Thresholds/Policies") + `leonardo-daemon/safeguards/drift.py` + `autoresearch-unified/tui/orchestrator.py`.

**What it does:**
Drift response is **typed** by the drift signal, not uniform:

| Drift type | Signal | Response | KFM effect |
|---|---|---|---|
| **Stagnation** (strategy) | `_detect_stagnation()` returns nudge | Append nudge to next prompt | None (agent still trustworthy) |
| **Behavioral, warning** (identity, mild) | composite ∈ [0.15, 0.30) | Log + observe-only | None |
| **Behavioral, lockdown** (identity, severe) | composite ≥ 0.30 | Demote current plan to DEPRECATED | K-Operator transition |
| **Boundary cross + heavy drift** | composite ≥ 0.30 immediately after `mark_boundary()` | KILL current session, restart from STABLE plan | KFM "K → re-anchor" |

**Why we adopt:**
Maps directly to the thesis's §8.2 PRD-3 (configurable thresholds → KFM actions). The graduated table is the bridge from the descriptive ontology (KFM-AE) to a prescriptive runtime policy. Stagnation gets a hint; identity drift gets a tier change. Heavy post-boundary drift is treated as evidence the new context broke continuity → kill and restart.

**How it fits Chimera:**
- Single `drift_policy.py` module exposes `respond(signal: DriftSignal) -> DriftAction` that returns one of `{NUDGE, OBSERVE, DEMOTE_PLAN, KILL_SESSION}`.
- Actions are KFM transitions: DEMOTE_PLAN = `STABLE → DEPRECATED` on the current plan record; KILL_SESSION = full re-anchor to last `STABLE` checkpoint.
- Policy is configurable per ADR 0002 once memory backing is chosen.

---

## Croissant as Ontology Serialization — DEFERRED

**Source:** `research/_clones/croissant/` (mlcommons).

Croissant is a JSON-LD schema for **datasets**. It's a strong candidate for serializing the KFM ontology *if* we treat each agentic entity (skill, tool, plan, sub-agent) as a "data record" with provenance, lineage, and lifecycle. The JSON-LD payload would carry the entity's KFM state, the audit trail of F/M/K transitions, the operator authority chain, and the fitness criteria that justified each promotion.

But Croissant is **dataset-centric**, and Chimera's ontology has runtime/operational semantics Croissant wasn't designed for (e.g., "this entity is currently in EXPERIMENTAL, expected promotion review at next M-Operator pass"). Forcing it may add ceremony without saving work.

**Decision:** evaluate as a serialization layer in **ADR 0002 (Memory Strategy)** once the in-memory ontology shape is firm. Do not commit to Croissant in Phase 0.

---

## Rejected / Weak Spots

- **Linear-only transitions in village's current `LEGAL_TRANSITIONS`.** Chimera will need non-linear paths (e.g., `EXPERIMENTAL → KILLED` for an obviously-failed experiment, `DEPRECATED → EXPERIMENTAL` for revival). Adopt the table-driven approach but extend the table in ADR.
- **Hard-coded thresholds in Leonardo's `DriftConfig`** (0.30 lockdown, 0.15 warning). Fine for Leonardo's single-personality daemon; insufficient for Chimera's multi-model orchestrator. Make per-model and per-tier.
- **Stagnation detector is HPO-shaped.** The "learning_rate bucket saturation" heuristic doesn't generalize. Adopt the *pattern* (bucket-saturation triggers nudge), generalize the strategy-bucket taxonomy.
- **No drift detector currently handles cross-model drift** (i.e., the orchestrator silently routes a task that used to go to Sonnet over to Haiku). Neither Leonardo nor autoresearch covers this. Open problem for Phase 4.

---

## Open Questions for the User

1. **Authority model for F/M/K operators inside Chimera.** Village runs F/M/K as separate agent processes on the bus. Should Chimera have separate sub-agents per operator type, or fold them into roles inside a single orchestrator? (Recommendation: single orchestrator with role-typed methods; revisit if/when Xenocomm/A2A lands.)
2. **Entity granularity.** What gets a KFM record in Chimera? Definitely skills and tools. Plans? Individual model calls? Sub-agent invocations? Recommendation: skills, tools, plans, sub-agents — not individual model calls.
3. **Drift-monitor library availability.** Are we OK depending on Leonardo's `drift-monitor` package, or do we ship with the fallback only and upgrade later? (Recommendation: fallback-only for MVP, add as optional dep for v1.)
4. **Promotion fitness criteria.** What numeric/qualitative signals justify `EXPERIMENTAL → CANDIDATE`? Leonardo uses success-rate + drift-score combined; village uses external M-Operator review. Chimera's first cut?
5. **Cross-session ontology persistence.** Where does the KFM state live across container restarts? This is the question ADR 0002 answers — but the choice depends on whether ontology state changes mostly *atomically per transition* (relational fits) or *streamed continuously* (event store fits).
6. **Croissant evaluation depth.** Worth a half-day prototype to serialize a sample ontology in Croissant JSON-LD and see if the impedance is real? Or definitively defer to v1+?

---

## References

### Theoretical
- `research/_clones/Agentic_Evolution/README.md` §3 — Ontology of Evolving Agents (Floridi informational ontology, layered abstraction, agency dimensions)
- `research/_clones/Agentic_Evolution/README.md` §4 — Mapping KFM operators to lifecycle processes
- `research/_clones/Agentic_Evolution/README.md` §7 — KFM-AE model postulates
- `research/_clones/Agentic_Evolution/README.md` §8.2 — Seven PRD principles (lifecycle states, fitness criteria, configurable thresholds, F/M/K protocols, lifecycle-aware resource management, observability)

### Code
- `research/_clones/village/services/clerk/src/clerk/kfm.py:39–100` — 7-state machine, transition table, operator authority table, pure `check_transition()` function
- `research/_clones/village/services/constable/alembic/versions/0002_agent_kfm_state.py` — DB schema for `agent_kfm_state` projection
- `Claude_Primary/leonardo/leonardo-daemon/safeguards/drift.py:1–280` — three-instrument composite drift detector with boundary marking and graduated response
- `Claude_Primary/leonardo/leonardo-daemon/safeguards/trust.py` — TrustManager that drift detector calls on lockdown
- `research/_clones/autoresearch-unified/tui/orchestrator.py:582–615` — stagnation detector + nudge generator
- `research/_clones/autoresearch-unified/tui/orchestrator.py:665–667` — nudge-injection into prompt

### Deferred references
- `research/_clones/croissant/` — JSON-LD dataset schema; potential serialization layer (ADR 0002)
- External `drift-monitor` library — depended on by Leonardo's full assessment path; not yet evaluated for license/maintenance health
