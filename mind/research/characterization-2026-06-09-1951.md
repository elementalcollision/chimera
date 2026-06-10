# Enforced self-determined soak characterization — 2026-06-09-1951

BREADTH sweep — ranks [5 6 7], SELF_BASE=main, enforce ON.
Each run is race-free (own worktree). Per-run wall cap 2400s.

| run | dur(s) | task | committed | verify verdict | gate invoked | escalated | primary | escalation | result |
|----|----|----|----|----|----|----|----|----|----|
| 1 | 315 | fix the 5 ruff lint finding(s) in tests/test_subagent.py | no | FAIL — ruff ✗, pytest ✗ | NO | - | - | - | INCONCLUSIVE |
| 2 | 317 | fix the 4 ruff lint finding(s) in tests/test_act.py | no | FAIL — ruff ✗, pytest ✗ | NO | - | - | - | INCONCLUSIVE |
| 3 | 316 | fix the 4 ruff lint finding(s) in tests/test_http_transport.py | no | FAIL — ruff ✗, pytest ✓ | NO | - | - | - | INCONCLUSIVE |

## Summary
- PASS (committed + ruff PASS + gate allowed): **0/3**
- Convergence and gate-decision distribution above; high variance in
  phase-1 convergence is the known characterization finding.
