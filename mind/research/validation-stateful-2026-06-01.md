# Stateful fault validation — 2026-06-01

A class whose behaviour depends on the SEQUENCE of method calls
(`chimera/runstats.py` RunningStats; bug `self._sum = x` instead of `+=`, so
`.mean()` is wrong only after multiple `.add()` calls). Fallback OFF.

## Result — fixed faithfully, but the machine gates went weak/blind

| metric | value |
|---|---|
| committed | `0079dff` — author=Chimera-Agent, genuine `[agent]` self-commit, fallback OFF |
| gate | PASS (sequence test now green) |
| fix | `self._sum = x` → `self._sum += x` — the correct accumulation fix |
| differential | **0 deltas — BLIND**: the pure single-string corpus cannot characterize a class (no top-level single-arg function), so it contributed nothing |
| mutation | reports FAITHFUL 1.00 — **but does NOT probe the bug site**: the mutator has no `visit_AugAssign`, so `+=` is never mutated; the score came from killing the *other* mutants (`==`, `/`, constants) |

## The honest frontier finding

On stateful code, **both contract-free faithfulness gates provided weak-to-no
coverage of the stateful behaviour itself**:
- the **differential is structurally blind** (pure-function single-string corpus),
- **mutation does not mutate `AugAssign`**, so the accumulation operator — the
  exact stateful bug — was never probed.

What actually pinned the stateful behaviour was the **human-written sequence test**
(add, add, add → mean), i.e. the contract — not a contract-free gate. The agent
fixed it correctly, and the critic (judgment) reviews the diff — but neither
machine gate would have caught a stateful regression that the suite didn't
already pin.

A second imperfection neither machine gate can see: the agent left the now-FALSE
`# BUG: should be self._sum += x` comment on the corrected line. Code correct,
comment stale — only the critic or a human reviewer would flag it.

## Implication / next chip

For stateful code, faithfulness should not rely on the differential (blind) or
on mutation alone (no AugAssign / no state-sequence probing). The targeted fix is
**stateful characterization**: drive a class through a corpus of call SEQUENCES
and snapshot observable state (and/or extend the mutator to cover `AugAssign`),
so the differential has something to compare. Until then, stateful faithfulness
rests on the suite's sequence assertions + the critic's judgment — which carried
this case, but is the documented weak point. The capability (fix + genuine
self-commit) is demonstrated; the *machine verification* of stateful behaviour is
the honest gap.
