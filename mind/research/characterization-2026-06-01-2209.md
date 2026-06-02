# Enforced self-determined soak characterization — 2026-06-01-2209

N=3 sequential runs, RANK=13, SELF_BASE=main, enforce ON.
Each run is race-free (own worktree). Per-run wall cap 2400s.

| run | dur(s) | task | committed | ruff | gate invoked | escalated | primary | escalation | result |
|----|----|----|----|----|----|----|----|----|----|
| 1 | 3025 | fix the 3 ruff lint finding(s) in tests/test_locomo.py | no | FAIL | NO | - | - | - | INCONCLUSIVE |
| 2 | 2863 | fix the 3 ruff lint finding(s) in tests/test_locomo.py | no | FAIL | NO | - | - | - | INCONCLUSIVE |
| 3 | 3307 | fix the 3 ruff lint finding(s) in tests/test_locomo.py | no | FAIL | NO | - | - | - | INCONCLUSIVE |

## Summary
- PASS (committed + ruff PASS + gate allowed): **0/3**
- Convergence and gate-decision distribution above; high variance in
  phase-1 convergence is the known characterization finding.
