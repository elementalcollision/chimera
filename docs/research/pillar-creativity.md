# Pillar: Creativity

## TL;DR

- **Bounded divergence + semantic dedup**: Opus generates 0–3 task proposals per cycle; fingerprinting + cluster-verb matching collapse near-duplicates before queuing, preventing proposal explosion.
- **Multi-tier critic loop**: Ideas flow through escalating gates (Opus evaluation → Sonnet assembly → sandbox validation → witness review → activation), burning expensive tokens only on high-confidence proposals.
- **Structural novelty + mode rhythm**: Rather than embedding similarity, Leonardo's Vitruvian inverts activity counts per 5 body regions to identify gaps; the agent then oscillates through 6 cognitive modes (OBSERVE→PLAY→THEORIZE→DEVELOP→EXPRESS→CORRESPOND) + 13+ voices, ensuring temporal and epistemic diversity without retraining.

---

## Pattern 1: Bounded Divergent Generation via Structured Task Proposals

**Source:** `research/_clones/claude-daemon/daemon/task_proposals.py:1–289`

**What it does:** The strategy engine (Opus tier) generates 0–3 concrete task proposals per planning cycle. Each proposal is a JSON object with `text` (actionable imperative), `rationale` (one-sentence why), and optional `tool_hint` (registered tool name). Proposals are extracted from a fenced ```tasks block in the LLM response. The hard cap `MAX_PROPOSED_TASKS_PER_PLAN = 3` (line 39) is explicit and enforced.

**Why we adopt:** Unbounded generation burns tokens and floods the mutation queue. The hard cap prevents "three riffs on the same lesson" from accumulating across cycles (line 14). Opacity into why Opus chose those 3 is acceptable; the architecture trusts Opus's priority ranking.

**How it fits Chimera:** This is the *discrete divergence mechanism*. In a multi-LLM setting, each tier (Opus for planning, Haiku for routine tasks) can emit bounded proposals. Chimera can extend this by tier—e.g., Opus proposes 0–3 *major* directions, Sonnet proposes 0–5 *refinements* of one major direction. The bound is the control knob that prevents combinatorial explosion.

---

## Pattern 2: Semantic Deduplication via Fingerprinting + Cluster Verbs

**Source:** `research/_clones/claude-daemon/daemon/task_proposals.py:165–289`

**What it does:** Two-pass deduplication runs on extracted proposals:

1. **Fingerprint** (lines 165–179): Lowercase, strip non-alphanumeric, drop stopwords (line 28–34), hash the first 10 content words sorted alphabetically. Catches "recall prior NOTES on machine state" vs "recall prior REFLECTIONS on machine-state" as equivalent.
2. **Cluster verb** (lines 130–162): Normalize verbs ("append_to_file" → "append", "add" → "append") via `_CLUSTER_VERB_NORMALISATION` table (lines 77–120). Extract target basename and pair it with canonical verb as a cluster key `(basename, verb)`. Catches "Append the lesson to mind/LESSONS.md" vs "Use append_to_file to add a lesson entry to mind/LESSONS.md" as the same intent (both map to `("lessons.md", "append")`).

**Why we adopt:** LLMs rephrase the same idea across consecutive calls. Without this, the queue fills with semantic duplicates that burn operator decision cycles. The two-axis approach—content overlap + intent normalization—catches both surface and structural duplication. Inline dedup is cheap (pure string operations) and happens at extraction time, before proposals reach the queue.

**How it fits Chimera:** In a multi-LLM setup, different tiers may propose the same idea in different phrasing. Fingerprinting allows Chimera to globally deduplicate across all tiers' outputs, not just within one tier. The cluster-verb table can be extended to Chimera's task domain (e.g., add domain-specific verbs like "query_qdrant", "route_to_model", "save_checkpoint").

---

## Pattern 3: Critic Loop via Opus Evaluation (Evolution Engine)

**Source:** `research/_clones/claude-daemon/daemon/evolution.py:201–241`

**What it does:** The evolution engine's knowledge evaluation phase calls Opus to decide on discovered knowledge (line 203–241). Each discovery candidate is assigned a `disposition`: pending → accepted/rejected/skill_proposed. Opus receives the candidate's source, description, and content preview, then decides: ACCEPT (ingest to memory), REJECT (discard), or SKILL (propose as new dynamic tool). Evaluation is gated by rate limits (router checks `can_call(ModelTier.OPUS)`, line 92) and budget alerts (hard/soft caps, lines 100–108).

**Why we adopt:** Not all discovered knowledge is equally valuable. An expensive Opus-tier evaluation pass sorts signal from noise *before* more expensive downstream phases (Sonnet code generation, sandbox validation). Without this gate, every discovery flows to assembly, burning tokens on low-confidence proposals. The tier gating system—Opus evaluation gates Sonnet assembly gates Haiku validation—enforces economic scarcity of judgment.

**How it fits Chimera:** In Chimera, every new idea (from any LLM or external source) should flow through a critic. This can be a dedicated critic model (e.g., Opus) or a confidence threshold. The evolution engine shows that *async, infrequent criticism* (Opus called max 4/hour) is sufficient; not every proposal needs real-time critique. Chimera can route discoveries through a policy-based critic that may delegate to Opus, a rule engine, or a lightweight heuristic depending on confidence.

---

## Pattern 4: Multi-Tier Skill Assembly Pipeline

**Source:** `research/_clones/claude-daemon/daemon/evolution.py:372–473` (assembly), `475–542` (test generation), `556–629` (validation)

**What it does:** Accepted knowledge proposals flow through a maturity pipeline:

- **Assembly** (line 372–473): Sonnet generates async handler function + JSON schema. Handler must be pure Python (no subprocess, network, eval), accept `**kwargs`, return `str`. Tests are generated separately (lines 475–542).
- **Validation** (line 556–629): Assembled code runs in a sandboxed subprocess + optionally reviewed by a witness model (line 631–679). Validation score blends sandbox result (60% weight) and witness confidence (40% weight). Minimum 0.6 to pass (line 610).
- **Activation** (line 706–793): Validated proposals queued for operator approval (if trust < AUTONOMOUS) or auto-activated (if T4+). Hard cap: 20 dynamic skills max (line 123); proposals that fail twice are skip-retried (lines 351–368).

**Why we adopt:** The pipeline enforces escalating confidence gates before code reaches production. Discovery is free; evaluation costs Opus tokens; assembly costs Sonnet tokens; validation costs sandbox time + witness tokens. Repeated failures are pruned (line 351–368: `max_failures=2`), preventing budget waste on fundamentally flawed proposals. The witness corroboration (line 631–679) adds a second opinion: even if sandbox passes, witness can veto if code is unsafe.

**How it fits Chimera:** Chimera will likely spawn new tools/skills at runtime (e.g., when discovering a new API). This pipeline can be adopted directly: discover → evaluate (Opus) → assemble (Sonnet) → validate (sandbox) → activate. In Chimera, the witness could be a specialized safety model or a formal verification pass. The hard cap (20 dynamic skills) and failure pruning prevent unbounded tool creation.

---

## Pattern 5: Structural Novelty Scoring via Gap-Mapping (Vitruvian)

**Source:** `research/_clones/leonardo-daemon/daemon/vitruvian/scoring.py:278–368`

**What it does:** Vitruvian computes per-region gaps across 5 body regions (head/heart/hands/eyes/feet) via a multi-stage pipeline:

1. **Domain projection** (lines 36–45, 201–246): Activity counts per domain (anatomy, optics, hydraulics, botany, music, philosophy, engineering, art) are mapped onto regions via static weights. E.g., "optics" → {head: 0.4, eyes: 0.6}. Unmapped domains contribute uniformly (1/5 to each region).
2. **Activity blending** (lines 81–101): Recent activity (30-cycle window, 70% weight) blends with lifetime activity (30% weight) per region.
3. **Gap inversion** (lines 252–272): Activity is inverted to scarcity: region with highest activity has gap ≈ 0; untouched region has gap = 1.0. Normalized by max activity so output is [0, 1].
4. **Composite** (lines 112–132): Three gap axes (touched/cited/promoted) blend at weights 0.5 / 0.3 / 0.2 per region.
5. **Frustration amplifier** (lines 171–195): Failure signal (per-region frustration) asymmetrically boosts gap score (+10% cap per region). High frustration in a region → higher gap → more scheduling weight for that region.
6. **Softmax** (lines 138–165): Final scores softmaxed to a probability distribution over regions (sums to 1.0).

**Why we adopt:** Rather than comparing embeddings of candidate outputs, Vitruvian compares the *structural profile* of what the agent has explored and inverts it. High gap = "this region is under-explored relative to others" = novel work likely when visited. The frustration amplifier adds adaptive feedback: if the agent struggles in region X (high frustration), region X's gap is boosted, forcing attention there. This creates a *negative feedback loop* that drives novelty toward struggling points, not away from them.

**How it fits Chimera:** Gap-mapping can be adopted as a domain-agnostic novelty heuristic. Instead of 5 body regions, Chimera could define regions as task categories, model tiers, or capability domains. The inversion principle—under-explored areas are novel—applies universally. Frustration amplification is particularly valuable: if Chimera discovers that reasoning tasks fail frequently, the scheduler can boost reasoning-task weight, driving exploration *into* the weak spot rather than around it.

---

## Pattern 6: Rhythmic Mode Oscillation

**Source:** `research/_clones/leonardo-daemon/daemon/modes.py:31–179`

**What it does:** Leonardo runs 6 cognitive modes in a weighted random schedule (line 165–169):

- **OBSERVE** (dawn): Passive intake, retrieval-heavy (decay weight 1.2)
- **PLAY** (morning): Recombinatory, cross-domain analogy (decay weight 1.5)
- **THEORIZE** (midday): Hypothesis generation, "possibly-wrong OK" (decay weight 1.5)
- **DEVELOP** (afternoon): Iterative refinement, Opus-tier (decay weight 1.0)
- **EXPRESS** (evening): Multimodal output, prose + diagram (decay weight 1.0)
- **CORRESPOND** (on-demand): Letter-writing voice (decay weight 0.8)
- **CONTEMPLATION** (night): Dream/integration, introspection signature at L4 (decay weight 1.0)

Weights are bounded [5%, 40%] per mode (lines 50–51, 100–143) via water-filling renormalization. The scheduler picks modes via weighted random selection. At L2.5+, Vitruvian adjusts weights based on gap-map output, routing more scheduling weight to under-explored regions.

**Why we adopt:** Different modes have different generative *affordances*. PLAY specializes in cross-domain recombination; THEORIZE tolerates wrong-ness (exploration); DEVELOP refines. Alternating modes within a single agent prevents local optima: a stuck DEVELOP phase can be interrupted by a THEORIZE phase that reopens the problem space. The bounded weights prevent mode starvation or dominance; every mode gets a chance within a bounded window.

**How it fits Chimera:** Chimera can adopt this as a *cognitive scheduling layer*. Instead of always running in "reasoning" mode, Chimera cycles through exploration (THEORIZE), refinement (DEVELOP), and expression (EXPRESS) phases. Each mode can have different token budgets, reasoning depth, or tool access. The scheduler ensures no phase is starved. Vitruvian's gap-map feedback can integrate directly: if a region (e.g., "visual reasoning") is under-explored, boost modes that touch vision (e.g., EXPRESS with image generation).

---

## Pattern 7: Multi-Voice Generation (Epistemic Polymorphism)

**Source:** `research/_clones/leonardo-daemon/daemon/voice.py:114–200`

**What it does:** Leonardo supports 13+ voices for system prompts, each offering a distinct epistemic stance:

- **first**: "I observed...", introspective
- **third**: "The daemon observed...", detached narration
- **contrarian**: "I doubt...", challenge-focused
- **apophatic**: "What is *not*...", negation-based (constraints and boundaries)
- **lyrical**: Emotional/subjective knowledge
- **systematic**: Rational orthodoxy, structured classification
- **aesthetic**: Taste, specificity, radical particularity
- **esoteric**: Symbol-as-truth, body-speech-mind integration

Each voice is a system prompt preamble (lines 114–128 inject via `voice_preamble(role)`). The voice is set once at startup but the architecture permits per-call overrides (future work). Every preamble includes a UTC clock anchor (lines 80–100) to prevent date hallucination.

**Why we adopt:** Different voices produce different candidate ideas from the same prompt. Contrarian voice forces counter-arguments. Apophatic voice generates constraints and boundaries. Aesthetic voice grounds in irreducible particularity. Voices are *cheap* (prompt variation only, no retraining) but high-impact on output diversity. An agent can generate candidates in THEORIZE mode with lyrical voice, then THEORIZE mode with contrarian voice—two passes, two epistemic stances, same mode.

**How it fits Chimera:** Chimera can adopt voice as a *prompting-level divergence knob*. Instead of calling Opus once, call it N times with N different voices. Each voice produces different concerns, framings, and candidate ideas. The voice system is modular: add new voices by extending the preamble table. This is particularly powerful for critique: call a contrarian voice to challenge a proposal, call an aesthetic voice to ground it in particularity, call an apophatic voice to find what *can't* be said.

---

## Rejected / Weak Spots

- **Free-form generation without caps**: Claude-daemon enforces `MAX_PROPOSED_TASKS_PER_PLAN = 3` (line 39); Leonardo caps dynamic skills at 20 (line 123). No unbounded divergence is observed in production code. Unlimited generation was not pursued.
- **Embedding-based nearest-neighbor filtering**: While Jina embeddings (2048-dim vectors) are available in Leonardo (`research/_clones/leonardo-daemon/daemon/jina_client.py`), they are scoped to image retrieval and express-mode generation at L1. They do *not* drive primary novelty scoring. Novelty is instead driven by structural gap-mapping (activity inversion), not vector similarity.
- **Critic models that gate divergence in-flight**: Evaluation happens *after* extraction. Proposals are generated, then filtered by dedup logic, then evaluated by Opus. No pre-generation critic (e.g., "ask Opus if this idea is worth proposing") is observed. The architecture accepts that Opus will sometimes propose low-value ideas and filters them downstream.
- **Per-mode proposal budgets**: All modes share the same 0–3 proposal budget (line 39). No per-mode allocation is observed. PLAY and THEORIZE don't get more proposal slots than DEVELOP.
- **Skill proposal feedback loop**: Skills once activated (line 790) do not feed back into gap-map or mode weighting. Dynamic skills are created but don't reshape the creativity machinery. This is a gap for L4+ maturity.

---

## Open Questions for the User

1. **Reggio driving logic** — Claude-daemon is described as "Reggio driving logic for Leonardo." What is the full Reggio loop? Current read shows proposal generation → dedup → evolution pipeline, but what feedback mechanism connects task execution back to goal/lesson state? Does Reggio drive *goal mutation* based on outcomes, or is it purely task-level?
2. **Leonardo L4 contemplation phase** — The modes module mentions "contemplation phase becomes the L4 signature rhythm." What does L4 contemplation actually *do*? State consolidation, mode-weight reset, voice re-sampling?
3. **Jina embedding integration in UAT variant** — Was Jina used to drive mode weighting (e.g., cosine distance of candidate outputs from prior work as a novelty signal)? Or purely for image retrieval? What did the experiment reveal?
4. **Multi-LLM creativity patterns** — Should Haiku and Opus have distinct creativity patterns? E.g., Opus generates proposals, Haiku generates refinements? Or all tiers run the same machinery? Should lower-tier models explore more (higher THEORIZE weight)?
5. **Voice + mode independence** — Are voice and mode completely orthogonal, or are certain pairings locked? Does the scheduler compose them, or is voice fixed at startup and modes rotate?
6. **Skill feedback into novelty** — When a dynamic skill activates, should it reshape the gap-map? If a skill is "query_new_api", does the "api_integration" region's gap drop?

---

## References

- **Task proposal extraction & dedup**: `research/_clones/claude-daemon/daemon/task_proposals.py:1–289` — fingerprinting, cluster verbs, proposal bounds, dedup logic
- **Evolution engine & skill pipeline**: `research/_clones/claude-daemon/daemon/evolution.py:140–847` — discovery, evaluation, assembly, validation, activation; hard caps and failure pruning
- **Strategy engine (planning)**: `research/_clones/claude-daemon/daemon/strategy.py:49–350` — Opus calls, rate limiting, budget checks, task proposal extraction integration
- **Cognitive modes & scheduling**: `research/_clones/leonardo-daemon/daemon/modes.py:31–289` — 6 modes + contemplation, weighted random selection, bounds enforcement, mode boost
- **Vitruvian gap-mapping**: `research/_clones/leonardo-daemon/daemon/vitruvian/scoring.py:20–369` — domain projection, activity blending, gap inversion, frustration amplifier, softmax, end-to-end score_gap_map
- **Voice polymorphism**: `research/_clones/leonardo-daemon/daemon/voice.py:103–200` — 13+ epistemic stances, preamble generation, clock anchor, voice-specific system prompts
- **Jina embeddings client**: `research/_clones/leonardo-daemon/daemon/jina_client.py:1–82` — 2048-dim text/image embeddings, currently scoped to image retrieval at L1
