# ADR 0149 — Write targets are write DESTINATIONS, not paths named in content

**Status**: Proposed (2026-05-30). Flip to Accepted after the next phase-1
build+postmortem soak shows the postmortem task completing without
`witness_rejected`.

## Context

Across the v46 re-soaks, **phase 1 repeatedly ended `no_forward_progress`**:
the agent built `chimera/soak_report.py` and greened the gated test (the build
task completed), but the *postmortem* task drew `witness_rejected` again and
again (rounds 9–18, tools 14–33) until it `skipped_three_strikes` and phase 1
stalled.

A postmortem is a `mind/research/*.md` doc. `should_witness`
(`chimera/core/witness.py`) only selects `.py` files under `chimera/`/`tests/` —
a `.md` cannot trigger the witness directly. So for the postmortem *task* to be
witnessed at all, its `write_targets` had to contain a `.py`. It did, and the
path was a **false positive**:

- The only registered writing tool is `code_exec`; the agent writes files by
  running Python like
  `Path('mind/research/v46-soakreport-postmortem.md').write_text("""# Postmortem … built chimera/soak_report.py …""")`.
- `extract_write_targets_from_calls` stringified **all** the call's args
  (destination *and* the prose content) and ran `extract_target_paths`, whose
  regex matches any path-shaped token with a known extension — including
  `chimera/soak_report.py` **named in the postmortem prose**.
- That scraped path entered `write_targets`; `should_witness` returned it; the
  witness panel read the (unrelated, already-built) module's diff against the
  **postmortem** task's charter, found a code change that has nothing to do with
  "write the postmortem", and rejected on a charter-anchoring concern
  (asymmetric voting, ADR 0107/#174: charter concerns reject on any dissent).

So the witness was doing its job — it was handed the wrong file. The root cause
is `write_targets` conflating "paths the content mentions" with "paths the agent
wrote", the same misnaming the v4.92 shell-read fix (ADR 0099 lineage) partially
addressed.

## Decision

In `extract_write_targets_from_calls`, extract write targets from **write
destinations**, not arbitrary content. A new `_code_write_destinations(blob)`
matches the write idioms of the lone writing tool (`code_exec`):

- `open('p', 'w'|'a'|'x'…)`
- `Path('p').write_text(…)` / `.write_bytes(…)`
- `Path('p').open('w'…)`

When at least one idiom is found, only those destinations become write targets —
paths merely *mentioned* in the content (a postmortem documenting
`chimera/soak_report.py`) are ignored. When **no** idiom is found, we
conservatively fall back to the legacy whole-blob scrape, so `write_targets`
stays populated for exotic write styles that other gates (and the postmortem-
honesty git fallback) depend on.

### Conservative / no-regression (locked constraint)

- The build task's real write
  (`Path('chimera/soak_report.py').write_text(…)`) still yields the module as a
  write target → `should_witness` still reviews genuine code. The fix **narrows
  scope**, it does not stop witnessing real code.
- Shell reads were already excluded (shell is not a writing tool); this is
  unchanged.
- The fallback means a regression is impossible for any call the legacy scrape
  handled — at worst we match the old behavior; at best we drop the false path.

## Consequences

### Pros

- Closes the phase-1 `witness_rejected` → `no_forward_progress` stall: the
  postmortem task no longer drags an unrelated module before the panel.
- Fixes a real correctness bug in `write_targets` semantics that several gates
  read (`should_witness`, `syntax_invalid`, `import_shadowing`,
  `fix_without_test`) — a documented-but-unwritten path could previously
  mis-trip any of them.
- Cheap, local, and covered: no change to the witness panel, the voting policy,
  or any other gate.

### Cons / honest disclosures

- **Idiom coverage is finite.** A write via an unrecognized idiom (a custom
  helper, `shutil`, `os.write`) falls back to the legacy scrape and could still
  over-scrape. Acceptable: the dominant idioms (`open`, `write_text`) cover the
  observed cases, and the fallback never regresses.
- **Does not touch the asymmetric voting** (ADR 0107/#174). That policy is
  correct for genuine code; the bug was the *input*, not the vote. A future
  refinement could also make `should_witness` task-aware (skip witnessing when
  the task's primary deliverable is a doc), but that is broader and unneeded
  once the input is correct.

## Test coverage

`tests/test_act_completeness.py` (+4): a postmortem-write whose prose names
`chimera/soak_report.py` + `tests/test_soak_report.py` yields `write_targets ==
['…postmortem.md']` and `should_witness([]) == []`; `open('dest','w').write('…
chimera/core/act.py …')` yields only the dest; a real
`Path('chimera/soak_report.py').write_text(…)` is still a write target and still
witnessed; a no-idiom call falls back to the legacy scrape. All prior
`extract_write_targets_from_calls` tests (v4.92 shell-read, mixed read/write,
v7 end-to-end) still pass.

## References

- `mind/research/v46-resoak2-gate-fires-agent-still-wont-commit.md` — flagged
  the phase-1 postmortem `witness_rejected` as a secondary friction.
- [ADR 0106](./0106-witness-code-review.md) /
  [ADR 0107](./0107-cross-provider-witness-panel-for-code-review.md) —
  the witness panel this protects from bad input.
- [ADR 0099](./0099-fix-without-test-detection.md) — the v4.92 lineage that
  first corrected `write_targets` (shell reads); this extends the correction to
  content-scraping.
