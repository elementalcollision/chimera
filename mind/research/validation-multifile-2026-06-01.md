# Multi-file fault validation — 2026-06-01

One task, **two-file fix**, fallback OFF (genuine self-commit), multi-file-aware
faithfulness + critic (PR #221). Faults: boundary in `chimera/numfmt.py`
(`>= 1024` → `> 1024`) + inverted comparison in `chimera/seqstats.py`
(`if v > current` → `if v < current`); one combined contract test
(`tests/test_multifile_validation.py`) catches both.

## Result — clean success ✅

| metric | value |
|---|---|
| committed | `ccb6fd9` — author=Chimera-Agent, ONE `[agent]` commit, fallback OFF (zero harness-autocommits) |
| files touched | `chimera/numfmt.py` + `chimera/seqstats.py` (scope-clean) |
| gate | PASS (combined contract) |
| numfmt faithful | yes — restored `value >= 1024` |
| seqstats faithful | yes — restored `if v > current` |

The agent diagnosed two independent bugs across two files, fixed both, and landed
a single scope-clean genuine self-commit; the multi-file faithfulness + critic
verified every changed file. The multi-file frontier is demonstrated end to end.

## Honest scope

n=1 multi-file run; both faults are pure-function single-line fixes in
independent modules (not a coupled cross-file contract). Coupled multi-file
changes (a contract that must change consistently in both files) and larger n are
the next evidence. Stateful faults remain open — the differential's input corpus
is for pure single-string functions and cannot characterize mutable state.
