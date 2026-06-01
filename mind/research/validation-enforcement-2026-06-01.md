# Live validation — in-loop critic enforcement (ADR 0162 item 7)

**Date**: 2026-06-01. **Harness**: `scripts/validation_enforcement.sh`.
**Critic (primary)**: `claude-sonnet-4-6` (Anthropic) — the model the calibration
ledger actually measures.

## The falsifiable claim

With `CHIMERA_CRITIC_ENFORCE=1` and a clean calibration record, the in-loop
critic gate must **block** the canonical silent regression (the `isdigit`-dropped
`to_snake` that the green gate accepted in the first live soak) from being
committed, and **allow** a faithful fix.

## Method

A throwaway temp git repo (never touches the real tree): HEAD = the buggy
pre-fix `to_snake`; a clean calibration record on disk; then two cases driven
through the REAL gate (`check_commit_critic`) with the LIVE critic:

- **A** — stage the `islower()`-only change (drops the digit branch). Expect BLOCK.
- **B** — stage the `(islower() or isdigit())` change (matches the docstring).
  Expect ALLOW.

## Result — PASS

- **A: BLOCKED.** `claude-sonnet-4-6` REJECTED with the exact concern: *"the new
  condition only triggers on `s[i-1].islower()`, silently dropping the digit
  branch … explicitly called out in the docstring as intended behaviour."* The
  gate returned `allowed=False`; the commit would not land.
- **B: ALLOWED.** The critic APPROVED: *"aligns the implementation exactly with
  the documented intent … no behaviour described in the docstring is removed or
  regressed."* The gate returned `allowed=True`.

**The gate blocks the canonical silent regression and passes the faithful fix —
the first time the loop refuses its own commit.**

## What the run caught (the reason to run it)

The FIRST attempt FAILED — and surfaced a real defect: the gate's default
reviewer resolved via `select_rung("sonnet")` to OpenRouter `deepseek-v4-pro`,
**not** the `claude-sonnet-4-6` the calibration's 0%-false-approve was measured
on. That model returned **empty text**, so:

- case A's primary (sonnet tier) gave a real reject *once* but was inconsistent;
- case B's primary returned empty → fail-closed → a clean fix was wrongly
  rejected (a false-reject caused by an empty response, not a judgment).

**The calibration-gated-activation invariant was bound to the wrong model** — we
gated on a number measured for `claude-sonnet-4-6` while the gate actually ran a
different, empty-returning model. Fix: the gate's PRIMARY reviewer now pins the
Anthropic provider + `CALIBRATED_MODEL = claude-sonnet-4-6` (the same model
`chimera critic-calibrate --model` defaults to); the calibration record now
stores the model id. Re-run → PASS.

## Honest residual

The ESCALATOR (independent second opinion for a reject) still resolves to the
OpenRouter rung, which returns empty in this environment → fail-closed. That is
SAFE (a primary reject stands; never a false-approve) but means the
**false-reject *rescue* path is inert here** — a lone over-cautious reject is not
actually rescued until a working, genuinely-independent second model is wired.
The two validation cases don't exercise the rescue (A: primary rejects correctly;
B: primary approves), so the claim holds; but the reject-requires-confirmation
benefit is unrealised in this provider config. Follow-up: wire a reliable
cross-vendor escalator (and assert it returns parseable text before trusting a
rescue).

## Standing-rule note

`scripts/validation_enforcement.sh` is a reusable harness (like the other
`scripts/validation_*.sh`); it uses a temp repo and never pushes/PRs/merges or
touches a `validation/*` branch. This result record lives under `mind/research/`.
