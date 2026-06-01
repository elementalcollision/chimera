# Step 1 — self-select-and-build: findings (2026-06-01)

**Harness**: `scripts/self_determined_soak.sh` (self_scan auto-picks the agent's
top-ranked candidate → real_task_soak with `CHIMERA_CRITIC_ENFORCE=1`, fallback
OFF). Two runs. Both manual-handoff; worktrees pruned.

## What worked

- **Self-selection (origination) works.** `self_scan` ranks 77 real,
  behaviour-neutral maintenance candidates; the harness auto-picks from the
  agent's own ranking with no human choosing the task. Run 1 picked its #1
  (`fix 14 ruff findings in chimera/cli.py`, score 1.00); run 2 picked a
  tractable lower rank (`1 ruff finding in chimera/_async_loop.py`, 77 lines).

## What did not — and the diagnosis

Neither run produced a committed result; the gate never fired (no commit reached
it).

- **Run 1 (cli.py, 14 findings, 3600 lines):** ACT hit `max_rounds` (rounds 12→18,
  ~21 tool calls) without converging; 0/3 tasks completed; ~$0.19 spent; no commit.
- **Run 2 (_async_loop.py, 1 finding, 77 lines):** SAME stall — ACT ran a full
  600s cycle, rounds=12, ~14 tool calls, 0/2 completed; **$0.02 spent**; no commit.

Run 2 is the key data point: even a **1-finding, 77-line** task stalled, so this
is **not** a tractability/file-size problem. The agent *is* acting (12 rounds,
14 tool calls) but not reaching a green "done" state within the round budget,
and the **$0.02 spend over 600s** is the signature of a weak/cheap ACT model.

**Root cause — ACT model quality in this env's ladder config.** ACT selects its
model via `select_rung(tier, prefer_cheapest=True)`, which walks the tier ladder
cheapest-first → an OpenRouter rung (`deepseek-v4-flash`/`-pro`). Direct probes
during the ADR 0162 work showed these rungs return **empty text** in this
environment. Such a model can complete a *trivial, test-anchored* fix — the
earlier `validation_enforcement_soak` (`percent()` with a pinned test) **passed**
and committed — but cannot converge on a **test-less "make `ruff` clean"** target,
where there is no crisp checkable "done" signal to anchor it.

So the bottleneck is the **combination** of (a) a weak/cheap ACT model and (b) a
test-less acceptance target. Origination and the enforcement gate are both
already validated; ACT execution is the limiting factor here.

## Implications / options (operator decision)

1. **Reconfigure the ACT ladder to use a capable, reliable model** (Anthropic
   `claude-sonnet-4-6`/`opus-4-7`, as the critic gate now does) for self-directed
   builds. Highest-leverage; has cost implications. The cheap-OpenRouter rungs are
   unreliable (empty) in this env regardless of task.
2. **Target TEST-BACKED self-selected tasks** (a crisp acceptance signal), playing
   to the proven strength (`percent()`), rather than ruff/lint debt.
3. **Add a tractability + test-backed signal to `self_scan` ranking** so the
   agent's #1 pick is something it can actually finish (origination-precision
   improvement — feeds Step 2).

Recommendation: **(1) + (2)** — give the self-directed loop a capable ACT model
AND test-anchored targets; then re-run Step 1 for a clean signal before scaling to
the Step-2 origination-precision batch.

## Honest ledger

Self-determination is demonstrated at the **origination** layer (the agent picks
real work) and the **enforcement** layer (the gate, proven separately), but the
**end-to-end self-directed BUILD** is not yet demonstrated on test-less tasks in
this config — ACT cannot converge. No result was fabricated; the failed runs are
recorded here. Nothing reached `main`.

## Update (post model-tier refresh, 2026-06-01 PM) — the REAL bottleneck

After the model-tier refresh (#236) + the harness tweak (default to the ACT
spread, no force-pin), a re-run on a tractable, TEST-ANCHORED self-pick
(`chimera/server/kfm_tool.py`, 2 ruff findings, `tests/test_kfm_tool.py`) finally
surfaced the actual blocker in the runner log:

```
tool dispatch failed: shell
PermissionError: command 'bash' not in shell allow-list
  (allow-list: awk cat comm date diff du echo file find git grep head ls mkdir
   pwd python3 sed sort stat tail test uniq uv wc which — NO bash/sh)
```

**The build loop stalls because the agent reaches for `bash`/`sh` to run commands,
and the shell allow-list blocks it** — it burns ACT rounds on blocked dispatches
(consistent with the earlier $0.02/600s, 0-completed stalls). The first cli.py run
hit the identical thing with `sh`. This reproduces across different models and
tasks, so it is NOT model identity, NOT token starvation, NOT file size. The
`percent()` soak passed precisely because that fix was edit-based + `uv run`,
never tempting a shell wrapper.

**Determination on Workstream A (max_tokens floor): NOT the fix.** ACT already
budgets 8192 tokens (sonnet tier) — far above the starvation threshold — and the
critic runs on non-reasoning Claude. Token starvation was a red herring for the
ACT loop. Workstream A is at most a low-priority *preventive* floor for future
low-budget callers; it does not unblock self-determined builds.

**The real fix direction (next):** the `bash`/`sh` allow-list mismatch. Options:
1. Prompt/guide the agent to use allowed binaries directly (`uv run ruff …`,
   `sed`, …) rather than wrapping in `bash -c`.
2. Allow `bash`/`sh` for the soak ACT under the existing scope/critic guards
   (weakens the allow-list — needs care).
3. Prefer edit-based self-selected tasks (the proven `percent()` shape) over
   shell-heavy ruff cleanups.

**Soak-infra caveat:** some background-launched soaks also die in early setup in
this detached environment; the validation is more reliable run interactively.
