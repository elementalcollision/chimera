# ADR 0098 — Ping-Pong Loop Detection

**Status:** Accepted
**Date:** 2026-05-22
**Release:** v4.87.0
**Provenance:** Agent-authored during soak v6 — first-ever
  `chimera/` source edit produced by a Chimera soak. Cherry-picked
  from `chimera-soak/v6-2026-05-22-0329` commit `aeb8a56` with an
  operator-written test suite added on top.

## Context

`chimera/tools/loop_guard.py` ships `detect_degenerate_loop`, which
catches **identical-args repeats** — the same tool name + same args
appearing N times consecutively. This is the right detector for the
classic stuck-in-a-rut case (the agent keeps running `ls /tmp` over
and over).

It does not catch **alternating cycles**: the agent oscillating
between two or three tool calls that, taken individually, look like
forward progress but in aggregate are a closed loop.

Examples of cycles the identical-repeat detector misses:

```
A → B → A → B → A → B               (length-2)
A → B → C → A → B → C → A → B → C   (length-3)
read(x) → write(x) → read(x) → write(x) → …
shell(ls a/) → shell(ls b/) → shell(ls a/) → shell(ls b/) → …
```

The agent surfaced this exact gap during soak v6's investigation
phase, then shipped a function to address it.

## Decision

Add `detect_ping_pong(history, *, min_cycle_length=2,
max_cycle_length=3, abort_at_repeats=2) -> LoopVerdict` to
`chimera/tools/loop_guard.py`.

The function inspects the **tail** of `history` for a repeating
pattern of `min_cycle_length..max_cycle_length` tool-call signatures.
When the same cycle appears `abort_at_repeats + 1` times in a row,
returns `LoopVerdict.ABORT`. Otherwise `LoopVerdict.OK`.

It does **not** issue `WARN` — by design. The identical-repeat
detector already provides graduated warning; ping-pong is a
strictly-stronger signal that the model has settled into a closed
orbit, and the right reaction is abort + retry with a different
tier or remediation hint, not "keep going but flag it."

### Where overlap with `detect_degenerate_loop` is acceptable

Six identical calls also match a length-2 cycle of `[A,A]`, so
`detect_ping_pong` returns ABORT on that input too. This is by
design: a stronger detector firing in addition to a weaker one is
not harmful. The two detectors are intended to run side-by-side;
either firing is sufficient to abort.

## Test coverage

8 tests added to `tests/test_guards.py`:

- empty history → OK
- short history (below `min_cycle_length * 2`) → OK
- length-2 cycle repeating 3× → ABORT
- length-3 cycle repeating 3× → ABORT
- identical repeats (overlap with `detect_degenerate_loop`) → ABORT
- one-off pattern (cycle then stray) → OK
- tail-only inspection (noise prefix + clean cycle tail) → ABORT
- custom `abort_at_repeats=3` threshold raises bar by one full cycle

Full test_guards.py suite: **44 passed** (was 36; +8 for ping_pong).

## Wiring (future work — not in v4.87)

The function is exported and tested but not yet *called* by ACT.
The wiring decision (call it before or after `detect_degenerate_loop`?
combine verdicts? new escalation finish_reason `ping_pong_detected`?)
is deferred to a later release. v4.87 is strictly the library-level
addition.

When wiring lands, the natural integration points are:

- `chimera/core/act.py::_run_one` — call both detectors after each
  tool round; ABORT if either triggers
- `chimera/core/escalation.py` — add `ping_pong` as an escalating
  finish_reason alongside `degenerate_loop`

## Soak provenance

This is the first ADR in the chain where the source-of-truth
implementation came from a Chimera soak run, not from an operator
edit. The agent:

1. Investigated `detect_degenerate_loop` during soak v6 phase 1
2. Identified the alternating-cycle gap in its own remediation doc
3. Drafted `detect_ping_pong` in phase 2 and committed it
4. The function imports cleanly and the pre-existing 36 guard tests
   all still pass against it

The operator's role in v4.87 was: cherry-pick the commit, write the
regression test suite the agent didn't write, file this ADR. The
*code* is the agent's.

## Related

- ADR 0003 — ACT-phase guards (original loop_guard surface)
- ADR 0097 — Post-escalation remediation (the v4.84 hint surface
  that enabled the agent to ship this fix)
- `mind/postmortems/soak-v6-2026-05-22.md` — six-soak arc closure
