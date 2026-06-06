# Evaluating vLLM Semantic Router for Chimera tool chains

**Status:** Evaluation / Phase-0-style gate note — no code change proposed yet.
**Date:** 2026-06-06
**Question:** Can we incorporate semantic routing (à la
[vllm-project/semantic-router](https://github.com/vllm-project/semantic-router))
into Chimera's core to improve tool chains?
**Verdict:** **Yes — selectively. Adopt the *pattern* (signal-driven
routing + tool pre-filtering), not the *runtime* (Go / Envoy ExtProc).**
Sequence it behind the embedding-model decision already parked in
[ADR 0134](../adr/0134-hybrid-search-eval.md). This mirrors how Chimera
treats Hermes/OpenClaw: re-implement the idea, don't depend on the project.

---

## 1. What vLLM Semantic Router actually is

A **network-layer inference gateway**, not an agent framework.

| Dimension | Semantic Router |
|---|---|
| Form factor | Go service running as an **Envoy `ext_proc`** filter |
| Position | Sits **between clients and OpenAI-compatible model backends** (vLLM-served) |
| Core job | Classify each request → pick the best **backend model** + reasoning mode |
| Classifier | **ModernBERT / BERT-family** CPU finetunes; MMLU-style 57-category domain taxonomy; LoRA classifiers |
| Extra signals | PII detection, jailbreak / prompt-guard, **semantic cache** (embedding-similarity threshold) |
| Decision pipeline | Signal Extraction → Decision Evaluation → Plugin Execution → Model Selection |
| Goal | Mixture-of-Models: ~10% higher accuracy, ~50% lower latency, ~50% fewer tokens in their trials |

Sources: project README, the
[vLLM blog](https://blog.vllm.ai/2025/09/11/semantic-router.html), and the
architecture docs. Crucially, the blog calls out **tool-catalog bloat** as a
first-class problem: *"Adding more tools or longer tool outputs can
drastically reduce accuracy. The router must pre-filter tools and keep
catalogs tight."* That sentence is the single most relevant idea for
Chimera's tool chains.

### Why we cannot adopt it wholesale

- It is **Go + Envoy ExtProc**, designed to front **self-hosted, OpenAI-
  compatible** model serving. Chimera is a **thin Python in-process agent**
  calling **Anthropic + OpenRouter SaaS** APIs (`chimera/providers/`).
- There is **no Envoy, no proxy chokepoint, no self-served model** in
  Chimera's deployment ([ADR 0064](../adr/0064-container-bootstrap.md)).
  An ExtProc sidecar has nothing to intercept.
- Bolting on a Go service + Envoy contradicts the MVP dependency discipline
  (`best-of-breed.md` §Dependencies: "re-implement, not depend") and the
  "thin Python core" charter in the README.

**Conclusion:** the *runtime* is a deployment-model mismatch. The *pattern*
— a cheap classifier that emits routing signals at a single chokepoint — is
a clean fit.

---

## 2. What Chimera already does that *is* routing

Chimera makes four routing-shaped decisions today. None of them are
semantic; all are lexical / static.

| # | Decision | Where | Mechanism today | Semantic? |
|---|---|---|---|---|
| 1 | **Starting tier** (haiku/sonnet/opus) | `core/escalation.py::recommended_tier` | Token-bag **Jaccard overlap** vs `task_escalations` history + a hardcoded **keyword list** (`research_task_floor_tier`) | ❌ lexical |
| 2 | **Rung within a tier** | `providers/tiers.py::select_rung` / `eligible_rungs` | Cheapest-first walk; escalate on provider error | ❌ static |
| 3 | **Tool exposure to the model** | `core/act.py:2467` → `registry.schemas()` | Returns **every available tool schema, every ACT round** | ❌ none |
| 4 | **Tool dispatch admission** | `tools/dispatch.py::check_policy` | OpenClaw-style deny/allow/availability/`requires_env` | ❌ static rules |

Two observations:

- **Decision 1 is the direct analog of semantic-router's core.** It already
  reaches for "is this task hard enough to need a stronger model?" — but it
  answers with token-bag Jaccard (`_signature()` drops <4-char tokens,
  sorts, comma-joins) and a frozen keyword set. Paraphrases miss:
  *"survey the literature and cite sources"* does not contain any
  `_RESEARCH_TASK_KEYWORDS` token, so it floors at haiku even though it is
  research-shaped.
- **Decision 3 is the tool-catalog-bloat problem, verbatim.** `act.py`
  hands the model the full registry every round (core tools + every
  operator-approved skill under `chimera/tools/dynamic/`). As that dynamic
  set grows, the blog's warning bites: a fat tool catalog degrades
  tool-call accuracy and wastes input tokens on every round of every chain.

### Existing semantic infrastructure: a scaffold, not a runtime

`chimera/memory/hybrid_search.py` is **BM25-only today**. The vector half is
an explicit **stub** (`vector_search()` returns `[]`), and the embedding-
model choice — *which model, which dim, which storage (sqlite-vec vs
LanceDB)* — is **deferred to ADR 0134 §"Deferred to #6.b"**. The
`f2-deadlock-rootcause-ollama-embed` postmortem records that an earlier
Ollama-embedding attempt deadlocked. So:

> **Chimera has no production embedding capability, and has deliberately
> parked the decision that semantic routing depends on.**

This is the gating constraint for the whole evaluation (see §5).

---

## 3. Where semantic routing maps onto "tool chains"

"Tool chains" = the multi-round tool-call sequence the agent runs in the
**ACT** phase (`core/act.py`, parallel dispatch per
[ADR 0040](../adr/0040-parallel-tool-dispatch.md)). Four candidate insertion
points, ranked by value-for-effort:

### 3.1 Tool pre-filtering / catalog pruning — **highest value, most "tool-chain"**

Replace the unconditional `registry.schemas()` (act.py:2467) with a
**task-scoped subset**: classify the task → expose only the relevant
toolset(s). This is exactly semantic-router's tool-bloat mitigation.

- **Benefit:** higher tool-call accuracy, fewer input tokens per round
  (compounds across a chain), fewer degenerate-loop aborts from the model
  fixating on an irrelevant tool.
- **Cheap first cut needs no embeddings:** the registry already carries a
  `toolset` label per entry and `schemas(toolset=...)` already filters by
  it. A lexical/keyword classifier (task → toolset set) is a zero-dependency
  v0; an embedding classifier is a strict upgrade later.
- **Clean seam:** one call site. Feature-flaggable.

### 3.2 Semantic tier routing — **direct analog, second priority**

Augment `recommended_tier()` with an embedding/intent classifier that maps
task text → {complexity, domain} → tier, instead of Jaccard + frozen
keywords.

- **Benefit:** paraphrase-robust complexity routing; retires the brittle
  `_RESEARCH_TASK_KEYWORDS` list; can prefer `reasoning_optimized` rungs
  (already declared in `ModelCapabilities`) for reasoning-shaped tasks —
  the same "fast path vs Chain-of-Thought" split the blog centres on.
- **Risk is already mitigated:** a misroute to a too-cheap tier is caught
  next cycle by `task_escalations` memory, which promotes the tier. Semantic
  routing makes the *first* attempt smarter; escalation memory remains the
  safety net.
- **Free training labels:** Chimera already logs `task_escalations`
  (task_text → tier that failed) and `ladder_outcomes` (task → rung →
  outcome). That is precisely the labelled corpus a router learns from — we
  would not be cold-starting.

### 3.3 Semantic cache — **rides on ADR 0134, defer**

An embedding-similarity cache over prior `task → result` (the blog's
semantic cache). This is literally the deferred vector half of
`hybrid_search.py`. Worth doing **as part of** ADR 0134 #6.b, not as a
separate effort.

### 3.4 Safety signals (PII / jailbreak) — **out of scope for tool chains**

Semantic-router ships prompt-guard + PII detection. Chimera has neither, but
they do not "improve tool chains" and they pull in the heaviest classifier
weights. Explicitly **defer / reject** for this initiative.

---

## 4. Architectural fit summary

| Semantic-router feature | Adopt? | Chimera home | Notes |
|---|---|---|---|
| Tool pre-filtering | ✅ **adopt (pattern)** | `act.py` tool-exposure seam + `registry.schemas(toolset=)` | Cheap lexical v0; embedding upgrade later |
| Category → model routing | ✅ adopt (pattern) | `escalation.recommended_tier` | Augment, keep escalation memory as net |
| Reasoning-mode selection | ◑ folds into tier routing | `ModelCapabilities.reasoning_optimized` already exists | No new surface |
| Semantic cache | ⏸ defer | `memory/hybrid_search.py` (#6.b) | Ride ADR 0134 |
| PII / jailbreak guard | ❌ reject (for now) | — | Not tool-chain-relevant; heavy weights |
| Envoy ExtProc runtime (Go) | ❌ reject | — | No proxy chokepoint; deployment mismatch |
| ModernBERT/LoRA local serving | ❌ reject | — | torch dependency vs thin core; Ollama-embed already deadlocked |

---

## 5. The gating constraint and recommended sequence

Everything of value here that uses **embeddings** is blocked on the **same
unresolved decision** Chimera already owns: ADR 0134 #6.b — *which embedding
model, which dimensionality, which storage*. Semantic routing should
**ride that decision, not leapfrog it.** Spinning up a parallel embedding
stack just for routing would fragment the very choice ADR 0134 exists to
make once.

**Recommended sequence (each its own ADR + `CHIMERA_*` feature flag, per
repo discipline):**

1. **Now, no embeddings required — tool pre-filtering v0 (lexical).**
   Scope the tool catalog per task at the `act.py` exposure seam using the
   existing `toolset` labels and a keyword/heuristic classifier. Captures
   most of the "improve tool chains" win, ships under the thin-core
   constraint, and lays the seam an embedding classifier later slots into.
   This is the recommended first slice.

2. **With ADR 0134 #6.b resolved — embedding-backed routing.**
   - Upgrade the §3.1 tool classifier from lexical to embedding similarity.
   - Add §3.2 semantic tier routing inside `recommended_tier()`, trained on
     the `task_escalations` / `ladder_outcomes` rows we already store.
   - Fold in §3.3 semantic cache as part of #6.b itself.

3. **Never (for this initiative):** Envoy/Go ExtProc, local ModernBERT
   serving, PII/jailbreak guards.

### Risks / watch-items

- **Misclassification → wrong tier or missing tool.** Mitigations: keep
  `task_escalations` promotion as the net (tier); always include a small
  "core" toolset floor (shell/code_exec) so pre-filtering can never strand
  the agent without a way to act.
- **Dependency creep.** Hold the line: no torch, no new vector store outside
  ADR 0134's chosen one (sqlite-vec is the standing recommendation).
- **Cost.** Tier/tool routing runs once per task, not per round; an embedding
  call there is negligible against the three cost caps. A *per-round* call
  would not be — keep routing at task granularity.

---

## 6. One-line answer

Yes: re-implement semantic-router's **signal-driven routing + tool pre-
filtering** pattern at Chimera's two existing chokepoints
(`recommended_tier` and the `act.py` tool-exposure seam), starting with a
zero-dependency lexical tool-pruner and upgrading to embeddings once
ADR 0134 #6.b picks the model. Reject the Go/Envoy runtime, local BERT
serving, and the safety guards — they are a deployment and scope mismatch
for a thin Python agent.
