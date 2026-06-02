# Enforced self-determined soak characterization — 2026-06-02-1413

N=3 sequential runs, RANK=13, SELF_BASE=main, enforce ON.
Each run is race-free (own worktree). Per-run wall cap 2400s.

| run | dur(s) | task | committed | verify verdict | gate invoked | escalated | primary | escalation | result |
|----|----|----|----|----|----|----|----|----|----|
| 1 | 2611 | fix the 3 ruff lint finding(s) in tests/test_locomo.py | no | FAIL — ruff ✓, pytest ✗ | yes | true | false | false | INCONCLUSIVE |
| 2 | 2589 | fix the 3 ruff lint finding(s) in tests/test_locomo.py | no | FAIL — ruff ✓, pytest ✗ | NO | - | - | - | INCONCLUSIVE |
| 3 | 444 | fix the 3 ruff lint finding(s) in tests/test_locomo.py | yes | FAIL — ruff ✓, pytest ✗ | yes | true | false | true | INCONCLUSIVE |

## Summary
- PASS (committed + ruff PASS + gate allowed): **0/3**
- Convergence and gate-decision distribution above; high variance in
  phase-1 convergence is the known characterization finding.
