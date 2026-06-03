# Enforced self-determined soak characterization — 2026-06-02-1926

BREADTH sweep — ranks [14 4 1], SELF_BASE=main, enforce ON.
Each run is race-free (own worktree). Per-run wall cap 2400s.

| run | dur(s) | task | committed | verify verdict | gate invoked | escalated | primary | escalation | result |
|----|----|----|----|----|----|----|----|----|----|
| 1 | 2408 | fix the 2 ruff lint finding(s) in chimera/server/kfm_tool.py | no | PASS — ruff ✓, pytest ✓ | NO | - | - | - | INCONCLUSIVE |
| 2 | 2054 | fix the 5 ruff lint finding(s) in chimera/core/loop.py | yes | PASS — ruff ✓, pytest ✓ | yes | false | true | null | PASS |
| 3 | 2210 | fix the 14 ruff lint finding(s) in chimera/cli.py | no | FAIL — ruff ✗, pytest ✗ | NO | - | - | - | INCONCLUSIVE |

## Summary
- PASS (committed + ruff PASS + gate allowed): **1/3**
- Convergence and gate-decision distribution above; high variance in
  phase-1 convergence is the known characterization finding.
