# ADR 0121 — soak_lib v4: mind/* journal auto-allow

**Status**: accepted
**Date**: 2026-05-24
**Companion code**: `scripts/soak_lib.sh` v4, `tests/test_soak_watchdog.py`

## Context

`scripts/soak_lib.sh::soak_phase2_deliverable_landed` is the soft
sentinel that lets a long-cycle soak exit phase 2 early once the
agent has committed a charter-clean, test-green diff. "Charter-clean"
means: every file in the cumulative `main..HEAD` diff matches the
operator-supplied whitelist.

v3 (ADR 0120) added a narrow auto-allow for `mind/research/*-remediation.md`
because the v19 retro noted the agent was reliably committing a
remediation summary doc alongside the deliverable.

That single-path exception did not generalize. Across six soaks since
the auto-allow shipped (v19, v22, v23, v24, v24-relaunch, v25) the
agent has consistently committed *other* journal files alongside its
deliverable:

- `mind/CHRONICLE.md` — cycle audit log
- `mind/HEARTBEAT.md` — per-cycle status
- `mind/INBOX.md` — task list the runner writes; agent ticks boxes
- `mind/SESSION_LOG.md` — long-form session narrative
- `mind/research/*-design.md` — the phase-1 design doc

These are operational artifacts the chimera-run loop writes between
cycles. The agent's `git add` step stages them as "modified files"
alongside the deliverable, even when the charter explicitly enumerates
"TWO files only" with overshoot traps.

No amount of charter strengthening has overcome the behavior:

| Soak | Charter strength | Journal files committed |
|------|------------------|--------------------------|
| v19  | "two files"      | 1                        |
| v22  | "FIVE files only, NO others" | 4 (mind/*) |
| v23  | same             | 4 (mind/*)               |
| v24  | same             | 4 (mind/*)               |
| v24-relaunch | tightened | 4 (mind/*)            |
| v25  | "TWO files" + 8 overshoot traps | 4 (mind/*) |

The agent reasons "the charter says 2 source files; the journals are
just operational artifacts, not real deliverable" — but the soft
sentinel reads the literal diff and refuses to exit early. The result
is wasted phase-2 budget and an "incomplete deliverable" verdict on
work that actually shipped the intended source change.

## Decision

Extend the v3 auto-allow from `mind/research/*-remediation.md` to
**all** `mind/*` paths. The mind/ tree is operational state —
chronicle, heartbeat, inbox, session log, research notes, wiki —
none of it is source code under test. Admitting mind/* into a
charter-clean diff is faithful to the contract's intent: the
deliverable shipped cleanly under the charter's source-file scope.

Concretely, change the file-loop case in
`soak_phase2_deliverable_landed`:

```bash
# v3
case "$f" in
    mind/research/*-remediation.md) continue ;;
esac

# v4
case "$f" in
    mind/*) continue ;;  # operational journal artifacts, not deliverable
esac
```

Bump `soak_lib_version()` to v4 so post-mortems can correlate
behavior with library revision.

## Consequences

**Positive**:
- The soft sentinel fires on the *intent* of charter compliance
  (source files only) rather than the *literal* commit shape that
  the runner's own journaling pollutes.
- Phase-2 budget is no longer burned on iterations where the
  deliverable is in fact already landed.
- Operators can stop investing in charter rewordings that have not
  moved the needle in six attempts.

**Negative**:
- An agent that intentionally hides a malicious change under `mind/`
  would slip past the soft sentinel. This is acceptable because the
  whitelist is one defense layer of several — the witness panel,
  test gate, and trust scoring all still see the full diff. The
  soft sentinel exists for budget control, not security.
- The v3-era convention "the whitelist enforces every committed
  path" is now relaxed for the mind/ tree. Operators authoring new
  charters can stop enumerating journal files.

## Out of scope

- Retrofitting v17–v25 runners — those are historical artifacts.
- Extending auto-allow to `docs/`, `state/`, or other operational
  trees outside `mind/`. If a pattern emerges there, a follow-up ADR
  can broaden it; for now the change is minimal.
- Changing the agent's git-add behavior. Reducing journal-pollution
  at the source is a separate defense layer (model-side); this ADR
  is operator-side only.
- An env knob to disable v4 behavior. The auto-allow is
  unconditional for `mind/*` because every documented occurrence has
  been benign journaling.

## Tests

`tests/test_soak_watchdog.py` (extended):

- `test_mind_paths_are_auto_allowed[mind/CHRONICLE.md]`
- `test_mind_paths_are_auto_allowed[mind/HEARTBEAT.md]`
- `test_mind_paths_are_auto_allowed[mind/INBOX.md]`
- `test_mind_paths_are_auto_allowed[mind/SESSION_LOG.md]`
- `test_mind_paths_are_auto_allowed[mind/research/foo-design.md]`
- `test_mind_paths_are_auto_allowed[mind/research/foo-remediation.md]`
  — preserves the v3 path
- `test_non_whitelisted_source_still_blocks` — `chimera/core/escalation.py`
  outside whitelist still blocks
- `test_docs_outside_mind_still_blocks` — `docs/adr/0117-foo.md`
  still blocks (not under `mind/`)
- `test_whitelisted_files_only_still_landed` — v3 baseline preserved
- `test_soak_lib_version_is_v4` — version string carries v4 + mind/* marker

All v3 smoke tests (`test_watchdog_*`) continue to pass; the
behavior change is strictly more permissive for `mind/*` paths.
