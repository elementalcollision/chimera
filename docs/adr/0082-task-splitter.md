# ADR 0082 — Task splitter (v4.63)

**Status:** Accepted (2026-05-20)

## Context

The 2026-05-19 escalation postmortem
(`mind/overnight/escalation-postmortem.md`) identified two recurring
anti-patterns in INBOX task text:

1. **"Research and write FOUR sections, each with citations …"** —
   bundles 4 parallel research tasks into one cycle. Haiku burns
   rounds on tool sequencing before reaching substantive work.
2. **"Dashboard honesty audit. For each widget … spawn a sub-agent
   on claude-3.5-sonnet … compile the answers."** — implicit fanout
   that detonated the 2026-05-19 cost burn (5+ cycles, $229 on
   opus).

[ADR 0075](./0075-task-conventions-and-tier-floor.md) (research-task
tier floor) fixed the *tier* mistake. ADRs 0072/0076/0079 added cost
caps that stop the runaway. None of those fixed the *shape*: a
single INBOX item that bundles parallel work will keep failing
until someone splits it.

The postmortem's recommendation:

> Create a task splitter. Before injecting a multi-section task
> into the cycle, have a tier-enabled router (even a small sonnet
> call) that splits the task into independent sub-tasks and assigns
> each its own round budget. The parent collects & merges outputs.

This ADR ships the splitter as an OPT-IN operator surface. Loop
auto-integration into ASSESS is deferred until the heuristic is
validated against more cases — the v4.46 escalation memory and
ADR 0073 hot-signature alarm together provide enough feedback to
tune before promoting to default-on.

## Decision

### 1. `chimera/core/task_splitter.py` — heuristic + provider call

Two layers:

**Pure heuristic** `is_splittable_shape(task_text) -> SplitSignal`:

Patterns and weights:

| Signal | Weight | Example |
|---|---|---|
| `(1)…(2)…` numbered sections | 0.5 (strong) | "Do (1) X, (2) Y" |
| Explicit multi-section phrasing | 0.5 (strong) | "the four sections" |
| Spawn N≥3 sub-agents | 0.5 (strong) | "spawn 14 sub-agents" |
| For-each + spawn (implicit fanout) | 0.5 (strong) | "for each widget … spawn a sub-agent" |
| Spawn 2 sub-agents | 0.3 (medium) | "spawn 2 sub-agents" |
| Multi-step deliverable phrases (≥2) | 0.3 (medium) | "and write, then compile" |
| ≥3 declared artifacts | 0.4 (medium) | 3 backtick paths |
| 2 declared artifacts | 0.1 (soft) | 2 backtick paths |
| `for each X` (alone) | 0.2 (soft) | "for each entity" |
| Long task text (≥1500 chars) | 0.1 (soft) | … |

Threshold: 0.5. Each strong signal alone trips. Soft signals only
contribute in combination. Weights tuned against the two canonical
postmortem cases (dashboard audit = 0.7, 4-section research = 0.9+).

**Provider-driven splitter** `split_task(task_text, *, provider, model_id)`:

System prompt instructs a sonnet-tier model to return JSON:

```json
{"split": true, "subtasks": ["...", "...", "..."]}
```

or

```json
{"split": false, "reason": "single coherent task"}
```

Rules in the prompt:
- Each sub-task self-contained (no shared state)
- < 800 chars per sub-task
- Each sub-task names its own declared artifact path
- Preserve original CONSTRAINTS (citation rules, tier hints, sub-agent
  models if specified)
- 2–6 sub-tasks preferred

`parse_splitter_response()` is defensive — accepts raw JSON, markdown
code-fenced JSON, JSON embedded in prose. Returns `[]` on
unparseable output, on `split: false`, or on non-list `subtasks`.

Provider failure → `[]`. The caller (CLI or future ASSESS hook)
decides what to do on empty result; typically "keep the task as
one and let escalation memory handle it."

### 2. `chimera split` CLI verb

```bash
chimera split "<task text>"                  # heuristic + model call
chimera split "<task text>" --no-model       # heuristic only
chimera split "<task text>" --json           # structured output
```

Operator workflow:
1. See a task you suspect is too bundled.
2. `chimera split "<task text>"` shows heuristic confidence + reasons
   and, if a sonnet-tier provider is available, the model's proposed
   split.
3. Operator decides whether the split makes sense.
4. Operator manually edits `mind/INBOX.md` — marks the original task
   `[-]` and appends the sub-tasks as new `[ ]` lines.

The verb does NOT auto-rewrite INBOX. That's a non-goal for v4.63
(see below).

### 3. Cost note

A sonnet-tier splitter call (deepseek-v4-pro post-ADR-0072) is
~2K input + ~1K output ≈ $0.003. The per-task budget (ADR 0079,
default $5) absorbs this rounded-down to zero. Operators using the
verb interactively pay similarly cheap rates.

## Tests

`tests/test_task_splitter.py` — 21 tests:

- Heuristic: empty, one-step (not splittable), numbered-sections,
  explicit multi-section, spawn N, for-each alone (not enough),
  multi-artifact, overnight-burn task detected, 4-section research
  detected
- Prompt builder includes task text and delimiters
- Response parser: raw JSON true/false; markdown-fenced; empty
  subtask stripping; malformed → empty; bare array → empty;
  non-list subtasks → empty
- `split_task` async with stub provider: returns subtasks; respects
  max_subtasks; provider failure → empty; empty text doesn't call
  provider

Full suite after v4.63: 683 passing (was 662, +21 new).

## Non-goals

- **No auto-rewrite of INBOX.** The splitter PROPOSES; the operator
  applies. Manipulating operator-owned files without consent is a
  bigger trust step than a heuristic is worth. A future ADR can
  route splits through the mutation queue.
- **No ASSESS-phase auto-invocation.** Calling the splitter every
  cycle for every task adds cost (~$0.003/task) and latency. We
  call it ONLY when the operator invokes the verb. A future ADR
  can promote to ASSESS-phase auto-invocation, gated by
  `CHIMERA_TASK_SPLITTER_ENABLED=1`, after the heuristic is
  validated against more cases.
- **No re-splitting of already-split tasks.** Sub-tasks emitted by
  the splitter are presumed to be atomic. Detecting "this looks
  like a sub-task from a prior split" is hard and unnecessary —
  if a sub-task is still too big, the operator runs `chimera split`
  on it again.
- **No model fallback chain.** If the configured sonnet rung's
  provider isn't available (no API key), the splitter returns `[]`
  — the heuristic confidence + reasons are still printed. No
  silent retries on cheaper rungs; the splitter call needs the
  reasoning depth.

## Why this shape

Why heuristic *plus* model call, instead of just model? Because the
heuristic is free and decides whether a model call is even worth
making. ~95% of INBOX tasks are simple and the heuristic correctly
says "keep as one" — zero token spend on those.

Why threshold 0.5 with strong signals at 0.5 each? Because each
strong signal alone is sufficient evidence (numbered sections,
explicit multi-section phrasing, ≥3 sub-agents, implicit fanout).
A soft signal alone shouldn't be enough — the false-positive cost
(unnecessary model call) is small but real. The threshold ensures
strong-OR-multiple-medium triggers.

Why preserve original CONSTRAINTS in the prompt? Because the
postmortem found research tasks that specify a citation regime
("(Author, Year)") or sub-agent models ("on claude-opus-4-7"). A
split that drops those constraints turns a precise task into a
vague one. The system prompt is explicit about preservation.

Why operator-applied instead of auto-rewrite? Because v4.46's
escalation memory and v4.54's hot-signature alarm already give the
operator the signal "this task keeps failing" — adding "and here's
how to split it" is the missing piece, but it's still advice. The
agent gives the suggestion; the operator decides. A future ADR can
promote auto-rewrite once the heuristic earns trust.
