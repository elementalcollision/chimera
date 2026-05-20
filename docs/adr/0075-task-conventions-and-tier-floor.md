# ADR 0075 — Task conventions + research-tier floor (v4.56)

**Status:** Accepted (2026-05-20)

## Context

The 2026-05-19 escalation postmortem
(`mind/overnight/escalation-postmortem.md`) identified two task-shape
anti-patterns that consistently burn rounds:

1. **Multi-section research on haiku.** The 1952-character task
   *"Research and write the FOUR missing analytical sections… each
   with 1-3 citations… spawn 1-2 sub-agents"* burnt 22 rounds without
   completing. From the postmortem:

   > Haiku burns rounds on tool orchestration before reaching
   > substantive research. […] The task is really 4 tasks disguised
   > as 1. Sections (1)-(4) don't share state, data, or intermediate
   > results. They're parallel.

2. **Ambiguous "pick two" selection.** The 747-character
   self-critical code-review task said *"Pick TWO modules from
   chimera/core/ or chimera/memory/"*. The postmortem:

   > The task text has one structural flaw: it doesn't *name* the
   > modules. […] forcing the agent to spend rounds discovering what's
   > available before it can review.

Both surfaced as `haiku × max_rounds` failures. v4.46 escalation
memory promoted them to sonnet on the next cycle, which was the
right behaviour after the fact — but it cost a haiku cycle of
round-budget thrash first. The structural fix is preventing the
wrong tier from being attempted in the first place when the task
shape makes the failure inevitable.

## Decision

### 1. Research-task tier floor in `recommended_tier()`

`chimera/core/escalation.py`:

```python
_RESEARCH_TASK_KEYWORDS: tuple[str, ...] = (
    "peer-reviewed", "peer reviewed", "cite inline", "citation",
    "research and write", "research and synthesize",
    "research and synthesise", "academic literature", "named journalism",
)

def research_task_floor_tier(task_text: str) -> str | None:
    if not task_text:
        return None
    lower = task_text.lower()
    for kw in _RESEARCH_TASK_KEYWORDS:
        if kw in lower:
            return "sonnet"
    return None
```

Applied in `recommended_tier()` BEFORE consulting escalation memory:

- If the task text matches the heuristic, the effective floor
  becomes `sonnet` regardless of `default_tier`.
- Memory-driven promotion still applies on top: a prior `sonnet`
  failure on a research task → promote to `opus`.
- The floor only lifts; it never demotes a caller who explicitly
  requested `opus`.

### 2. Task convention doc updates

- `AGENTS.md` §"Naming & conventions" gains a "Task-text shape
  conventions" subsection: code-review tasks must name modules;
  research-shaped tasks auto-floor at sonnet; multi-section tasks
  should split.
- `docs/runbook.md` gains a "Writing tasks for the agent" section
  with the same conventions in operator-facing language.

These conventions exist so the operator writes tasks that the
agent's tier ladder can actually execute. They are advisory for
humans and enforced (where possible) by the floor heuristic for the
agent.

## Tests

`tests/test_research_tier_floor.py` — 10 new tests:

- Parametrized keyword matches → `sonnet`
- Parametrized non-research text → `None`
- Empty memory + research + `default_tier="haiku"` → `sonnet`
- `default_tier="opus"` not demoted by floor
- Non-research text + `default_tier="haiku"` → `haiku`
- Research + prior sonnet failure → `opus` (memory + floor compose)
- Research + prior haiku failure → `sonnet` (memory agrees with floor)

Full suite after v4.56: 605 passing (was 595 at v4.55, +10 new).

## Non-goals

- **Not building a task splitter.** The postmortem recommended a
  small sonnet pre-cycle that splits multi-section tasks into
  independent sub-tasks. That's [A14] in the Tier 2 backlog,
  punted to v4.57+ — it's a new module with its own design
  decisions (when to split, who collects, how to merge). The
  research-floor heuristic addresses the *tier* mistake; the
  splitter addresses the *shape* mistake separately.
- **Not enforcing "name the modules" at the inbox parser.** The
  convention is documented in AGENTS.md and the runbook; humans
  writing tasks should follow it. Building an inbox-time linter
  is more friction than the failure case warrants — `chimera
  escalations summary` already surfaces signatures that keep
  failing, which is the right feedback loop for "this task text
  is broken."
- **Not extending the keyword set yet.** Five keyword families
  cover the postmortem's failure cases. We'll add more if and
  when hot signatures with non-matching but research-shaped text
  appear in the summary.

## Why this shape

Why a keyword heuristic instead of a tier-router LLM call? Because
the heuristic is free, deterministic, and unit-testable. A router
call would burn its own tokens on every task and add an extra
network hop to the assess→plan boundary. If the heuristic misses,
the escalation memory still catches the failure on the next cycle
— the floor is a "make the first attempt cheaper" optimisation, not
a hard gate.

Why floor at sonnet and not opus? Because deepseek-v4-pro (the
new opus-tier default per ADR 0072) is barely more expensive than
deepseek-v4-flash at the sonnet tier — but sonnet has the actual
reasoning depth required for citation weaving without paying for
opus-tier overhead. The escalation memory can still promote to
opus on a documented sonnet failure; the floor doesn't pre-empt
that.

Why apply the floor BEFORE memory? Because the alternative ("after
memory") creates a corner case: if `default_tier="haiku"` and
memory says "promote to sonnet because of a prior failure," that's
indistinguishable from "no prior failure but research floor lifts
to sonnet" — but the right next-promotion step differs
(failure-driven → opus; floor → sonnet again). Applying the floor
first by mutating `default_tier` makes the memory walk see the
correct baseline and produce the right promotion either way.
