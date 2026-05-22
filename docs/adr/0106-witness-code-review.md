# ADR 0106 — Witness review for foundational code changes

**Status**: Accepted (2026-05-22, v4.102)
**Supersedes**: —
**Superseded by**: —
**Related**: ADR 0105 (syntax_invalid detection), ADR 0031 (multi-witness skill critique), ADR 0107 (cross-provider witness panel — extends this with a panel)

## Context

Across 10 soaks, every agent commit to `chimera/*.py` has shipped with zero second-model review of the diff. The runtime accumulates structural and convention defects that pass the per-detector gates we shipped between v4.79 and v4.101 yet still degrade the codebase.

Two specific failures motivate this ADR:

- **Soak v9** (`/Users/dave/chimera-soak-v9-2026-05-22-1554`, agent commit `3c5a205`): the agent flipped a `mind/INBOX.md` checkbox `[ ] → [x]` and shipped an untested edit to `chimera/core/act.py`. `inbox_claim_invalid` (v4.100) and `fix_without_test` (v4.90) catch parts of this, but neither READ the diff. A model that did would have noticed the test gap before commit.
- **Soak v10** (`/Users/dave/chimera-soak-v10-2026-05-22-1731`, snapshot `/tmp/v10-broken-act.py`): the agent wrote a dangling `return ActResult(` block, interrupted by a dedented `verdict = detect_degenerate_loop(...)` statement, into `chimera/core/act.py:1524`. The file failed to import; the runner spun on identical `SyntaxError` tracebacks for 13 minutes before the operator killed it. v4.101's `syntax_invalid` (`py_compile`) catches v10 specifically. But the more general class — code that PARSES but is structurally wrong — has no detector.

The existing `chimera/skills/cross_critique.py` (ADR 0031) is a multi-witness pool for skill assembly. It's tightly coupled to `SkillSpec` / `AssembledSkill` / `ValidationResult` and is not reusable as a general code-review primitive — see "Decision" below.

## Decision

Add a witness-review layer that fires at ACT completion AND at PR submission, on writes to foundational code only.

### Scope

- **In**: `chimera/*.py` and `tests/*.py`
- **Excluded**: `chimera/_version.py`, `chimera/__init__.py` (mechanical edits)
- **Out**: `mind/`, `state/`, `docs/`, `scripts/`, `proposals/` (the planner already proposes there; witnessing every prose write is noise)

### Pipeline placement (after v4.102)

1. `artifact_missing`
2. `artifact_incomplete`
3. `scope_evasion`
4. `ungrounded_citation`
5. `syntax_invalid` (v4.101) — parse-time
6. **`witness_rejected` (v4.102) — semantic-read time**
7. `fix_without_test`
8. (post-task) `phase_fix_without_test`, `inbox_claim_invalid`

Order: cheapest detectors first. `syntax_invalid` is a sub-second subprocess; `witness_rejected` is a 1-3s provider call. Both run only on the clean-stop completion path. We gate witnessing on `should_witness(write_targets) != []` so a non-code task never pays the witness cost.

### Module decision: new, not reused

`chimera/skills/cross_critique.py` is rejected as a reuse target:

- Its inputs are `SkillSpec` + `AssembledSkill` + `ValidationResult`. Adapting those for a code-diff is a larger surface than writing a focused helper.
- Its output is a "winning revision" selected across a pool. Witness review on foundational code wants a single verdict, not a winner.
- Its prompt assumes skill-shaped output (assembled triples, validation scores). Code review's prompt is structurally different.

Instead, `chimera/core/witness.py` ships as a focused module: `should_witness()`, `capture_diff_for_witness()`, `parse_verdict()`, `witness_code_change()`, `WitnessVerdict`. The cross-provider PANEL variant lives separately as ADR 0107 / v4.103.

### Tier default: sonnet

| Tier | Per-call cost | Soak impact (4 witnessings) | Defect catch rate (manual replay) |
|------|--------------:|---------------------------:|----------------------------------:|
| haiku | ~$0.003 | ~$0.012 | missed v9 untested-edit signal; missed v10 dangling-return |
| **sonnet** | **~$0.01-0.05** | **~$0.04-0.20** | caught both v9 and v10 in dry-run |
| opus | ~$0.10-0.20 | ~$0.40-0.80 | same as sonnet on these two cases |

Sonnet is the right floor. Opus per-touch cost is hard to justify at the 2-5 witnessings/soak we observe, given sonnet caught both motivating cases in dry-run.

### Trust + escalation wiring

- `finish_reason = "witness_rejected"` joins `ESCALATING_FINISH_REASONS` so the three-strikes auto-skip applies.
- Trust delta = **0** (same bucket as `ungrounded_citation` — recoverable draft-quality signal). Draining trust per touch would punish a normal review cycle; three-strikes handles repeat offenders.
- Remediation hint (`_witness_rejected_hint`) inlines the witness's top three concerns so the model knows exactly what to address.

### Cost envelope

Worst case at sonnet tier: 5 foundational writes × $0.05/call = **$0.25/soak**. The soak budget is already $5-10; this is <5% impact. Off-switch via `CHIMERA_WITNESS_ENABLED=0` for budget-constrained debug runs.

### Defense in depth: ACT-time + PR-time

- **ACT-time** (per-task) catches the issue when the model can still act on the hint inside the same task budget. Most defects die here.
- **PR-time** (cumulative branch diff vs `main`) catches the cross-task accumulation case where no single task tripped the witness but the branch as a whole drifted. Mirrors the relationship between v4.92 (per-task) and v4.99 (phase-scope) `fix_without_test`.

## Configuration

- `CHIMERA_WITNESS_ENABLED=1` (default on)
- `CHIMERA_WITNESS_TIER=sonnet` (haiku / sonnet / opus)
- Soak runner sets both; debuggable disable for cost-constrained runs.

## Non-goals

- **NOT** a replacement for operator review. The operator still reads the PR.
- **NOT** wired into every tool call — only completion + foundational writes.
- **NOT** a blocker for retries. The agent can address concerns and resubmit; this is a soft gate routed through the same remediation path as every other detector.
- **NOT** witnessing `mind/` writes — too noisy at planner velocity.

## Reference fixtures

- Soak v9 broken commit: `/Users/dave/chimera-soak-v9-2026-05-22-1554`, commit `3c5a205`
- Soak v10 broken file: `/Users/dave/chimera-soak-v10-2026-05-22-1731`, also `/tmp/v10-broken-act.py`

## Follow-ups

- ADR 0107 / v4.103: extend the single-witness call into a cross-provider PANEL (Anthropic + OpenAI + Gemini) for foundational changes where divergent providers materially improve catch rate. Tracked separately so v4.102 lands narrow.
