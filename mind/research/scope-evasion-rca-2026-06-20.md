# Foreign-run scope_evasion RCA — why foreign PRs didn't fire (2026-06-20)

**Resolution: the foreign-PR trust gate now reads the operator's STANDING trust
(`state_dir`), not the throwaway clone's per-run trust. The noisy per-run
`scope_evasion` demotion no longer blocks an otherwise-clean foreign PR.**

## Symptom

The B.4 self-clone dry run produced a green, committed change but the foreign-PR
submit was `SKIPPED — trust tier T3 < T4`. The operator's standing trust was T5.

## Root cause (multi-agent RCA + code/log verification)

1. **`scope_evasion` is general and noisy.** `check_scope_evasion`
   (`chimera/core/act_guards.py:195`) flags an intended path group only if no path
   in it appears in ANY tool-call arg AND the file isn't on disk. It fires on both
   self and foreign runs — verified: the successful 2026-06-20 0815 *self*-crawl
   also hit `scope_evasion` (on the `chimera faithfulness` task, which legitimately
   runs a verify command and doesn't edit the scope files), demoting to T3 and
   recovering. A verify-only task being scope-checked for "did you edit?" is a
   detector false-positive class (secondary finding; see below).
2. **The demotion hits the per-run (clone) trust.** Each `scope_evasion` demotes
   2 tiers (`chimera/trust/manager.py`). A foreign soak runs `chimera run` in the
   clone, which mutates the clone's COPY of the trust state (seeded from the
   operator's). That copy is discarded with the clone.
3. **The foreign-PR gate read that discarded copy.** `maybe_foreign_pr` defaulted
   its trust source to `repo_root/state` = the clone. So one noisy in-run ACT
   cycle dropped the gate's view to T3 < T4 and blocked the PR — even though the
   operator's standing trust (`uberagent/state`) was still T5.

## Fix

`maybe_foreign_pr` now defaults its trust source to **`state_dir/trust_state.json`**
(the operator's persistent state the soak/CLI pass via `--state-dir`), i.e. the
**standing** trust. This is safe by construction:

- The PR content is bounded independently of in-run behaviour: the foreign
  autocommit commits ONLY the allowlist (`git add -- $TASK_FILES`,
  `real_task_soak.sh`), so a PR can never carry scope-evaded files.
- The other gates still apply per-run: gate-pass (ruff/pytest), the ADR 0162
  critic-commit gate, the verify_cmd-review gate, and the first-5 per-PR approval.
- Per-run trust remains the **self-loop's learning signal** (the detector and
  demotion are unchanged) — it just is no longer the foreign-PR *decision*.

So the foreign-PR gate now asks "has this agent earned T4+ STANDING autonomy?"
(the right question) rather than "did this one clone run stay clean?" (already
covered by the gate/critic/review/approval gates).

## Secondary finding (follow-up, NOT fixed here)

`scope_evasion` false-fires on verify-only phase tasks (e.g. the `faithfulness`
task whose instruction is to RUN `chimera faithfulness`, not edit). This demotes
trust on the self-loop too (then recovers). It's non-blocking today but pollutes
the trust signal. A future fix could skip the scope check for non-edit tasks, or
distinguish read-only tool calls (`_WRITING_TOOL_NAMES` already exists for the
fix-without-test check). Deferred — it touches the live detector and isn't
gating anything now.
