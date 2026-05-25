# Chip-branch-jump prevention — Layers 2 and 3 design

Composes with PR #46 (Layer 1: `chimera doctor` warn check) to complete the
3-layer detection-and-response stack chartered in ADR 0114's autonomous-
delivery framework.

## Recap — the papercut

Chip sessions spawned via `mcp__ccd_session__spawn_task` sometimes check
out their feature branch into the operator's main worktree
(`/Users/dave/uberagent`) instead of a fresh sibling worktree. Recovery
requires stash + checkout + worktree-add + stash-pop. Hit 3+ times across
the v4.114.0 chapter (PRs #41, #49, #52).

Layer 1 is reactive — fires only when the operator runs `chimera doctor`
voluntarily.

## Layer 2 — refusal at `chimera run` startup

### Where the hook fires

In `chimera/cli.py`, inside the `args.command == "run"` branch, BEFORE
`ChimeraLoop()` is constructed. This guarantees no provider API spend
on a doomed run.

### Detection logic

Reuses Layer 1's detection by extracting a shared
`detect_main_worktree_branch_drift(repo_root) -> DriftSignal` helper from
`chimera/core/doctor.py`. `DriftSignal` is a tiny dataclass:

```
@dataclass(frozen=True)
class DriftSignal:
    drifted: bool
    branch: str | None    # e.g. "feat/foo" or None on detection failure
    toplevel: Path | None
    reason: str           # human-readable
```

Doctor's `_check_main_worktree_branch_drift` becomes a thin wrapper that
maps `DriftSignal -> CheckResult`. Layer 2 calls the same helper and
maps `drifted=True` to a stderr-printed refusal + non-zero exit.

### Override mechanism

`CHIMERA_ALLOW_MAIN_BRANCH_DRIFT=1` in the environment bypasses the
refusal. Mirrors the `SOAK_SKIP_CONCURRENT_CHECK=1` precedent from
PR #51 (operator-aware single-use escape hatch). Default OFF. Documented
in the refusal message itself and in `chimera run --help` (footer
epilog).

### Refusal message (locked)

```
ERROR: chimera run refuses to operate in the main worktree on a non-main branch.

  worktree : <toplevel>
  branch   : <branch>

This is the chip-branch-jump papercut (ADR 0114 / PR #46 / ADR 0141).
To recover:

  1. Stash any uncommitted work:  git stash push -u -m "chip-recovery-$(date +%s)"
  2. Switch back to main:         git checkout main
  3. Move the chip work to a fresh worktree:
     git worktree add ../<dir> <branch>
     cd ../<dir>
  4. Restore your work in the new worktree: git stash pop

Override (operator-aware, single-use): export CHIMERA_ALLOW_MAIN_BRANCH_DRIFT=1
```

Exit code 2 (distinct from the cycle-failure exit codes).

## Layer 3 — pre-commit hook auto-logging to CHRONICLE

### Option choice — A (pure-bash) wins

Pure-bash `pre-commit` hook installed at `.git/hooks/pre-commit`. No
Python interpreter dependency, no chimera-venv-activation needed, no
import-path concerns when git invokes the hook from arbitrary cwd.

Rejected: Python script `chimera/hooks/pre_commit.py` invoked via the
shebang. Heavier — requires `uv` or activated venv resolvable from
git's hook execution environment, fragile across operator setups.

### Hook semantics

- DOES NOT block the commit. Layer 3's job is evidence-recording, not
  enforcement. Refusing the v4.114.0 release commits at commit-time
  would be hostile.
- Fires only when: `git rev-parse --show-toplevel` ≡ cwd AND
  `git symbolic-ref --short HEAD` ≠ `main`.
- Appends one structured Markdown block to `mind/CHRONICLE.md`
  (creating the file if missing). Format is grep-friendly so future
  chips can count occurrences:
  `grep -c "chip-branch-jump detected" mind/CHRONICLE.md`.

### CHRONICLE entry (locked format)

```
## YYYY-MM-DD HH:MM:SS — chip-branch-jump detected at commit time

**Event**: pre-commit hook fired
**Worktree**: <toplevel> (= git toplevel)
**Branch**: <branch>
**Commit author**: <git config user.email>
**Mitigation**: this commit landed but the chip-branch-jump is recorded for audit.
**See**: ADR 0114, PR #46 (Layer 1), ADR 0141 (Layers 2+3).
```

(Commit subject is unavailable in pre-commit context without parsing
the staged COMMIT_EDITMSG path; we omit it rather than add fragility.)

### Hook installation — `chimera doctor --install-hooks`

New flag on the existing `doctor` subparser. Idempotent:

1. Locate `.git/hooks/pre-commit`.
2. If absent → write our hook with a sentinel marker line
   `# chimera-pre-commit-hook v1` and `chmod +x`.
3. If present AND contains our sentinel → report "already installed",
   exit 0.
4. If present AND does NOT contain our sentinel → refuse with a clear
   message ("foreign hook detected; will not clobber; append manually
   or remove existing hook first"). Never silently overwrite an
   operator's existing hook.

Bonus: `chimera doctor --install-hooks` prints a one-line confirmation
and runs the rest of doctor's checks after.

### Removal

Out of scope this PR. Operator can `rm .git/hooks/pre-commit` manually;
the sentinel marker makes verification trivial.

## Test plan

Mirroring `tests/test_doctor.py::test_worktree_branch_drift_*` patterns:

- `tests/test_cli_run_refusal.py` (new file, ~5 tests):
  - refuses with exit 2 when drifted
  - allows when `CHIMERA_ALLOW_MAIN_BRANCH_DRIFT=1`
  - allows when on main
  - allows when cwd != toplevel
  - refusal message includes the override hint

- `tests/test_doctor.py` (extended, ~4 tests):
  - install writes hook with sentinel + executable bit
  - install is idempotent (second install reports already-installed,
    no double-write)
  - install refuses to clobber a foreign hook
  - hook content (loaded from package data via `importlib.resources`)
    contains the CHRONICLE template strings

The pre-commit hook itself is bash; we test the installer's behavior,
not the hook's runtime (which has trivial branching and depends only on
`git` + standard POSIX utilities).

## Scope discipline

5–7 files (target met):
1. `chimera/core/doctor.py` — extract `detect_main_worktree_branch_drift` helper
2. `chimera/cli.py` — Layer 2 refusal + `--install-hooks` flag
3. `chimera/hooks/__init__.py` + installer + bash template (single new package)
4. `tests/test_cli_run_refusal.py` (new)
5. `tests/test_doctor.py` — append installer tests
6. `docs/adr/0141-chip-branch-jump-layers-2-3.md` (Proposed)
7. `docs/adr/README.md` — append row, bump counter

No ADR 0114 amendment in this chip (deferred per charter).

## False-positive / false-negative honesty

- **FP**: an operator legitimately working on a feature branch in the
  main worktree (e.g. recovery sessions) WILL hit Layer 2's refusal.
  Mitigated by the override env var.
- **FN**: a chip session that never invokes `chimera run` and never
  commits (e.g. a pure read-only inspection chip) will not trip Layer 2
  or Layer 3 — but it also won't damage main, so no harm done.
- **FP** for Layer 3: every legitimate operator commit on a feature
  branch (post-checkout-into-feature-branch-in-main-worktree, e.g.
  emergency hotfix work) WILL log a CHRONICLE entry. Acceptable cost —
  CHRONICLE is append-only and the format is grep-distinguishable.

## READY-FOR-REMEDIATION
