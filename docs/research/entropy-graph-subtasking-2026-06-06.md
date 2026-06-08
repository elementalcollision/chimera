# Random graph theory & entropy optimization for Chimera sub-tasking

**Status:** Investigation / research note — no code change proposed.
**Date:** 2026-06-06
**Question:** How do random graph theory and theories of entropy optimization
apply to the way Chimera sub-tasks to *itself* and to *peer agents*, and where
are the concrete levers?

---

## 0. The two sub-tasking surfaces, as they exist today

Both are **deterministic decision trees with hand-tuned constants** — which is
exactly the surface these theories address.

**To itself** (single process):

| Decision | Current rule | Site |
|---|---|---|
| PLAN proposes work | hard cap **3** proposals/cycle, fingerprint+cluster dedup | `proposals/generate.py:28`, `proposals/dedup.py` |
| Task split fan-out | confidence ≥ 0.5 → model split capped at **6** | `core/task_splitter.py:152,244` |
| Sub-agent recursion | fixed `max_depth=2`, `max_rounds=4` | `tools/subagent.py:81,83` |
| Parallel tool fan-out | **unbounded** (whatever the model emits) | `core/act.py:3195` |
| Tier/rung escalation | Jaccard ≥ 0.5 → +1 rung; 3-strikes auto-skip | `core/escalation.py`, `core/remediation.py:40` |

**To peers** (A2A federation):

- Registry is an **unordered set of JSON files** (`a2a/registry.py`); remote peers
  discovered by HTTP `/healthz` probe (`a2a/remote_sync.py`).
- Dispatch is **single-target**: the tool name `mcp-<peer>-<tool>` hard-codes the
  peer; `PeerAwareDispatcher` (`a2a/peer_dispatch.py`) only *gates* the call
  (ALLOW/DEGRADE/REFUSE) on trust tier + KFM state + drift. **No candidate
  selection, no load balancing, no scoring, no randomness.**
- A **graph projection already exists** in Kuzu (`memory/graph.py`): `Peer` nodes,
  directed `TRUSTED(drift_score, verdict)` and `BELIEVES_ABOUT(label, drift_score)`
  edges — but it is **read-only and unused for routing**.
- `CircuitBreaker` (CLOSED/OPEN/HALF_OPEN, `positioning/circuit.py`) exists but is
  **not wired into peer dispatch**.

The headline: there is **no randomness, no entropy signal, and no
load/topology-aware allocation anywhere** in either path. The graphs Chimera
needs already exist latently; the theory tells us what to compute over them and
which constants to replace with policies that have a *meaningful knob*.

---

## 1. The three latent graphs

| Graph | Nodes / edges | State today |
|---|---|---|
| **G1 — decomposition DAG** | tasks → sub-tasks (PLAN proposals, splits, sub-agent recursion) | shallow tree, depth ≤ 2, fan ≤ 6, ≤ 3 proposals; never materialised as a graph |
| **G2 — federation graph** | peers; `TRUSTED` / `BELIEVES_ABOUT` edges weighted by drift | **materialised in Kuzu, inert** |
| **G3 — tool/skill graph** | core + `dynamic` + `mcp-*` tools | dashboard already renders a "skill graph" widget |

Everything below is "what to compute over G1/G2/G3."

---

## 2. Random graph theory

### 2a. Federation resilience = percolation on G2 (highest-value graph result)

Model the **trust-reachable** federation as a random graph: a directed edge
A→B exists iff A's policy would `ALLOW` dispatch to B (trust ≥ T2 **and** drift <
`lockdown_drift_threshold=0.30`). Peer churn, drift rises, and lockdowns are
**bond/site percolation** events that delete edges/nodes.

- **Giant component / percolation threshold.** Below a critical connectivity the
  swarm shatters into islands that cannot collectively cover the capability set.
  For an Erdős–Rényi view the giant component appears at mean degree ⟨k⟩ > 1
  ([Newman 2003](https://arxiv.org/pdf/cond-mat/0303516); [Callaway et al.
  2000](https://arxiv.org/pdf/cond-mat/0007300)). **Concrete lever:** compute
  `federation_connectivity = |largest trust-reachable component| / N` directly
  from the existing Kuzu `TRUSTED` projection, surface it as a dashboard number,
  and alarm when it drops toward fragmentation. This turns an *already-built but
  inert* graph into the swarm's single resilience gauge.
- **Random vs targeted failure.** Scale-free topologies are robust to random
  drop-out but fragile to **hub removal**. If trust concentrates on one
  highly-trusted relay, that node's drift/lockdown fragments the swarm. **Lever:**
  measure the `TRUSTED` degree distribution; flag hub concentration (a
  single-point-of-trust-failure alarm).

### 2b. Capability clustering = stochastic block model on G2

Peers advertise `capabilities` (`server/identity_tool.py`). An SBM/community
view groups peers into capability-blocks, which answers "which cluster can serve
this sub-task" and enforces **redundancy** (don't route an entire capability into
one block). Useful once N is large enough for blocks to exist.

### 2c. Decomposition as a branching process on G1 (reframes the cost caps)

Sub-agent recursion is a **Galton–Watson branching process**: each task spawns a
random number of children with mean offspring μ. Expected total work ≈ Σ_d μ^d.
With μ > 1 and unbounded depth the tree **explodes** — which is precisely the
cost-runaway the fixed `max_depth=2` + the three cost caps
([ADR 0072](../adr/0072-cost-runaway-guards.md)) exist to prevent. The caps are a
*crude* branching-process control.

- **Principled version:** enforce **subcriticality** μ·p_continue < 1 (p_continue
  = probability a child itself spawns) as a *budget*, instead of a flat depth cap.
  This permits **deeper trees when each level is cheap** and **shallow trees when
  each level is expensive** — strictly better than a constant, while preserving
  the boundedness guarantee.
- **The one uncapped place:** parallel tool fan-out (`act.py:3195`) is
  `asyncio.gather` over *whatever the model emits* — unbounded width. A
  branching/value lens caps it: the marginal value of the w-th simultaneous probe
  has diminishing returns; stop widening when expected marginal value < marginal
  cost (or when the fan-out's tool-type entropy, §3d, says the extra calls are
  redundant).

### 2d. "Power of two choices" — the missing peer load balancer (top practical import)

The A2A map shows **no peer selection at all**. The classic result
([Mitzenmacher, "power of two choices"](https://www.numberanalytics.com/blog/ultimate-guide-network-resilience-random-graphs)):
when ≥ 2 peers satisfy a capability, sample **two at random** and route to the
better one (lower drift / lower load) — this yields an *exponential* improvement
in worst-case load over uniform-random, at near-zero cost, and avoids the herding
of "always pick the single best." **Concrete lever:** a `select_peer(capability)`
in/above `PeerAwareDispatcher` that (i) enumerates trust-eligible candidates via
`list_peer_chimeras()`, (ii) samples two, (iii) picks min over (drift_score,
circuit-breaker health). This replaces "the tool name hard-codes the peer" and is
the single highest-leverage, lowest-risk theoretical insertion because it fills a
genuine gap rather than tuning an existing knob.

---

## 3. Entropy optimization

### 3a. Maximum-entropy allocation (Jaynes) for PLAN / split

Under uncertainty about *which* sub-task is the bottleneck, MaxEnt says: don't
prematurely commit the whole budget to one branch — spread it as the
maximum-entropy distribution consistent with the known constraints (deadline,
cost cap, capability priors). Operationally this is a **Boltzmann/softmax
allocation** of the proposal/round budget over candidate sub-tasks with a
**temperature**: hot early (explore broadly), cooled as evidence accrues. It
generalises today's flat caps (≤ 3 proposals, ≤ 6 splits) into a budget that
*concentrates* when the agent is confident and *spreads* when it is not.

### 3b. Tier escalation = simulated annealing / temperature schedule

The tier ladder is already a thermal schedule in disguise: cheap, diverse,
cross-vendor haiku/sonnet rungs = **high temperature** (broad, cheap, noisy
exploration); opus = **low temperature** (precise, expensive exploitation). Today
escalation is purely *reactive* (failure memory → +1 rung). An annealing view
makes it principled and adds one concrete improvement:

- **Reheat on stuck = decorrelated restart.** When a signature keeps failing,
  jump to a **random different-vendor rung** rather than strictly the next one up.
  A deepseek→minimax switch decorrelates failure modes far more than
  deepseek→deepseek-bigger. The `SONNET_LADDER`'s deliberate cross-vendor spread
  (`providers/tiers.py:186`) already gestures at this; annealing names *why* and
  *when* to use it.

### 3c. Free-energy / active inference for the loop and the engines

The 8-phase loop already approximates active inference (ASSESS = belief update,
PLAN = policy selection, ACT = action, drift = surprise). FEP unifies
exploration and exploitation as one quantity — **expected free energy = pragmatic
value (finish the task) − epistemic value (information gain)** — and gives the
result that **low precision (confidence) ⇒ more random exploration**
([Orchestrator: Active Inference for Multi-Agent Systems, 2025](https://arxiv.org/pdf/2509.05651);
[FEP overview](https://arxiv.org/pdf/2207.06415)).

- The Discovery/Curiosity/Reflection engines are **epistemic-value generators**,
  currently scheduled by time-of-day + signal-density gates
  (`engines/*`, ADR 0089). An EFE view schedules them by **information gain**:
  fire curiosity when outcome entropy is high, suppress when low.
- "Low precision ⇒ explore" maps onto §3a: when escalation memory says a
  signature is *hot* (unpredictable), widen the proposal distribution; when the
  agent is confident, commit. This is a single coherent rule behind several
  currently-independent heuristics.

### 3d. Entropy as a named control/observability signal (cheapest wins)

Several Chimera signals already *are* entropies — naming them yields continuous
diagnostics where today there are only exact-match thresholds:

- **Tool-use entropy** H(tool distribution) per cycle. Low H = fixation
  (degenerate-loop *precursor*, earlier than the exact-repeat detector in
  `act.py`); high-but-unproductive H = thrashing. The dashboard already plots
  "tool fan-out"; add the entropy.
- **Proposal diversity** = cluster entropy over `dedup.py`'s cluster keys; a
  low-entropy proposal batch is redundant → regenerate.
- **Stagnation drift** is, formally, the **falling entropy of the
  KFM-transition / activity distribution** over time. The Shannon (or von
  Neumann) entropy of the ontology transition matrix is a principled stagnation
  metric for the existing composite drift score.
- **Federation self-uncertainty** = entropy over peer-belief labels
  (`a2a/peer_beliefs.py`).

---

## 4. Ranked, grounded recommendations

Each is tied to a file and would ship behind a flag + ADR, matching the
ADR 0165/0166 discipline (default-OFF, byte-identical until opted in).

| # | Insertion | Theory | Site | Value / effort / risk |
|---|---|---|---|---|
| 1 | **`select_peer()` via power-of-two-choices** | randomized load balancing | `a2a/peer_dispatch.py` (+ `list_peer_chimeras`) | High value, low effort, low risk — fills a real gap |
| 2 | **Federation connectivity / hub metric** | percolation, giant component | read Kuzu `TRUSTED` in `memory/graph.py` → dashboard | Pure observability; activates an inert graph |
| 3 | **Subcriticality fan-out budget** | branching process | `tools/subagent.py`, `act.py:3195` | Replaces flat caps; must stay *inside* ADR 0072 caps |
| 4 | **Decorrelated reheat-on-stuck** | simulated annealing | `core/escalation.py`, `providers/tiers.py` | Small, safe; better escape from correlated failures |
| 5 | **Entropy observability signals** | Shannon / von Neumann entropy | `act.py` guard, `dedup.py`, drift | Cheap, high diagnostic value |
| 6 | **Boltzmann proposal/split allocation** | maximum entropy | `proposals/generate.py`, `task_splitter.py` | Speculative; needs a value estimate; most invasive |

---

## 5. Honest caveats

- **These are modeling lenses first, algorithms second.** Most of the value is in
  (a) the *metrics* they license (connectivity, tool-use entropy, hub
  concentration) and (b) replacing magic constants with policies whose knob
  *means something* — not in importing a textbook algorithm wholesale.
- **Asymptotics vs N.** Percolation/SBM math is asymptotic; Chimera federations
  are often N = 1–2. So #2 is a "build the gauge now, it pays as the swarm grows"
  play, not an urgent fix. #1 (power-of-two) already helps at N ≥ 2.
- **The cost caps are scar tissue, and they work.** Any annealing/Boltzmann
  allocation (#3, #6) must sit *inside* the three existing cost caps
  ([ADR 0072](../adr/0072-cost-runaway-guards.md)/0076/0079), never replace them —
  stochastic allocation is exactly the failure mode they were built to stop.
- **Free energy is elegant but heavy.** The cheap 80% is §3d ("use entropy as a
  signal"); a full active-inference rebuild of the loop is not warranted.

---

## 6. One-line answer

The theory pays off in three concrete moves, in order: **(1)** add
power-of-two-choices peer selection (the federation has *no* load balancer);
**(2)** compute a percolation/giant-component connectivity gauge over the
already-materialised-but-inert Kuzu peer graph; and **(3)** name the entropies
Chimera already half-measures (tool-use, proposal, stagnation) so existing guards
get continuous signals. Branching-process subcriticality, decorrelated annealing
restarts, and max-entropy Boltzmann allocation are the deeper follow-ups — all
constrained to live inside the existing cost caps.
