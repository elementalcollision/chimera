# TOOL_PREFILTER cost evidence (ADR 0184) — deterministic, offline (2026-06-19)

Using the new `prefilter_savings()` (PR #flag-soak-refinement) to measure
CHIMERA_TOOL_PREFILTER's actual lever — **tool-definition input tokens** (the
schemas sent to the model every ACT call), full vs pruned — across representative
tasks, at two toolset sizes. Key-free, no soak, no API; flag-independent.

The prefilter only prunes the `dynamic` + `mcp-*` toolsets; the `core` floor
(shell/web/code_exec/git_commit/mind_search) is never pruned, and a token-less
task gets the full catalog (safety floor).

## Results (tool-definition tokens per ACT call)

**CURRENT runtime** (core + 1 dynamic = 6 tools; NO MCP servers configured):

| task | full# | kept# | full_tok | saved_tok | save% |
|---|---|---|---|---|---|
| code / code-fix / search / finance / multistep | 6 | 5 | 1021 | 41 | 4% |
| narrow ("reverse a string") | 6 | 6 | 1021 | 0 | 0% |
| empty | 6 | 6 | 1021 | 0 | 0% |
| **mean** | | | | ~29 | **~3%** |

**GROWN runtime** (core + 24 dynamic/mcp = 29 tools — the regime the flag is for):

| task | full# | kept# | full_tok | saved_tok | save% |
|---|---|---|---|---|---|
| code: add helper+tests | 29 | 5 | 1961 | 981 | 50% |
| code-fix: failing pytest | 29 | 6 | 1961 | 938 | 48% |
| search: web docs | 29 | 13 | 1961 | 648 | 33% |
| finance: SEC filing | 29 | 10 | 1961 | 774 | 39% |
| narrow: reverse string | 29 | 6 | 1961 | 940 | 48% |
| multistep: design subsystem | 29 | 6 | 1961 | 942 | 48% |
| empty | 29 | 29 | 1961 | 0 | 0% |
| **mean** | | | | ~746 | **~38%** |

## Interpretation

1. **One-directional (cost-safe).** Pruning only *removes* tools, so ON is never
   costlier than OFF on tool-def tokens — the cost risk is zero by construction.
2. **Safety floor holds.** Empty/token-less tasks keep the full catalog (0%
   pruned); the core floor is never pruned. The agent can never be left without
   a path to progress.
3. **Scales with toolset size.** Negligible today (~3%, ~40 tok — there is almost
   nothing to prune without MCP servers), but ~38% mean (up to 50% on focused
   code tasks) once dynamic/MCP tools grow — exactly the ADR's anticipated regime.
4. **Caveat (scope).** This is the *tool-definition* token lever; total per-call
   input is also dominated by conversation history + file contents, so the
   whole-call cost reduction is smaller than 38%. But tool-def tokens ship on
   EVERY round, so absolute savings compound across an ACT cycle.

## Graduation read (ADR 0184)

The **cost side is settled and favorable**: ON is cost-neutral-or-better by
construction and safety-floored, with material savings as the toolset grows. The
remaining gate is **quality** — does the lexical router ever prune a tool the
task actually needed (→ gate regression)? That is what `scripts/flag_soak.sh`
(both-arm-green, multi-trial) measures, in a keyed scheduler-off window. Given
the cost evidence + the safety floor, graduation is low-risk; today it is nearly
a no-op (almost nothing to prune) that future-proofs the loop as the toolset
grows. Recommend: graduate on a clean both-pass quality soak (or accept the
floored low-risk argument), per operator call.
