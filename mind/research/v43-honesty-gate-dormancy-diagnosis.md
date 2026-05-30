# v43 R2: the honesty gate was DORMANT — `write_targets` empty across the soak

**Date**: 2026-05-29
**Surfaced by**: v43 parallel-build soak (`v43-trio-2026-05-30-0052`), capstone
`mind/research/v43-trio-capstone.md` §"The finding (falsification-honest)".
**Scope**: honesty-gate COVERAGE only. The v43 build itself converged correctly
(17/17, three scope-clean `[agent]` commits); `tests_passing` — the load-bearing
honesty field — was genuinely accurate on all three postmortems. This note is
about why the *in-loop* honesty substrate never got to check that.
**Status**: fixed (git-status fallback + regression tests + numeric convention).

---

## 1. Symptom

On all 20 ACT-cycle records of the v43 run, the write-target-based in-loop ACT
gates were effectively no-ops because their sole input, `ActResult.write_targets`,
was empty:

- `check_import_shadowing(write_targets)` — never inspected a `.py`.
- `check_postmortem_honesty(write_targets)` — never inspected a `.md`, so the
  just-landed numeric-honesty **Rules D/E** (`act_cycles` / `spend_usd`, PR #158)
  never evaluated anything. The three postmortems' `act_cycles: 7` /
  `spend_usd: 0.09` per-build claims shipped **un-gate-validated**.

The build's correctness was proven by *other* gates that do NOT read
`write_targets` — the primary pytest gate and the scope/charter git-diff gates —
which is why convergence was real while the honesty substrate stayed dark.

## 2. Root cause — how `write_targets` is populated, and why it stayed empty

Trace, write → gate:

1. **Population** is one line in the ACT round loop
   ([act.py](../../chimera/core/act.py) ~`2718`):
   ```python
   recent_calls = history[-len(response.tool_uses):]
   write_targets[:] = extract_write_targets_from_calls(recent_calls, existing=write_targets)
   ```
2. `extract_write_targets_from_calls` ([act.py:479](../../chimera/core/act.py))
   contributes a path **only** when the tool name is in
   `_WRITING_TOOL_NAMES = {code_exec, write_file, edit_file, create_file}`
   ([act.py:471](../../chimera/core/act.py)), then regex-scans that call's args
   for path-shaped tokens.
3. The gate reads the accumulated `write_targets` on the clean-stop branch
   ([act.py:2324](../../chimera/core/act.py)).

Two facts collapse this to "empty all run":

- **Only `code_exec` of the four writing names is actually registered.**
  `register_core_tools` wires `shell`, `web`, `code_exec`, `mind_search`
  ([tools/__init__.py:81](../../chimera/tools/__init__.py)). `write_file` /
  `edit_file` / `create_file` do not exist — they are aspirational entries in
  the frozenset.
- **The `shell` tool can write, and is deliberately excluded.** Its allowlist
  includes `python3` and `git`
  ([tools/shell.py:48](../../chimera/tools/shell.py)), so an agent writes a
  module or a postmortem with `shell argv=["python3","-c","...write_text..."]`
  or `git apply` — argv-only, no metacharacters needed. But `shell ∉
  _WRITING_TOOL_NAMES` (the soak-v7 fix that stopped `cat file` reads being
  mis-counted as writes). So **every shell-routed write is invisible to
  `write_targets`.**

→ **Hypothesis (b) confirmed.** The v43 agent wrote modules and postmortems via
`shell` (`python3 -c` + `git`), not `code_exec`, so `extract_write_targets_from_calls`
captured nothing on every cycle. Not (a) — the field IS threaded into the gate
(and into the `ActResult`); it was genuinely empty at the source. Not (c) — it
is reset per `execute()` (one ACT cycle) by design, and accumulates correctly
across rounds *within* a cycle. Not (d) — the soak uses the same
`ActExecutor.execute()` path as `chimera run` (via `loop._phase_act`); nothing
soak-specific drops it.

A secondary structural narrowing compounds it: the write-target gates run **only
on the clean-stop + `completed` branch**. A postmortem written in a cycle that
exits via `max_rounds` / `skipped_three_strikes` (the v43 run had 8 such
postmortem-churn cycles) is never even handed to the gate. The fallback below
addresses the *input*; the residual "gate not called on non-clean exits" is
noted in §6.

## 3. v43-specific or general?

**General, and long-standing.** The capture surface (`_WRITING_TOOL_NAMES`,
shell-excluded, only `code_exec` registered) is platform-wide and predates v43.
Any soak whose agent writes via `shell` produces empty `write_targets`. The
in-loop `check_postmortem_honesty` gate has existed since the v40′ sub-chip-2
work, but if earlier soaks (v40′, v41, v42) also wrote their postmortems via
shell — the path of least resistance given the toolset — then **the in-loop
honesty gate has never actually fired in a real soak.** What has caught dishonest
postmortems to date is **post-hoc operator review** (each capstone hand-checks
`tests_passing` ↔ ledger `tests_passed_any`). The retained committed postmortems
(v40–v43) are consistent with this: they're honest on `tests_passing` because a
human verified it, not because the gate did.

The soak ledgers themselves can't re-confirm this directly — the worktrees were
pruned, and `build_act_record` never serialized `write_targets` anyway (it
records `tool_calls` as `{name, args_hash, is_error, duration_ms}`
([soak_ledger.py:176](../../chimera/core/soak_ledger.py)), with args **hashed**),
so "write_targets empty in the ledger" was an operator inference from the gate's
silence, not a literal ledger field. The code path is the authoritative witness,
and it is unambiguous.

## 4. Fix — a `git status` fallback so the gate fires on what's on disk

Option (b) from the charter, because it is robust to *every* root-cause variant
(shell writes, unregistered tools, future tool paths): the honesty gate should
not depend on *which* tool did the write. `git status` is ground truth for "what
changed in this worktree."

- **`_git_changed_paths(worktree_root, suffix)`** — `git status --porcelain
  --untracked-files=all`, filtered by suffix; covers staged, unstaged, and
  untracked (a just-written, uncommitted postmortem), resolves renames to their
  destination, fail-soft to `[]` on any git/OS error.
- **`_postmortem_gate_targets(write_targets, worktree_root)`** — `.md` entries
  of `write_targets` UNION the worktree's changed `.md`, deduped by resolved
  path. `worktree_root=None` → fallback OFF → exact legacy behavior (keeps unit
  tests and non-soak `chimera run` hermetic).
- **`check_postmortem_honesty(write_targets, worktree_root=None)`** now iterates
  `_postmortem_gate_targets(...)`. The loop call site passes `Path.cwd()`
  ([act.py:2324](../../chimera/core/act.py)), enabling the fallback in-soak.

The gate is still no-op outside a soak (`CHIMERA_SOAK_RUN_ID` unset) and
fail-soft throughout, so it can never block a postmortem on an unverifiable
number or an unreadable worktree.

Populating `write_targets` from shell writes (option a) was **rejected as the
primary fix**: re-admitting `shell` to the write-capture surface would re-open
the soak-v7 false-positive (`cat file` counted as a write) and require fragile
argv intent-parsing. The git fallback gets the same coverage from ground truth.

## 5. Numeric semantics for fan-out (N>1): the convention

The ambiguity the v43 postmortems exposed: they reported **per-build**
`act_cycles: 7` (7+7+7 ≈ 20), but `summarize_run().act_cycles` is the
**cumulative** run total (`len(act_rows)` = 20), and Rule D compares against it.
Per-build attribution is not recoverable from the ledger — ACT records are not
tagged by build target.

**Decision: `act_cycles` and `spend_usd` are CUMULATIVE-RUN fields.** In a
fan-out soak every postmortem reports the same run totals (the ledger's 20 and
the DB's `$0.41`), because that is what the substrate can verify. This makes
Rule D/E well-posed with **no comparison change** — the gate already compares
against the cumulative ground truth; the fix is (1) making the gate actually
fire (§4) so the convention is *enforced*, and (2) instructing postmortems/INBOX
to report cumulative. Consequence, now covered by a regression test: a per-build
`act_cycles: 7` against cumulative 20 is a **gate violation** (7 ∉ 20 ± 5), so
the exact v43 drift would now trip.

A non-gated, optional `act_cycles_this_build:` note field can carry the per-build
attribution for human readers without entering the checked comparison; not
implemented here to keep the surface minimal.

## 6. Residual / follow-ups

- **Gate-not-called-on-non-clean-exit.** The honesty gate is only invoked on the
  clean-stop + `completed` branch. A postmortem written in a cycle that ends via
  `max_rounds` / `skipped_three_strikes` still escapes. The fallback fixes the
  *input* but not the *invocation site*; running the honesty gate on the
  non-clean return paths is a larger, separately-scoped change.
- **Generalize the fallback to `check_import_shadowing` / `check_syntax_valid`.**
  Same dormancy applies to the `.py` gates. The same `_git_changed_paths(root,
  ".py")` fallback would close it; deferred to keep this chip focused on the
  honesty gate the v43 run flagged.

## 7. Tests

`tests/test_postmortem_honesty_fallback.py` — proves the gate fires from a
WRITTEN postmortem (`write_targets == []`, found via git status), the v43
per-build-vs-cumulative drift is caught, the cumulative convention passes,
multiple fan-out postmortems are each evaluated, and the legacy
(`worktree_root=None`) / no-soak paths stay no-op.
