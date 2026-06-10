# ADR 0177 — act.py / cli.py façade extraction (pure moves)

**Status:** Accepted (2026-06-10)

## Context

The 2026-06-10 review measured the two monoliths: `chimera/core/act.py` at
3,351 lines with 50 top-level definitions (the `ActExecutor` plus ~35
guard/check functions accreted across the v4.82–v4.105 amendments), and
`chimera/cli.py` at 3,819 lines (a ~980-line `_build_parser()` plus ~10
command handlers and their helpers). Neither had a correctness problem;
both had a navigation and review-surface problem — every soak fix landed
in the same two files.

The binding constraint on any split: **dozens of tests monkeypatch names
on these modules** (`monkeypatch.setattr(act, "check_…")`,
`cli._single_string_arg_functions`, even `act_mod.subprocess.run`), and
several chimera modules import from them (`critic_gate` imports
`_function_docstrings` from `chimera.cli`; `loop`/`budget`/`submit_pr`/
`soak_ledger` import guard names from `chimera.core.act`). A naive move
breaks patches silently — the worst failure mode, because the patched
function keeps existing while the call site resolves the unpatched copy.

## Decision

Pure moves with the original modules retained as **façades**: bodies
relocate, names re-import, every external consumer and every monkeypatch
target keeps resolving on the original module, and the moved-out code is
still called through the façade's globals so patches stay effective.

### act.py → act_guards.py

- 64 symbols (35 guard/check/extract functions + 29 private regex/constant
  helpers) moved byte-verbatim to `chimera/core/act_guards.py`, grouped by
  section (scope-evasion / write-target / syntax & import-shadow /
  test-claim / commit-diff & provenance / artifact / inbox-claim).
- act.py keeps `ActResult`, `ActExecutor`, the executor-private helpers,
  and re-imports all 64 names (`# noqa: F401`).
- Deliberate exception: `check_postmortem_honesty` +
  `_run_spend_usd_best_effort` **stayed** in act.py — tests patch the
  helper on the act module and the guard calls it internally; had both
  moved, the patch would no-op silently.
- `import subprocess` is retained in act.py with a noqa: tests patch
  `act.subprocess.run`, making it part of the façade surface.
- Result: act.py 3,351 → 1,722 lines; act_guards.py 1,727.

### cli.py → cli_cmds/

- Seven handler modules under `chimera/cli_cmds/`: `peers`, `evals`,
  `verify`, `self_scan`, `critic_calibrate`, `charter` (+ `__init__`),
  moved verbatim except relative-import depth; heavy imports stay lazy
  inside functions so CLI startup cost is unchanged.
- Deliberately NOT moved: `_build_parser()`, `main()`, and the entire
  faithfulness/review cluster — `tests/test_cli_faithfulness.py` patches
  `cli._single_string_arg_functions` (and `cli.Path`), and
  `chimera/core/critic_gate.py` imports `_function_docstrings` from
  `chimera.cli`, so those call chains must keep resolving cli-module
  globals.
- cli.py remains a module (the `chimera = "chimera.cli:main"` entry point
  is untouched) and re-exports the 9 test-referenced handler names.
- Result: cli.py 3,819 → ~3,190 lines.

## Verification

- Full suite green on each branch pre-merge and on the merged branch
  (2,495 passed / 5 skipped / 1 xfailed) — including the ~30 test files
  that monkeypatch act/cli module attributes.
- `chimera --help` and all affected verb `--help` outputs byte-identical
  pre/post; `chimera tiers --json` smoke-passes.
- ruff clean post-merge (the pre-existing `Sequence` F821s that travelled
  with the guards were resolved by importing it in act_guards.py).
- Runtime check: all 81 original top-level names still resolve on
  `chimera.core.act`.

## Consequences

- act.py is halved; guards have a home with section structure; cli
  handlers are individually reviewable. New guards should land in
  act_guards.py (and be re-exported in act.py while consumers import from
  there); new CLI verbs should land as `cli_cmds/<verb>.py`.
- The façade re-import lists are now part of the public-surface contract:
  removing a re-export is a breaking change for tests and peers of the
  module, and should be treated like an API removal.
- `_build_parser()` (≈980 lines) remains the largest single block in the
  repo — splitting it requires restructuring, not moving, and is left for
  a future decision if it starts hurting.

## Falsification / revisit triggers

- If a moved guard ever needs to call a sibling that tests patch on the
  act module, route the call through `chimera.core.act` (the façade), not
  the local global — otherwise the patch no-ops (the
  `check_postmortem_honesty` precedent).
- If cli_cmds modules start importing each other, that's the signal the
  split boundary is wrong; re-draw it before the web forms.
