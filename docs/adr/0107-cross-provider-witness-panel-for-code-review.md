# ADR 0107 — Cross-provider witness panel for ACT code review (v4.103)

**Status:** Accepted (2026-05-22) — builds on ADR 0106 (v4.102)

## Context

Soak v10 (2026-05-22) shipped structurally broken Python from the
agent into `chimera/core/act.py` around line 1524 — an `ActResult(`
call opened, a dedented `verdict = detect_degenerate_loop(history)`
interrupted it, then keyword arguments continued inside the dangling
call. None of the 13 mechanical detectors caught it; the runner spun
13 minutes on identical `SyntaxError` tracebacks. v4.101 (ADR 0105)
added a mechanical `py_compile` check for that exact class of
failure. v4.102 (chip queued) adds a single same-provider witness
critique on foundational-code-touching tasks.

A single witness from the same provider as the agent has correlated
failure modes with the agent — same training data, same inductive
biases, same blind spots. [ADR 0031](./0031-multi-witness-critique.md)
established multi-witness panels for skill assembly; [ADR 0035](./0035-cross-provider-defaults.md)
established cross-provider defaults for those panels. v4.103 extends
the same pattern into v4.102's ACT code-review hook.

Reference fixtures:

- `/Users/dave/chimera-soak-v10-2026-05-22-1731` — uncommitted broken
  Python in `chimera/core/act.py` (~line 1524, also at
  `/tmp/v10-broken-act.py`). Integration test must replay this diff
  and assert UNANIMOUS rejection from a cross-provider panel.
- `/Users/dave/chimera-soak-v9-2026-05-22-1554` — commit `3c5a205`
  with a real but incomplete edit (`chimera/core/act.py` +15, no
  tests/). Panel review should flag the missing-test gap as a
  semantic concern even before v4.99's mechanical phase-scope check
  fires.

## Decision

### Replace v4.102's single witness with the existing panel API

Reuse `chimera/skills/cross_critique.py` and the cross-provider
defaults from ADR 0035 — do **not** build new panel-selection logic.
v4.103 is wiring, not architecture.

### Panel composition

- Panel size: 3 (configurable via `CHIMERA_WITNESS_PANEL_SIZE`,
  default 3, debugging allowance for 1).
- Provider diversity: at least 2 distinct providers across the
  panel; the agent's own provider can appear at most ONCE.
- Exact members resolved from `tiers.json` / the existing
  cross-provider-defaults config. Example: agent =
  Anthropic-sonnet → panel = {Anthropic-sonnet,
  OpenRouter:deepseek-v4-pro, OpenRouter:gpt-5-mini}.

### Voting rule

UNANIMOUS approve required. Single dissent → `witness_rejected`.
Stricter than v4.102's "single witness approves" and stricter than
skill-assembly's typical majority rule. Rationale: foundational code
is high blast radius — false-negative cost ≫ false-positive cost.
v4.93 trust delta at −0.5 keeps the agent able to recover from
spurious rejections.

Configurable via `CHIMERA_WITNESS_VOTING=unanimous` (default for
code review; `majority` is the v4.102 fallback if explicitly set).

### Token-budget awareness

Each witness has a context window. The wiring must:

- Prefer smaller-context witnesses on small diffs (cheap path).
- Escalate to larger-context witnesses (gpt-5 long-context,
  sonnet-200k) when diff is large.
- When diff exceeds ALL panel members' windows, decompose by file
  or by hunk and run per-chunk reviews; aggregate rejections OR
  aggregate approvals across chunks.
- **Never silently truncate the diff** — truncation masks the very
  issues the witness is supposed to catch.

### Concerns aggregation

Each rejecting witness produces concerns; aggregate by
similarity-dedupe and surface through the v4.84 remediation hint:

```
Your code change was rejected by witness review (2 of 3 witnesses):
  - [anthropic:sonnet] Dangling open-paren on line 1524; ActResult( is not closed
  - [openrouter:deepseek-v4-pro] Indentation discontinuity between line 1525 and 1526 suggests the inner block is incorrectly scoped

Read the file, address each concern specifically, and rewrite. Don't analyse — just fix.
```

### Pipeline order

```
on task completion check:
  1. artifact_missing
  2. artifact_incomplete
  3. scope_evasion
  4. ungrounded_citation
  5. syntax_invalid           (v4.101 — mechanical)
  6. witness_rejected         (v4.102 wiring + v4.103 panel)
  7. fix_without_test
  8. (post-task) phase_fix_without_test, inbox_claim_invalid
```

Witness gate fires only when `writes_touch_foundational_code(write_targets)`
returns true (chimera/ + tests/).

### Code

- `chimera/core/act.py` — replace v4.102's single-witness call with
  `build_witness_panel(...)` + `asyncio.gather`. Aggregate verdicts;
  unanimous gate.
- `chimera/skills/cross_critique.py` — reuse `build_witness_panel`,
  `review_code_change` review method (add if v4.102 didn't already).
- `chimera/core/remediation.py` — `_witness_rejected_hint`
  consumes aggregated concerns.

### Env / config

- `CHIMERA_WITNESS_PANEL_SIZE=3`
- `CHIMERA_WITNESS_REQUIRE_CROSS_PROVIDER=1` (soaks always 1)
- `CHIMERA_WITNESS_VOTING=unanimous`

### Cost calibration

3× witness cost vs. v4.102's single witness. Projection:
$0.01–0.05/call → $0.03–0.15/call. Soak budget impact <$1.00 across
a typical soak (well within $10 cap). Acceptable for the
failure-rate reduction.

## Tests

`tests/test_witness_panel.py`:

- Panel of 3 unanimous approve → no fire.
- 2/3 approve, 1 dissent → `witness_rejected` with that witness's
  concerns surfaced.
- Only 1 provider configured → log warning and degrade to
  single-provider panel with a soak-runner warning.
- Large diff exceeds smallest panel member's window → escalate or
  chunk; assert no silent truncation.
- v10 fixture (broken Python at `/tmp/v10-broken-act.py`): all 3
  witnesses (Anthropic, OpenRouter-A, OpenRouter-B) must flag it;
  if any approves, the test fails — that signals panel composition
  is too weak.

Full suite expectation: prior count + 5 new.

## Non-goals

- **Don't rebuild panel selection.** ADRs 0031 + 0035 +
  `cross_critique.py` already cover it.
- **Don't make voting configurable mid-soak.** Voting rule =
  unanimous for code review, period.
- **Don't witness-review every tool call.** Only completion-time,
  only writes under `chimera/` + `tests/`.
- **Don't witness-review witness rejections.** The v4.84 hint goes
  back to the original agent, not another witness round — no
  infinite recursion.

## Why this shape

The platform has reached the layer where the agent ships real
foundational code (v9 wiring, v10 attempted wiring). Single-witness
review is necessary but not sufficient — it's the same gradient
problem that motivated Reggio-style multi-witness in the first
place (ADR 0031). v4.13 made the call once for skill assembly;
v4.103 makes the same call for code review.

Operator framing: *"a secondary or tertiary model from a different
provider might have caught the malformed loop provided tokens are
correctly sized, etc."* — exactly this ADR.
