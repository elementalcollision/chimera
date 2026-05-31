# Full autonomous loop, live: Chimera self-charters, builds, and delivers `durparse`

**Date**: 2026-05-31
**Goal (the only human input)**: "parse a duration string like 1h30m45s into total seconds"
**Result**: **complete originate → verify → materialize → build → deliver, live,
on a self-authored goal.** Chimera decided what to build, wrote a discriminating
test, verified the test (teeth 0.93), built a correct module from scratch against
it, and self-delivered it — `[agent] de8c144 build chimera/durparse.py`, 14/14
tests green, total spend ~$0.07, ~11 minutes.

## The loop, end to end

1. **Originate** (`chimera charter`, ADR 0153) — from the one-line goal, the
   model (sonnet) authored a `CharterBundle`: module `durparse`, target
   `chimera/durparse.py`, a design note, an acceptance test, and a reference impl.
2. **Verify** (teeth gate, ADR 0152) — the self-written test killed 0.93 of the
   single-point mutants of the reference impl → accepted (≥ 0.8). A weak test
   would have been rejected here, before any build.
3. **Materialize** (ADR 0154) — wrote `tests/test_durparse.py` (imports rewritten
   to `chimera.durparse`) + a scope-check-parseable design note; reference impl
   stripped. Committed to branch `build/durparse-live` (`1ebeacc`); the test was
   confirmed RED (module absent).
4. **Build** (`charter_build_soak.sh`, ADR 0155) — a worktree off the build
   branch; phase 1 (engines off) had the agent build `chimera/durparse.py` from
   scratch against the test until green. Nothing human-written in the loop except
   the goal.
5. **Deliver** (ADR 0148) — phase 2 committed: `de8c144 [agent] build
   chimera/durparse.py`; post-build gate **14 passed**.

## What it built (verbatim)

```python
import re

def parse_duration(s: str) -> int:
    """Parse a duration string like '1h30m45s' and return total seconds."""
    s = s.strip()
    if not s:
        return 0
    matches = re.findall(r'\d+[hms]', s)
    reconstructed = ''.join(matches)
    original_no_space = re.sub(r'\s+', '', s)
    if reconstructed != original_no_space:
        raise ValueError(f"Invalid duration format: {s!r}")
    total = 0
    for token in matches:
        value = int(token[:-1]); suffix = token[-1]
        total += value * (3600 if suffix == 'h' else 60 if suffix == 'm' else 1)
    return total
```

Genuinely correct and defensive: it reconstructs the matched tokens and raises
`ValueError` when they do not account for the whole input — i.e. it rejects
malformed strings rather than silently dropping garbage. The agent built this
against a test *it authored*, including the order-independence and
invalid-input cases the charter's test pinned.

## What this validates — and the honest boundary

**Validated:** the entire pipeline fires live and end-to-end. Chimera moved from
*executing* a human-written charter (the v46 arc) to *originating* the charter,
*verifying* it is trustworthy, *building* it, and *delivering* it — autonomously,
from one sentence.

**Honest boundary — the commit was harness-executed.** The build ran with
`CHIMERA_SOAK_AUTOCOMMIT=1` (the ADR 0148 fallback, default on for charter
builds). The agent authored + greened `durparse.py`; the *runner* executed the
`git commit` (the log shows `harness-autocommit: committed` on the first phase-2
iteration). So: BUILD is fully autonomous; COMMIT is harness-supplied. A pure
agent self-commit on this loop would set `CHIMERA_SOAK_AUTOCOMMIT=0` and rely on
the `git_commit` tool (validated separately in the v46 re-soak #4, where the
agent self-committed via that tool). The two have not yet been combined in one
run.

**Other honest notes:** one easy, well-bounded goal; teeth 0.93 (not 1.0 — a few
equivalent/uncaught mutants survived, acceptable at this fidelity); phase 1
exited `no_forward_progress` *after* the build landed (the postmortem sentinel,
as in prior soaks — the module was built and the test green regardless).

## Artifacts

- Build commit `de8c144` on branch `chimera-soak/charter-durparse-2026-05-31-1740`
  (preserved; not on main).
- Materialized charter on `build/durparse-live` (`1ebeacc`).
- Run log: `state/charter_build_charter-durparse-2026-05-31-1740.log`.

`chimera/durparse.py` is a real, working, 14-test-covered module — the first
thing Chimera both *decided to build* and *built*. It can be landed to main as
the inaugural self-chartered deliverable (operator's choice).

## Next

- **Combine self-commit + self-charter**: rerun with `CHIMERA_SOAK_AUTOCOMMIT=0`
  so the agent self-commits via `git_commit` — a fully agent-driven loop with no
  harness commit.
- Harder / more ambiguous goals (where the charter may need critique-and-revise,
  or the teeth gate should reject).
- Land `durparse` to main (the first autonomously self-chartered module).
