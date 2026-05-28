# v35 soak postmortem — chip-branch-jump guard misfires on every secondary worktree

**Date**: 2026-05-28
**Soak**: `scripts/long_cycle_soak_v35.sh` (post-v4.115.0 inaugural soak)
**Outcome**: operational FAIL before substantive work began. No diagnosis produced.
**Headline**: ADR 0141 layer-2 enforcement (`chimera run` refusal) misidentifies *every* `git worktree add`-created worktree as the main worktree, blocking all soak iterations at $0 spend.

---

## Substantive layer

**No substantive output.** The soak never executed a single productive `chimera run` iteration. Phase 1 ran 5 cooldown-spaced no-op iterations (~95s wall) before the supervisor terminated it; phase 2 never started. Therefore:

- Phase 1 design recommendation: **N/A** (no design note produced)
- Hypothesis classification (H1 retrieval-distractor / H2 context-budget displacement / H3 category-fundamentals): **N/A**
- Phase 2 outcome: **did not run**
- Auto-generated PR: **none opened**
- Worktree (still present for forensics): `/Users/dave/chimera-soak-v35-2026-05-28-0054` on branch `chimera-soak/v35-2026-05-28-0054`

The F2 temporal-reasoning regression diagnosis (−10.42pp, see [PR #98](https://github.com/elementalcollision/chimera/pull/98)) remains an open chartered investigation; it must be re-run by a follow-up soak once the guard defect is fixed.

---

## Operational layer

### Failure mode

Every `chimera run` invocation in phase 1 exited with code 2 immediately, printing:

```
ERROR: chimera run refuses to operate in the main worktree on a non-main branch.

  worktree : /Users/dave/chimera-soak-v35-2026-05-28-0054
  branch   : chimera-soak/v35-2026-05-28-0054
```

The soak loop treated this as a benign "engine skip", logged `chimera trust degrade-check: ok`, slept 15s, and re-tried — yielding an indefinite no-op loop bounded only by `MAX_ITERATIONS_PER_PHASE=200` (≈ 67 min of pure noise per phase).

### Root cause — ADR 0141 layer-2 guard cannot distinguish primary from secondary worktrees

The detector at [chimera/core/doctor.py:496-550](chimera/core/doctor.py:496) (`detect_main_worktree_branch_drift`) uses:

```python
toplevel = Path(subprocess.run(["git", "rev-parse", "--show-toplevel"], ...).stdout.strip()).resolve()
cwd = repo_root.resolve()
if cwd != toplevel:
    return DriftSignal(False, ..., "cwd ... ≠ git toplevel ...; not the main worktree")
```

`git rev-parse --show-toplevel` returns the working tree of *whichever worktree you're inside*, not the primary worktree. For a `git worktree add`-ed secondary worktree, `cwd == toplevel` holds just as it does in the primary — so the guard concludes "this IS the main worktree" and (if HEAD is not `main`) refuses to run. The guard fundamentally cannot tell a secondary worktree apart from the primary using this check.

**Empirical confirmation** (this session, from the affected worktree):

```
$ git -C /Users/dave/uberagent                       rev-parse --git-dir         → .git
$ git -C /Users/dave/uberagent                       rev-parse --git-common-dir  → .git
$ git -C /Users/dave/chimera-soak-v35-2026-05-28-0054 rev-parse --git-dir         → /Users/dave/uberagent/.git/worktrees/chimera-soak-v35-2026-05-28-0054
$ git -C /Users/dave/chimera-soak-v35-2026-05-28-0054 rev-parse --git-common-dir  → /Users/dave/uberagent/.git
```

The correct discriminator is `--git-dir == --git-common-dir` (only true in the primary worktree). The current check using `--show-toplevel` cannot work for this purpose.

### Why didn't this surface earlier?

ADR 0141 Layer 2 (`chimera run` refusal) shipped after the v25-v34 soak series consolidated into the post-v4.115.0 release. The v35 runner is the first soak to actually invoke `chimera run` against the new guard from inside a secondary worktree. The unit test at `tests/test_cli_run_refusal.py` exercises the guard with mocked subprocess output, which masks the worktree-detection gap; no integration test runs the guard from a real secondary worktree. The defect was therefore invisible until the inaugural post-v4.115.0 soak.

### Wall-clock & spend

| Metric | Value |
|---|---|
| Total wall | ~95s |
| Phase 1 wall | 95s (terminated after iter 3 completed, iter 4 in cooldown) |
| Phase 2 wall | 0 (never started) |
| Iterations completed | 5 (all no-op exits) |
| Total spend | $0.00 |
| Final cycle count | 0 |
| API calls | 0 (chimera exited before any provider call) |

### Infrastructure shakeout — what we learned anyway

Because no API call was made, most post-v4.115.0 infrastructure was *not* exercised:

| Mechanism | Source | Exercised? | Result |
|---|---|---|---|
| Persistent asyncio loop | [#93](https://github.com/elementalcollision/chimera/pull/93) / [#94](https://github.com/elementalcollision/chimera/pull/94) | No | not exercised |
| Shared `httpx.AsyncClient` | [#97](https://github.com/elementalcollision/chimera/pull/97) | No | not exercised |
| Ollama timeout/retry + BM25 fallback | [#96](https://github.com/elementalcollision/chimera/pull/96) | No | not exercised |
| Chip-branch-jump prevention | [ADR 0141](docs/adr/0141-chip-branch-jump-layers-2-3.md) | **Yes** | **misfired — false positive on secondary worktree** |
| Witness panel verdicts | — | No | no panel runs occurred |
| Soft-sentinel / wiring_coordinator | `_soak_common.sh` | No | phase 1 never produced the sentinel target |
| Watchdog / killgroup trap | `_soak_common.sh` | Partially | killgroup trap held; SIGTERM did not stop the loop on first try (SIGKILL succeeded) |

### Honest disclosures

- **Operator-side**: I (the supervisor) launched without first dry-running `chimera run` from the prepared worktree. A 30s precheck would have caught the guard misfire before the full soak started. Recommend adding a sanity-call to the soak preamble (`chimera doctor` or a no-op `chimera run --help` from inside the freshly created worktree, fail fast if exit != 0).
- **Chip framework**: the soak's loop logs `engine skips and gate denials are normal` as a footnote to every non-zero `chimera run` exit. That message is appropriate when ENGINE_GATES deny a tool call mid-iteration; it is *misleading* when `chimera run` exits 2 before doing anything, because the cycle counter and spend both stay at 0. The loop has no "are we making any forward progress?" check.
- **Substantive**: zero substantive output. The F2 temporal-reasoning diagnosis remains open and must be re-chartered after the guard defect lands a fix.

---

## Recommended next chips

1. **Fix the guard detector** (highest priority — blocks every future soak).
   - Change [chimera/core/doctor.py:496-550](chimera/core/doctor.py:496) to use `git rev-parse --git-dir` vs `--git-common-dir` to identify the primary worktree (they are equal only in the primary).
   - Add an integration test that creates a real `git worktree add`-ed branch and asserts `chimera run` does **not** refuse from inside it.
   - Update `tests/test_cli_run_refusal.py` to cover the secondary-worktree path.

2. **Add a soak preflight** to `_soak_common.sh`:
   - After `git worktree add`, run `chimera doctor` (or equivalent) inside the new worktree and abort the soak immediately if it reports drift / refusal-class errors. Fail fast costs seconds; a no-op soak costs hours.

3. **Add a forward-progress watchdog** to the soak loop:
   - If N consecutive iterations report `cycle=0 spend=$0`, abort with a `FATAL: no forward progress` marker rather than continuing to spin until the iteration cap.

4. **Re-charter v35** (LoCoMo temporal-regression investigation) once chips 1-3 land. The substantive question (why does hybrid retrieval hurt temporal-reasoning by 10.42pp) is unchanged and still chartered.

---

## Substantive verdict

**FAIL** — no diagnosis produced. F2 temporal-regression investigation remains open.

## Operational verdict

**FAIL** — post-v4.115.0 infrastructure could not be exercised because a precondition guard (ADR 0141 layer 2) misfires on the soak's own worktree. The defect is in the guard's worktree detection, not in any of the v4.115.0 mechanisms themselves (those were not reached).

## Forensic artifacts (preserved)

- Soak log: `state/long_cycle_v35_2026-05-28-0054.log`
- Soak worktree: `/Users/dave/chimera-soak-v35-2026-05-28-0054` (intact, branch `chimera-soak/v35-2026-05-28-0054`)
- Launch wrapper log: `/tmp/v35-soak-launch.log`
