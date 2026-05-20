# ADR 0086 — `chimera doctor` cost-caps check (v4.67)

**Status:** Accepted (2026-05-20)

## Context

`chimera doctor` is the preflight verb — "does this environment
work?" Pre-v4.67 it covered config (state/mind dirs, provider keys,
HTTP auth, env JSON shapes) but NOT operational state. After the
v4.53–v4.60 cost-discipline arc, "rolling-hour spend trajectory"
is operational state that operators want to know before kicking
off a long-horizon run.

The dashboard's cost-rate widget surfaces the same data, but the
dashboard isn't always running — `chimera doctor` is the headless,
SSH-friendly preflight.

## Decision

### `chimera/core/doctor.py` — new `_check_cost_caps(state_dir)`

Reports current 60-minute spend against the rolling-hour cap, plus
a one-line summary of all three caps (cycle / task / 60m). Returns:

- `ok`   — empty DB OR spend < 50% of cap
- `warn` — spend ≥ 50% but < 100% of cap (review trend)
- `warn` — spend ≥ cap (next cycle will trip)
- `warn` — cap explicitly disabled (`CHIMERA_ROLLING_HOUR_CAP_USD=0`)

**Never returns `error`.** A spend-over-cap state is operationally
expected — the caps trip ACT exits, not preflight failures. Treating
it as an `error` would cause `assert_no_errors` to refuse to start
the loop, which is the wrong remediation: the cap exists precisely
to let the loop run safely while expensive.

Wired into `run_checks()` alongside the other operational/config
checks. Visible in:

- `chimera doctor` CLI output
- `assert_no_errors` (called by `boot_config_validator` paths)

Sample text output:

```
chimera doctor:
  …
  [✓] cost_caps                60m spend $0.00 (0% of $20.00 cap); caps: cycle=$2.00 task=$5.00 60m=$20.00
  …
```

## Tests

`tests/test_doctor.py` — 6 new tests:

- Empty DB → ok with $0.00 message
- Spend < 50% of cap → ok
- Spend at ~75% of cap → warn
- Spend over cap → warn with `OVER` marker
- `CHIMERA_ROLLING_HOUR_CAP_USD=0` → warn ("disabled")
- Absurd spend → never returns `error` (status="warn" only)

Full suite after v4.67: 731 passing (was 725, +6 new).

## Non-goals

- **No new failure-mode for `assert_no_errors`.** The check is
  observational, not config-gating. Operators who want to refuse
  loop start on over-cap conditions can wire their own pre-cycle
  shell guard around `chimera cost --json | jq -e .band != "red"`.
- **No alarm-rate trip into the check.** The cost-rate widget
  (ADR 0073) already classifies green/amber/red on the 15-min
  rate. Duplicating that into doctor would be noise; doctor uses
  the 60-min window because that's the rolling-hour cap's window.
- **No per-task budget surfacing in doctor.** Per-task budgets are
  per-signature; doctor is a global preflight. The summary line
  reports the budget value as one of the three caps; actual
  per-task spend is at `chimera escalations summary` (hot
  signatures) or `chimera cost`.

## Why this shape

Why a doctor check and not a separate command? Because the
operator already runs `chimera doctor` before long-horizon runs as
a preflight ritual. Folding cost-state into the same call means
one command tells them "is this environment healthy AND has it
already started racking up spend." Two separate commands would
add friction without clarifying.

Why warn-not-error on cap-disabled? Because some operators
legitimately disable the cap (CI runs, sandbox networks). The
agent should tell them their cap is off without refusing to
start; the operator can decide.

Why the 50% threshold? Because rolling-window spend can fluctuate
quickly with one expensive cycle; warning at 50% gives the operator
half a window of slack to course-correct (one of the cap-runaway
patterns from 2026-05-19 was the operator missing the dashboard
trajectory for two hours straight). 50% is roughly "you have a
healthy buffer left but you should check what's burning."
