# Enforced self-determined soak characterization — 2026-06-02-1714

N=3 sequential runs, RANK=13, SELF_BASE=main, enforce ON.
Each run is race-free (own worktree). Per-run wall cap 2400s.

| run | dur(s) | task | committed | verify verdict | gate invoked | escalated | primary | escalation | result |
|----|----|----|----|----|----|----|----|----|----|
| 1 | 465 | fix the 3 ruff lint finding(s) in tests/test_locomo.py | yes | PASS — ruff ✓, pytest ✓ | yes | true | false | true | PASS |
| 2 | 2312 | fix the 3 ruff lint finding(s) in tests/test_locomo.py | no | PASS — ruff ✓, pytest ✓ | NO | - | - | - | INCONCLUSIVE |
| 3 | 2142 | fix the 3 ruff lint finding(s) in tests/test_locomo.py | yes | PASS — ruff ✓, pytest ✓ | yes | true | false | true | PASS |

## Summary
- PASS (committed + ruff PASS + gate allowed): **2/3**
- Convergence and gate-decision distribution above; high variance in
  phase-1 convergence is the known characterization finding.
