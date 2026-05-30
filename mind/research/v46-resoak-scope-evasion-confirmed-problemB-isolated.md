# v46 re-soak — scope_evasion commit-phase fix CONFIRMED; Problem B (commit-not-executed) isolated

**Date**: 2026-05-30
**Soak**: `chimera-soak/v46-soakreport-2026-05-30-1929` (genuine rebuild via
`CHIMERA_SOAK_STRIP_TARGETS`)
**Base**: main @ `62a4717` (PR #180 — scope_evasion on-disk guard)
**Verdict**: the scope_evasion commit-phase stall is **empirically fixed**; the
re-soak isolated the *second half* of the original v46 finding — the agent
self-reports the commit task complete without ever running `git commit`.

## Setup — a genuine rebuild, not a no-op

The v46 module was operator-landed in #179, so a worktree off main starts GREEN.
To force a real rebuild that exercises the phase-2 commit path, the runner
stripped both landed targets on the soak branch via one non-`[agent]` commit
(new `CHIMERA_SOAK_STRIP_TARGETS` knob; default off → zero behavior change):

- `chimera/soak_report.py` (the module — strip → test goes red)
- `mind/research/v46-soakreport-postmortem.md` (the postmortem — must strip too,
  else its stale `READY-FOR-REMEDIATION` marker short-circuits the phase-1
  sentinel before any build happens)

Confirmed red after strip: `5 failed` (ModuleNotFoundError). Phase 1 then
rebuilt the module to **green** (`test-runs.jsonl`: `passed==true`,
`chimera/soak_report.py` 1760 B on disk).

## Result A — scope_evasion commit-phase fix: CONFIRMED ✅

| Signal | This re-soak | Original v46 |
|---|---|---|
| Phase-2 `scope_evasion` firings | **0** | derailed phase 2 (cycle 156 stall) |
| Phase-2 commit-task outcome | reached `stop / completed=True` | three-strikes skip loop |
| Only `scope_evasion` in whole run | phase-1 cycle 146 — **correct** (module genuinely not yet on disk; written cycle 147) | — |

The on-disk-exists guard (`check_scope_evasion(..., base_dir=_import_shadow_scan_root())`,
PR #180) held exactly as designed: in phase 2 the rebuilt module exists on disk,
so naming it in the commit INBOX no longer reads as evasion. The R2 target from
the v46 capstone is closed.

## Result B — NEW isolated finding: the agent stages but never commits ❌

With scope_evasion no longer masking it, the *other* half of the original v46
finding ("the agent staged the files but the `git commit` never executed")
reproduced cleanly. At cycle 156 all three phase-2 tasks self-reported
`completed=True`:

1. "Re-run the gated test; confirm 4 passed" — ran it, 4 passed ✓
2. "Stage ONLY ..." — `git add` ran (worktree shows `A chimera/soak_report.py`,
   `A mind/research/...postmortem.md` — staged) ✓
3. **"Commit with a message starting with `[agent]`"** — `completed=True` after a
   single shell call, **but no commit exists** (`git log main..HEAD` shows only
   the operator strip commit). The files sit staged-but-uncommitted.

The soft-sentinel (`soak_phase2_deliverable_landed`) correctly refused to call
this converged (it requires a real `[agent]` commit in `main..HEAD`), so phase 2
idled to no further signal until the operator stopped it (iter ~119/200, total
spend $0.085 — cheap).

### Root cause (code-anchored)

The ACT completion path in `chimera/core/act.py` is a sequence of gates that each
flip `completed=False` with a `finish_reason`:

- `ungrounded_citation` (ADR 0095) — content
- `scope_evasion` (ADR 0096/0109, +#180 on-disk guard) — content
- `syntax_invalid` (ADR 0105) — content
- `import_shadow` (B2/ADR) — content
- `commit_message_diff_drift` (ADR 0122) — commit **message**, *only if a commit
  happened*

**Every gate verifies the content of work or the message of a commit — none
verify that the commit action actually ran.** In phase-2 (commit-only) the
deliverable *is* the commit, yet nothing in the loop enforces "HEAD advanced".
The only detector is the *external* soak sentinel, which silently re-loops
rather than feeding "you have not committed" back to the agent. The phase-2
INBOX does say in prose — "git add only stages… verify the commit exists with
git log before you stop" — but that is documentation/trust-based.

### The agent diagnosed it itself

At cycle 158 the curiosity engine spawned `q004: "Exploring commit compliance
with strict constraints (ADR 0146/0122/0142)"` and wrote (verbatim):

> Documentation-only compliance gets ~40% adherence. Trust-based prompts? Also
> ~40%. Deterministic hook enforcement (exit code 2 = immediate block,
> unbypassable) achieves ~100%. The gap is not about better docs — it's about
> removing the ability to skip.

That is precisely Problem B: the commit instruction is prose (≈40% adherence);
it needs a deterministic gate.

## Next — R2: commit-landed ACT gate

When the task is a commit task (phase-2 / commit-expected) and the agent reports
completion, verify `HEAD` advanced (a new commit since the task started) before
accepting `completed=True`; otherwise set
`completed=False, finish_reason="commit_not_executed"` and re-prompt "run
`git commit` now." This is the deterministic enforcement the agent's own
research points at, and the natural successor now that scope_evasion no longer
masks it.

## Housekeeping

- Validation-only run: the module is already on main (#179), so there is **no
  code to land** from this soak. The worktree can be pruned.
- The `CHIMERA_SOAK_STRIP_TARGETS` runner knob (default off) is currently
  **uncommitted** in the main working tree — a reusable genuine-rebuild scaffold.
  Landing it (or folding it into the R2 chip) awaits operator authorization.
