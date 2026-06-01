# Landmark: enforced no-contract autonomy validated end-to-end in the live loop (2026-06-01)

A single race-free, fully-instrumented self-determined soak closed finding #2 AND
gave the first live demonstration of the critic gate's false-reject rescue path.

## The run

`self_determined_soak.sh`, `SELF_BASE=main`, `CHIMERA_CRITIC_ENFORCE=1`,
fallback OFF, refreshed ACT spread. The agent SELF-SELECTED its task (no human
chose it), built it, and the enforced gate adjudicated its own commit.

```
self-selected : fix the 3 ruff finding(s) in tests/test_locomo.py
committed     : yes (94dd699 [agent] fix the 3 ruff lint finding(s) in tests/test_locomo.py)
gate (ruff)   : PASS
gate invoked  : yes (1 enter)
RESULT        : PASS
```

`state/critic-gate-debug.jsonl` (the finding-#2 instrument):
```json
{"event": "enter", "enforce": true, "override": false}
```
`state/critic-gate-log.jsonl` (the decision):
```json
{"allowed": true, "source": "recomputed", "escalated": true,
 "approved": false, "escalation_approved": true, "escalation_parsed": true,
 "escalator_model": "claude-opus-4-7"}
```

## What it proves

1. **Finding #2 — RESOLVED.** The gate WAS invoked on the agent's autonomous
   commit (`enter`, `enforce:true`) and logged a decision. The earlier
   `char-run-1` empty gate-log was a pre-fix artifact (stale soak_lib via the
   relative-source bug + the racy `ls -t` collector + no instrument yet). With
   the harness fixed (#242) and the instrument in (#241), the gate demonstrably
   engages.

2. **First LIVE proof of reject-requires-confirmation (the false-reject rescue).**
   Primary critic `claude-sonnet-4-6` REJECTED (`approved:false`) — over-cautious
   on a behaviour-neutral ruff cleanup. The independent `claude-opus-4-7`
   escalator APPROVED (`escalation_approved:true`, `escalation_parsed:true`), the
   lone reject was OVERRULED → `allowed:true` → commit landed. This is the exact
   mechanism built in ADR 0162 (and feared inert when the OpenRouter escalator
   returned empty) — now demonstrated end-to-end with a real cross-model
   disagreement, on a refreshed, reliable escalator model.

3. **The full no-contract loop works:** self-select → build (self-correcting off
   `bash`→`uv run` via the shell-hint chain #238/#239) → ruff PASS → enforced
   gate (primary reject → opus rescue → approve) → gated self-commit lands.

4. **Soaking is now a reliable instrument** — the result is self-consistent,
   bound to its own worktree (`selfdet-…`), v6 heartbeats engaged, gate-invocation
   surfaced. The harness defects (#242) and instrument (#241) made this legible.

## Caveat / honesty
One favourable run. The escalator overruling the primary is the *false-reject*
direction (safe); the false-APPROVE direction stays gated by the 0%-calibration
invariant. Characterization across more runs (convergence variance, gate-decision
distribution) is the next step.
