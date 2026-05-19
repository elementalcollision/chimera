# ADR 0035 — Cross-provider witness defaults (v4.13)

**Status:** Accepted (2026-05-19)
**Builds on:** [ADR 0031](0031-multi-witness-critique.md), [ADR 0032](0032-named-rungs-assembly-journal.md)

## Context

v4.8 enabled cross-witness critique. v4.9 added per-rung
`resolve_rung("gpt-5-pro")` selection. But the default
`witnesses=("sonnet", "opus")` still routed both critics through the
tier-level resolver — which picks the cheapest rung — so in practice
both witnesses landed on Anthropic-or-OpenRouter cheap rungs and
"cross-witness" was thinner than the design promised.

The operator's autoresearch mandate is explicit: "call multiple
models to create, inspect, witness, and objectively critique".
Diversity is the point.

## Decision

Default `witnesses` changes from `("sonnet", "opus")` to:

```
("claude-opus-4-7", "gpt-5-pro", "gemini-3-pro")
```

Three witnesses, three providers (Anthropic, OpenAI, Google), all
flagship-class. Same `resolve_rung` path that v4.9 wired in;
operators can still override.

Updated in two places:

- `chimera/skills/ladder.py::assemble_with_escalation` default arg.
- `chimera/skills/cross_critique.py::cross_critique` default arg.

## Why these three specifically

- **`claude-opus-4-7`** — strongest baseline for code synthesis on
  evidence to date. Goes first.
- **`gpt-5-pro`** — OpenAI flagship via OpenRouter. Different
  reasoning shape; useful disagreement.
- **`gemini-3-pro`** — Google flagship; 2M-token context lets it
  hold the entire task history if needed.

Three rather than four because concurrency × cost grows fast and
the marginal information from a 4th model is usually small. If
operators want more, override the kwarg.

## Why not include DeepSeek

DeepSeek-V4-Pro is on `OPUS_LADDER` as the cost safety net; it's
fine as a fallback rung but its code-gen agreement with the three
above is high enough that adding it as a 4th witness rarely
disagrees usefully. Keep it on the ladder; drop it from witnesses.

## Non-goals

- **No automatic witness rotation.** Operators wanting "different
  three this run" just pass `witnesses=(...)` explicitly.
- **No outcome-weighted defaults.** A future v5 could read
  `ladder_outcomes` history and adapt the default witness pool by
  task type. Not in this ADR.
- **No cost-aware fallback.** If `gpt-5-pro` is unavailable in the
  operator's region, that rung's call fails and v3.5's retry
  machinery moves on — the other two witnesses still produce
  results.

## Tests

`tests/test_cross_critique.py::test_default_witnesses_span_three_providers`
introspects `assemble_with_escalation`'s default and asserts the
three named witnesses are present and span at least two distinct
providers (per `resolve_rung`).

Full suite: 498 passing.
