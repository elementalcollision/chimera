# Escalation Postmortem

**Date:** 2026-05-20 | **Source:** `task_escalations` table in `state/chimera.db`
**Analysis:** Chimera (adversarial self-review)

---

## Executive summary

The `task_escalations` table contains exactly **2 rows** — neither signature appears
more than once. Zero signatures meet the ≥2-escalation threshold. This is itself a
healthy signal: the agent is not repeatedly failing on the same task type. Every
escalation so far is a first-time failure, suggesting either the tier assignment or
the task text was wrong from the start.

---

## Full table dump

| id | tier | finish_reason | rounds_used | cycle | created_at | signature_tokens | task_len |
|----|------|---------------|-------------|-------|------------|------------------|----------|
| 1  | haiku | max_rounds   | 22          | 15    | 2026-05-20 04:08 | ~285 tokens | 1952 ch |
| 2  | haiku | max_rounds   | 16          | 17    | 2026-05-20 04:38 | ~97 tokens  | 747 ch  |

Both failures: `haiku` tier, `max_rounds` finish reason. Both were large multi-step
tasks that exhausted their round budget without completing.

---

## Row-by-row analysis

### Escalation #1 — "Research and write the FOUR missing analytical sections…"

**Task text:** Sprawling 1952-character prompt asking for 4 distinct research sections
(capital as first-class node, feedback-loop dynamics, named antagonists, structural
omissions) — each requiring 1-3 citations, inline references, a reference list,
spawning of sub-agents, and writing into `mind/agonistic_futures_annotated.md`.

**Tier:** `haiku`

**Verdict: Task text is the primary failure mode.** Tier promotion alone would not fix this.

**Reasoning:**
1. **Scope mismatch.** Haiku's context window and reasoning depth are insufficient for
   research requiring 8-12+ cited claims across 4 orthogonal sections. The task expects
   web_search, http_fetch, sub-agent spawning, and file writing — all in a single
   `max_rounds=25` cycle. Haiku burns rounds on tool orchestration before reaching
   substantive research.
2. **The task is really 4 tasks disguised as 1.** Sections (1)-(4) don't share state,
   data, or intermediate results. They're parallel. A single agent must sequentially
   research each, hitting tool-round limits on section 2 or 3.
3. **Sub-agent spawning is an anti-pattern here.** The task says "spawn 1-2 sub-agents
   for adversarial review," but spawning from haiku spawns another haiku (or lower).
   The sub-agents don't improve citation quality — they just consume rounds.

**Proposed rewrite:** Split into 4 independent tasks, run in parallel:

> **Task A (section 1):** Research and write section "Capital as a first-class node".
> Find 3+ specific examples: hyperscaler capex figures, sovereign wealth fund
> datacentre investments, private equity in grid assets. Cite inline. Write under
> `## Missing sections (researched additions)` heading in
> `mind/agonistic_futures_annotated.md`. Append to `## References`.
>
> **Task B (section 2):** (same pattern, section 2 only)
> **Task C (section 3):** (same pattern, section 3 only)
> **Task D (section 4):** (same pattern, section 4 only)

Each task would fit in 8-12 rounds on `haiku`, or 4-6 on `sonnet`. Run them
concurrently via spawn_sub_agent or a cycle-injection mechanism.

---

### Escalation #2 — "Self-critical code review…"

**Task text:** 747-character prompt asking the agent to pick 2 modules from
`chimera/core/` or `chimera/memory/`, read their source via shell, compute
structural metrics via code_exec, and write a detailed review to
`mind/overnight/code-review-<module>.md`.

**Tier:** `haiku`

**Verdict: Task text is adequate; tier was too low.** Sonnet would have
finished this in 10-12 rounds.

**Reasoning:**
1. **Haiku's weakness is nuanced qualitative judgment.** The task requires the agent
   to evaluate design choices (strongest/weakest), identify bugs it "suspects but has
   not confirmed," and propose refactors. Haiku tends to produce shallow commentary
   on obvious patterns (e.g., "no error handling" is every haiku review's go-to gripe).
2. **The file-reading overhead isn't the bottleneck.** Shell + cat for two modules
   takes ~2 rounds. The metrics computation is a 5-line code_exec. The real cost is
   the deliberation — and haiku deliberates by generating more text, not better text.
3. **However**, the task text has one structural flaw: it doesn't *name* the modules.
   It says "Pick TWO modules from chimera/core/ or chimera/memory/" — forcing the
   agent to spend rounds discovering what's available before it can review. This was
   a meaningful contributor to the round exhaustion.

**Proposed rewrite (light edit):**

> **Self-critical code review.** Review the following two modules:
> `chimera/memory/audit.py` and `chimera/memory/entities.py`.
> For each, write `mind/overnight/code-review-<module>.md` with:
> (a) what the module does in one paragraph;
> (b) the strongest design choice and why the agent agrees with it;
> (c) the weakest design choice and a concrete alternative;
> (d) one bug or footgun the agent suspects but has not confirmed;
> (e) a single proposed refactor sized small enough to fit one ADR.
> Use `shell` to `cat` the files, `code_exec` to compute structural metrics
> (count of branches, function sizes). DO NOT edit the source.
> Run on **sonnet** tier. Time budget: 14 rounds.

Named modules + sonnet tier = one-and-done in a single escalation-free cycle.

---

## Systematic patterns

Two (admittedly small-sample) patterns emerge:

1. **Multi-section tasks on haiku always hit max_rounds.** The overhead of
   tool-switching between sections means the agent never finishes all sections
   before the budget expires. Remediation: split into parallel sub-tasks, or
   raise tier to sonnet+ with higher round budget.

2. **Ambiguous selection tasks waste rounds on discovery.** Task #2's "Pick TWO
   modules" forces the agent to explore the filesystem, decide, backtrack, and
   then start the real work. Any task that requires an initial discovery/decision
   step should either (a) name the targets explicitly, or (b) budget +3 rounds
   for exploration and document this in the task text.

---

## Recommendations

1. **Create a task splitter.** Before injecting a multi-section task into the
   cycle, have a tier-enabled router (even a small sonnet call) that splits the
   task into independent sub-tasks and assigns each its own round budget. The
   parent collects & merges outputs.

2. **Name targets explicitly in code-review tasks.** If the task is "review X and Y,"
   say "review `chimera/memory/audit.py` and `chimera/core/kfm.py`" — not "pick two."

3. **Don't send research tasks to haiku.** Research requires web_search +
   http_fetch + citation weaving + file writing — that's 4+ tool types. Haiku
   struggles to sequence them without exhausting rounds. Floor for research:
   `sonnet` with min_rounds=12.

4. **Monitor the escalation log after each change.** With only 2 rows, any new
   escalation will double the dataset. Set a trigger: if any signature hits ≥2
   escalations, escalate *that signature* to a human with the full task text and
   this postmortem format.
