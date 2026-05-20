# Soak v3 — focused remediation retry (2026-05-20 evening)

**Goal.** Land the deliverable that soak v2 didn't: a minimal patch to
`chimera/tools/loop_guard.py` (or `chimera/core/act.py`) that addresses
the `degenerate_loop_abort` hot signature from soak v1.

**Why v3 instead of declaring v2 done.** Soak v2 produced six findings,
all valuable, but the *named target* never got touched. Now that the
v4.78 INBOX priority and v4.79 artifact validation fixes are in, the
soak runner has a clean shot at the original goal without the drift
that derailed v2.

---

## What changed since v2

Three pieces of soak-v2-driven plumbing are now in main and active:

| Version | Change | Effect on v3 |
|---|---|---|
| v4.76 | Trust escape hatch + observer-mode doctor warning | Already had trust state seeded by the runner; v3 inherits |
| v4.77 | SIGTERM-safe WAL checkpoint + close-time checkpoint | Clean shutdowns won't leave orphan WALs |
| v4.78 | Operator-first ASSESS priority + INBOX provenance | Engines can fire without displacing operator tasks |
| v4.79 | NL artifact validation + non-empty check | Phantom `completed=True` will downgrade to `artifact_missing` |

---

## v3 design

### Phase 1 — investigation ($5 cap, watchdog A)

- **`CHIMERA_ENGINES_ENABLED=0`** for phase 1. Soak v2's data: the
  investigation only burned $0.28 across 5 substantive subtasks
  before drifting to engine-proposed work. Cutting engines removes
  the displacement source entirely. v4.78 would have handled this
  too (operator tasks sort first), but belt-and-suspenders for the
  cleanest signal.
- Target: produce `mind/research/loop-abort-investigation.md` with
  the verdict + a fix sketch + a `## READY-FOR-REMEDIATION` marker.
- Soak v2 had a 7-bullet INBOX. Trimming to 4 bullets — read the
  guard, read the call site, hypothesise, write the doc — since
  the wiki_search + sub-agent steps added overhead without clear
  value in v2 (the sub-agent spawn worked but its critique was
  generic).

### Phase 2 — remediation ($5 cap, watchdog B)

- Engines back on (`CHIMERA_ENGINES_ENABLED=1`, session mode on)
  for chronicle continuity. v4.78 keeps the operator's
  remediation tasks at the head of ASSESS.
- Target: edit `chimera/tools/loop_guard.py` or
  `chimera/core/act.py` per the phase-1 verdict, add a regression
  test, commit with `[agent]` prefix to the soak branch, run the
  loop_guard test file.

### Artifact validation is implicit

v4.79's `expected_artifacts()` will catch any phantom
`Write all of the above to ...` completion. No special INBOX
wording needed — the NL regex matches the existing phrasing.

### Budget shape

```
Phase 1: $5 cap, 50¢ safety buffer, watchdog A
Phase 2: $5 cap, 50¢ safety buffer, watchdog B
Total:   $10
```

Expected actual spend ≤ $5 based on v2 data ($0.28 for the work
that was actually focused on the target).

---

## Acceptance criteria

The run is **successful** if at the end:

1. `mind/research/loop-abort-investigation.md` exists, non-empty,
   contains `## READY-FOR-REMEDIATION`.
2. The verdict is named: `false-positive` / `correct` / `unresolved`.
3. **If false-positive or correct:** a commit on the soak branch
   with the patch + a regression test.
4. **If unresolved:** a commit with a failing test harness that
   would resolve the verdict.
5. `uv run pytest tests/test_loop_guard.py -q` passes on the branch.
6. Total spend ≤ $10.

The run is **a useful failure** if (1)+(2) land but no patch — same
diagnostic value as v2 but with the deliverable visible.

---

## What v3 should NOT do

- Spawn sub-agents for adversarial critique. Soak v2 confirmed the
  pattern works; it's not load-bearing for this specific target.
- Survey the codebase broadly. The investigation is narrow:
  loop_guard.py + the call site in act.py.
- Engine-driven exploration during phase 1. Disabled.

---

## How to launch

```bash
bash scripts/long_cycle_soak_v3.sh
```

Live tail: `tail -f state/long_cycle_v3_2026-05-20.log`.

SIGINT behaviour: same as v1/v2.

After the run:

```bash
WORKTREE_DIR=$(ls -d /Users/dave/chimera-soak-v3-* | tail -1)
cd "$WORKTREE_DIR"
git log --oneline main..HEAD
git diff main -- chimera/tools/loop_guard.py
cat mind/research/loop-abort-investigation.md
uv run pytest tests/test_loop_guard.py -q
```
