# Enforced self-determined soak characterization — 2026-06-02-0122

N=3 sequential runs, RANK=13, SELF_BASE=main, enforce ON.
Each run is race-free (own worktree). Per-run wall cap 2400s.

| run | dur(s) | task | committed | verify verdict | gate invoked | escalated | primary | escalation | result |
|----|----|----|----|----|----|----|----|----|----|
| 1 | 2858 | fix the 3 ruff lint finding(s) in tests/test_locomo.py | no | FAIL — ruff ✓, pytest ✗ | NO | - | - | - | INCONCLUSIVE |
| 2 | 3304 | fix the 3 ruff lint finding(s) in tests/test_locomo.py | no | FAIL — ruff ✓, pytest ✗ | NO | - | - | - | INCONCLUSIVE |
| 3 | 3173 | fix the 3 ruff lint finding(s) in tests/test_locomo.py | no | FAIL — ruff ✓, pytest ✗ | NO | - | - | - | INCONCLUSIVE |

## Summary
- PASS (committed + ruff PASS + gate allowed): **0/3**
- Convergence and gate-decision distribution above; high variance in
  phase-1 convergence is the known characterization finding.
