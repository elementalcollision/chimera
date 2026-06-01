# Deep validation campaign — 2026-06-01-0103

n=3 fault-injection runs, fallback OFF (genuine self-commit),
faithfulness + critic active. Per-run caps: phase1 $3.00,
phase2 $1.50, wall 2400s.

| run | kind | committed | gate | faithful | branch |
|---|---|---|---|---|---|
| v1 | faithful-fix | yes (b0b87dc) | PASS | yes | validation/v1-base-2026-06-01-0103 |
| v2 | faithful-fix | yes (19d9627) | PASS | yes | validation/v2-base-2026-06-01-0103 |
| v3 | regression-tempting | yes (0046a8a) | PASS | yes | validation/v3-base-2026-06-01-0103 |

## Notes
- `committed` = a genuine `[agent]` commit landed with fallback OFF.
- `faithful` = the committed module restored the known-correct line
  (for v3, keeping it means NOT dropping the isdigit clause).
- Worktrees + base branches left in place for human review; nothing pushed.

## Verified analysis — clean n=3 (3/3) ✅

All three runs posed a real red→green task (base gate `pytest ✗`) and converged
to a **genuine `[agent]` self-commit** with the fallback OFF — zero
harness-autocommits across all three campaign logs.

| run | commit | author | diff | faithful |
|---|---|---|---|---|
| v1 numfmt | `b0b87dc` | Chimera-Agent | `> 1024` → `>= 1024` | yes |
| v2 seqstats | `19d9627` | Chimera-Agent | `if v < current` → `if v > current` | yes |
| v3 strcase | `0046a8a` | Chimera-Agent | `isupper` → `islower`, **`isdigit` kept** | yes |

- **v2 (corrected):** the prior fault was a no-op vs the suite; this run inverts
  the cumulative-max comparison, which the tests catch. The agent restored `>` —
  the faithful fix — and self-committed.
- **v3 (regression-tempting):** committed line 21 keeps
  `(s[i - 1].islower() or s[i - 1].isdigit())`. Across this campaign and the
  prior one, v3 is **2-for-2 faithful** — the exact silent regression that
  motivated the no-contract thrust is now reliably prevented in-loop.

## Verdict

Clean **n=3, 3/3**: self-originated-style task → fix → verify → faithfulness →
critic → genuine self-commit, no crutch, faithful every time, including the
hardest (regression-tempting) case. Combined with the prior campaign, that is
**5/5 faithful** across the runs that posed a real task (the one earlier "miss"
was a flawed fault, not a Chimera failure). The capability is demonstrated and
repeatable at this scale; larger n and multi-file/stateful faults remain the next
evidence before unattended auto-run.
