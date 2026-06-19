# ADR 0184 — Graduate CHIMERA_TOOL_PREFILTER to default-ON

**Status:** Proposed (2026-06-18) — *evidence-gated; the Evidence section is a
placeholder until a keyed flag-OFF/ON soak runs.*

## Context

ADR 0179 built the graduation mechanism (`flag_enabled` honours the registry
`default`) and ADR 0180 flipped `CHIMERA_ENTROPY_SIGNALS`, explicitly naming
`TOOL_PREFILTER` / `COMPLEXITY_ROUTING` as the next rungs **gated on cost-delta
evidence**. The verdict engine for that evidence now exists:
`chimera cost-delta` (ADR 0183 follow-up) diffs two soak `api_calls` DBs into a
deterministic token/cost delta — so the gate is now a one-command measurement.

What ON does (`chimera/tools/tool_selection.py`, `tool_prefilter_enabled` /
`select_tool_schemas`, ADR 0165): before each ACT model call, prune the
advertised tool schemas to a relevance floor (always keep the core floor; add
lexically/availability-relevant dynamic + MCP tools). Fewer tool *definitions*
in the request → **fewer input tokens per ACT call** with no dispatch change.
This is a pure-cost lever: the expected delta is a token/cost *reduction*, with
gate-pass quality held at parity (the agent still reaches the tools it needs).

## Evidence (keyed flag-OFF/ON soak — TO BE FILLED)

Procedure (run in a keyed env, scheduler off to avoid concurrent soaks):

1. Run the same gate-visible CRAWL spec twice — `CHIMERA_TOOL_PREFILTER=0`
   (baseline) and `=1` (treatment) — preserving each run's `api_calls` DB.
2. `chimera cost-delta --baseline <off.db> --treatment <on.db>`.
3. Graduate **iff** treatment is cheaper (fewer input tokens / lower cost) AND
   both runs reach a green gate (parity quality — no completion regression).

> _Evidence: pending a VALID keyed run. Drop the `cost-delta` verdict + both
> gate results here, then move Status → Accepted._

> **First attempt 2026-06-19 — INCONCLUSIVE** (writeup:
> `mind/research/flag-soak-0184-first-attempt-2026-06-19.md`). Two confounds make
> the naive soak unusable as evidence: (1) the OFF arm *failed its gate* (n=1
> variance), so the arms did unequal work — a flag soak is only valid when **both
> arms reach a green gate** (use **multi-trial**, ≥3, median); (2) total-token
> cost-delta can't isolate this flag — TOOL_PREFILTER prunes *tool-definition*
> input tokens, which are dwarfed by conversation/file tokens on a real soak (ON
> even showed MORE total input tokens, purely from running more rounds). Before
> re-attempting: require both-arm gate-pass + multi-trial, and **measure
> tool-definition input tokens specifically** (instrument the prefilter to log
> pruned-schema token counts) rather than total cost.

> **Cost side SETTLED 2026-06-19** (deterministic, offline; writeup:
> `mind/research/prefilter-savings-0184-2026-06-19.md`). The instrumentation
> (`prefilter_savings`) measured the tool-definition-token lever directly across
> representative tasks: **one-directional** (pruning only removes tools — ON is
> never costlier than OFF), **safety-floored** (empty/token-less task → full
> catalog; core never pruned), and it **scales with toolset size**: ~3% in
> today's MCP-less self-soak (almost nothing to prune) → **~38% mean (up to 50%
> on focused code tasks)** at ~29 dynamic/mcp tools. So the cost gate is met and
> the cost risk is zero by construction. **Remaining for graduation: the QUALITY
> check only** — does the lexical router ever prune a tool the task needed
> (→ gate regression)? Measure with `scripts/flag_soak.sh` (both-arm-green,
> multi-trial) in a keyed scheduler-off window, OR accept the floored low-risk
> argument (today graduation is nearly a no-op that future-proofs the loop as
> the dynamic/MCP toolset grows).

## Decision (on evidence)

Flip the registry default: `CHIMERA_TOOL_PREFILTER` `None → "1"` in
`chimera/config.py`. Per the ADR 0179 contract, any explicit non-truthy value
(`0`/`false`/`off`/empty) still disables.

Test graduation pattern (mirrors ADR 0180):
- `tests/test_tool_selection.py`: change `test_flag_off_returns_full_catalog`
  (asserts default-off) to a default-ON assertion with the env unset; keep the
  explicit-disable parsing test.
- `tests/test_flag_graduation_0184_0185.py`: un-skip
  `test_tool_prefilter_default_on_after_graduation`.

## Consequences
- Every ACT call ships a pruned tool set by default → lower input-token cost
  loop-wide; opt-out via `CHIMERA_TOOL_PREFILTER=0`.
- The graduation ladder advances; `COMPLEXITY_ROUTING` (ADR 0185) is the pair.

## Falsification / revisit triggers
- If the cost-delta shows no meaningful token reduction, **do not graduate** —
  the flag isn't earning default-on.
- If prefilter prunes a tool the agent then needs (gate-pass regression vs
  baseline), widen the relevance floor before re-attempting; don't flip.
