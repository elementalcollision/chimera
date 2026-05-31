# First LIVE self-charter run — originate → verify → materialize, end-to-end

**Date**: 2026-05-31
**Command**: `chimera charter "parse a duration string like 1h30m45s into total seconds" --tier sonnet`
**Model**: anthropic sonnet (live; keys from `.env`)
**Verdict**: the originate → verify → materialize half of the loop works
end-to-end against a live model, first try. Chimera decided what to build, wrote
a **discriminating** acceptance test, the teeth gate confirmed it (**1.00**), and
it materialized correct, scope-check-parseable build-soak inputs.

## What happened

One CLI command ran the full S1+S2 pipeline live:

1. **Self-charter** (ADR 0153) — the model authored a `CharterBundle`: module
   `durparse`, target `chimera/durparse.py`, a design note, an acceptance test,
   and a reference implementation.
2. **Teeth gate** (ADR 0152) — `verify_test_teeth` ran the self-written test
   against single-point mutants of the reference impl: **teeth 1.00** (every
   mutant killed). The self-authored test is trustworthy.
3. **Materialize** (ADR 0154) — wrote `tests/test_durparse.py` (imports rewritten
   to `chimera.durparse`) + a design note whose `READY-FOR-REMEDIATION` allowlist
   is `chimera/durparse.py`. The reference impl was stripped.

## The test it wrote (verbatim, abridged)

```python
import chimera.durparse as durparse

def test_parse_duration_basic():
    assert durparse.parse_duration("1h30m45s") == 5445

def test_parse_duration_order_independence():
    # A wrongly ordered split on 'h' then 'm' then 's' would fail here
    assert durparse.parse_duration("30m1h") == 5400
    assert durparse.parse_duration("45s30m1h") == 5445

def test_parse_duration_strips_whitespace():
    assert durparse.parse_duration(" 1h30m ") == 5400
```

The notable line is the agent's own comment on `order_independence`: it
deliberately wrote a case that **catches a naive positional implementation**.
That is precisely the discriminating behaviour the teeth gate rewards — and it
emerged from the model unprompted. Six test functions across basic, single-unit,
omitted-unit, zero, order-independence, and whitespace cases.

## Why this matters

This is the first time Chimera **originated** a buildable, *verified-trustworthy*
spec against a live model — not executed a human-written one. The full pipeline
(generate → teeth-gate → materialize) fired correctly:

- the import rewrite produced a test that imports the real dotted path;
- the design note's allowlist is parsed by the real ADR 0146 scope check;
- the teeth score (1.00) means a vacuous or weak self-written test would have
  been rejected *before* any build — the safety property holds in practice.

## Honest scope — what is NOT yet demonstrated

- **The build half.** Materialization stops at the soak inputs. Actually
  *building* `durparse` against the self-written test (the v46 self-commit loop)
  needs a GENERIC charter-build runner — the existing `long_cycle_soak_v46.sh`
  is hard-wired to `soak_report`. That runner is the clear next chip; until it
  exists the loop is originate → verify → materialize, not yet → build → deliver.
- **One run, one easy goal.** A duration parser is a clean, well-bounded target;
  harder/ambiguous goals will stress the charterer (and may surface weak charters
  the teeth gate should reject — itself a useful test).
- **No artifacts committed.** The materialized test imports a module that does
  not exist on main; committing it would red CI. The run wrote to a temp dir
  (cleaned up); this note is the record.

## Next

- **Generic charter-build runner**: a soak harness that takes the materialized
  artifacts (test + design + target path) and runs the v46 two-phase build →
  self-commit. This closes the loop to → build → deliver and lets us launch a
  real build on `durparse` (or any self-charter).
- Then: a true end-to-end live run (charter → build → self-commit) on `durparse`.
- Follow-ups: critique-and-revise on weak charters; harder/ambiguous goals.
