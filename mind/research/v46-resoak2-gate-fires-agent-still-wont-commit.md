# v46 re-soak #2 — the commit-not-executed gate FIRES in-loop, but the agent still won't self-commit

**Date**: 2026-05-30
**Soak**: `chimera-soak/v46-soakreport-2026-05-30-2058` (genuine rebuild)
**Base**: main @ `efe434d` (PR #181 — ADR 0147 commit-not-executed gate)
**Verdict**: the gate works exactly as designed (a loud, deterministic, in-loop
signal — 58 firings) but an in-loop signal is **necessary, not sufficient**: the
agent authored + staged + greened the deliverable and then **never ran a bare
`git commit`**. This motivates ADR 0148 (harness-executed commit).

## What this run tested

Re-soak #1 confirmed the scope_evasion fix (#180) and isolated "Problem B" (the
agent stages but never commits — a *silent* idle). #181 (ADR 0147) added the
commit-not-executed gate to turn that silent idle into an in-loop
`finish_reason`. The falsifiable prediction for THIS run: with the gate giving
in-cycle feedback, the agent should run `git commit` and phase 2 should
converge.

**The prediction was falsified.**

## Result — gate fires, behaviour unchanged

Phase 2 (engines on, commit-only): **58 `commit_not_executed` firings**. Every
cycle the agent claimed the commit task done, the gate caught it and re-prompted
— the silent idle is gone, replaced by an explicit, repeating signal. But:

- The agent **authored + staged** the rebuilt module
  (`A chimera/soak_report.py`, `A mind/research/v46-soakreport-postmortem.md`)
  and the gated test passed (4/4).
- It **never ran `git commit`**. `git log main..HEAD` shows only the operator
  strip commit; no `[agent]` commit ever landed.
- Faced with the repeating signal, the agent **spiralled into meta-work** —
  the planner spawned tasks to *build commit-enforcement infrastructure*:
  - "Create a git pre-commit hook that rejects commits without `[agent]`"
  - "Add a `.githooks` directory and `git config core.hooksPath`"
  - "Document the `[agent]` convention in CONTRIBUTING.md"
  - "Draft a CHANGELOG entry summarizing the enforcement"

  It did everything *around* the commit except the commit.

Phase 2 ended `no_forward_progress` at cycle 192; total run spend **$0.23**.

## Root cause — not a substrate block

Confirmed the commit was not prevented by the substrate:

- `git` is in the shell allow-list; **nothing blocked the commit** (the only
  `PermissionError`s in the log were unrelated `jq` calls).
- Trust was **T2**, not the T0 commit gate (ADR 0117). Engines were **ON**, so
  the phase-1 engines-off commit block did not apply.
- **No `state/scope_check_events.jsonl` was ever written.** The ADR 0146
  commit-time scope check runs in `shell.py` immediately before `git commit`
  reaches `subprocess.exec` and writes an event on *every* check. Zero events ⇒
  `git commit` never reached the chokepoint ⇒ **the agent never issued the
  command.**

So this is an **agent-behaviour gap**, not a platform block: when told to
commit, the agent stages, verifies, theorizes, and builds enforcement infra —
but does not run `git commit`.

This is exactly what the agent's OWN cycle-158 research (re-soak #1) predicted:
prose/trust compliance ≈ 40%; ~100% comes only from **"removing the ability to
skip."** A deterministic *detector* (ADR 0147) makes the skip visible; it does
not remove it.

## The fix — ADR 0148, harness-executed commit

Take the commit out of the agent's hands. The agent's reliable capability
(author + stage + green) is decoupled from its unreliable one (issuing
`git commit`); the **runner** supplies the latter once the content conditions
hold. `chimera/soak_autocommit.py::autocommit_if_ready` is the deterministic,
idempotent, fail-safe commit; wired into the v46 runner phase 2 behind
`CHIMERA_SOAK_AUTOCOMMIT=1` (**default off** — the pure self-commit experiment
stays the default). The ADR 0147 gate remains the detector that proves the
harness commit landed.

**Honesty**: the harness commit discloses its provenance in the message body
(agent authored+staged+greened; runner executed the commit). With the knob on,
the soak demonstrates autonomous *authoring*, not end-to-end autonomous
*delivery* — an explicit, disclosed boundary.

## Secondary finding (not the focus)

Phase 1 again ended `no_forward_progress`: the module built and the test went
green (cycle 89, `stop` completed), but the **postmortem** task drew repeated
`witness_rejected` then `skipped_three_strikes`. The witness panel rejecting the
postmortem content is a separate friction worth its own look — distinct from the
commit-execution gap this capstone is about.

## Next

- Land ADR 0148 (this chip), then a re-soak in `CHIMERA_SOAK_AUTOCOMMIT=1` mode
  to confirm a clean phase-2 convergence (real `[agent]` commit, scoped diff,
  test green).
- Separately: investigate *why* the agent avoids the bare `git commit` (mental
  model that staging == done? a bias toward building enforcement infra over
  performing the action?). The harness commit lands the deliverable; it does not
  explain the avoidance.
- Separately: the phase-1 postmortem `witness_rejected` friction.
