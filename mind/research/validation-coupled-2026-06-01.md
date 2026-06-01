# Coupled multi-file fault validation — 2026-06-01

A single logical fault spanning two files, fixable only by a CONSISTENT change to
both: `chimera/tempc.py::c_to_f` and `chimera/tempf.py::f_to_c` are exact inverses
but both carried the same wrong constant (`+30`/`-30` vs `32`). The round-trip
test `f_to_c(c_to_f(c))==c` PASSES on the consistent-but-wrong pair; direct tests
fail; fixing one file alone breaks the round-trip.

## Result — clean success ✅

| metric | value |
|---|---|
| committed | `9a3f071` — author=Chimera-Agent, ONE `[agent]` commit, fallback OFF, **0 harness-autocommits** |
| files | `chimera/tempc.py` + `chimera/tempf.py` (both, scope-clean) |
| gate | PASS (direct + round-trip) |
| tempc | `c * 9 / 5 + 32` — correct |
| tempf | `(f - 32) * 5 / 9` — correct, **consistent with tempc** |

The agent understood the coupling — the inverse relationship and the consistency
the round-trip test encodes — and made a coherent two-file change to the same
correct constant. A coordinated multi-file fix, not two independent guesses.

## Note

The harness's first result line said `tempf_fixed=NO` — a bug in the result grep
(`grep -qE '- 32'` parsed the leading `-` as an option flag), NOT a Chimera
failure. Fixed to `grep -qE -- '- ?32'`. The committed code was correct
throughout (verified by re-running the gate: PASS).

## Frontier status

- single-file (clean n=3 + regression-tempting): 5/5 faithful
- multi-file, INDEPENDENT bugs: genuine 2-file faithful self-commit
- multi-file, COUPLED (this): genuine coherent 2-file faithful self-commit
- stateful: fixed faithfully; machine gates hardened (differential + AugAssign)
