# Enforced self-determined soak characterization — 2026-06-09-1054

BREADTH sweep — ranks [5 6 7], SELF_BASE=main, enforce ON.
Each run is race-free (own worktree). Per-run wall cap 2400s.

| run | dur(s) | task | committed | verify verdict | gate invoked | escalated | primary | escalation | result |
|----|----|----|----|----|----|----|----|----|----|
| 1 | 501 | fix the 5 ruff lint finding(s) in tests/test_subagent.py | yes | PASS — ruff ✓, pytest ✓ | yes | false | true | null | PASS |
| 2 | 2014 | fix the 4 ruff lint finding(s) in tests/test_act.py | yes | PASS — ruff ✓, pytest ✓ | yes | false | true | null | PASS |
| 3 | 2219 | fix the 4 ruff lint finding(s) in tests/test_http_transport.py | yes | PASS — ruff ✓, pytest ✓ | yes | true | false | true | PASS |

## Summary
- PASS (committed + ruff PASS + gate allowed): **3/3**
- Convergence and gate-decision distribution above; high variance in
  phase-1 convergence is the known characterization finding.
