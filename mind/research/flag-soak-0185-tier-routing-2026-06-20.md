# ADR 0185 (COMPLEXITY_ROUTING) — keyed tier-routing flag soak, 2026-06-20

**Verdict: FAVOURABLE for graduation — ON ~halves rounds and cuts total tokens
~37% at flat dollar cost, by skipping a doomed cheap-rung attempt. Operator
decision (per ADR 0185); n=2, cost direction is trial-dependent (see caveats).**

## Why the standard flag soak couldn't measure this

`flag_soak.sh` (and the whole A/B family: `ab_soak`, `ab_arena`) PINS the model
per arm (`CHIMERA_ACT_FORCE_MODEL`) to isolate a model-INDEPENDENT flag — correct
for TOOL_PREFILTER (0184). But COMPLEXITY_ROUTING's entire effect IS the tier the
router picks: `recommended_tier` is bypassed when a model is force-pinned, and it
also no-ops for tiers off the haiku→sonnet→opus axis (e.g. `code`). So a pinned
soak makes 0185 inert → both arms identical → inconclusive by construction (the
same confound class as the 0184 first attempt).

**Fix:** added a `FLAG_NO_FORCE_MODEL=1` tier-routing mode to `flag_soak.sh` —
runs UNPINNED, base tier `FLAG_BASE_TIER` (default haiku), so `recommended_tier`
routes each arm. The flag stays the only difference; the ROUTER, not a human,
picks each arm's tier. Default (pinned) path is byte-identical for 0184.

## Setup

- Probe: `mind/ab/complexity-probe.md` — goal *"Implement
  chimera.core.duration.parse_duration with descending-unit validation, then add
  the round-trip test cases"* trips `complexity_floor_tier` → **sonnet**
  (reasoning verb "implement" + multistep "then"). The implementation is the
  moderately-tricky `duration.py` parser (deterministic gate: ruff + the agent's
  own pytest over the two scoped files) so both arms can reach the same green gate.
- Command: `FLAG=CHIMERA_COMPLEXITY_ROUTING AB_SPEC=mind/ab/complexity-probe.md
  FLAG_NO_FORCE_MODEL=1 FLAG_BASE_TIER=haiku AB_TRIALS=2 bash scripts/flag_soak.sh`
- base pinned @ 9e9c35a; both-arm-gate=pass required per pair; scheduler off.

## What the router actually did (tier lift confirmed)

The ACT ladders are OpenRouter spreads (`chimera/providers/tiers.py`): the haiku
tier's operative rung is `openai/gpt-5-nano`, the sonnet tier's is
`deepseek/deepseek-v4-pro` (the Anthropic models are safety-net rungs only).

| pair | OFF (routing off, base=haiku)          | ON (routing on → sonnet floor) |
|------|----------------------------------------|--------------------------------|
| t1   | gpt-5-nano ×29 → **escalated** deepseek-v4-pro ×30 = **59 calls** | deepseek-v4-pro ×26 = **26 calls** |
| t2   | gpt-5-nano ×33 → deepseek-v4-pro ×12 = **45 calls** | deepseek-v4-pro ×30 = **30 calls** |

OFF started at the cheap rung (gpt-5-nano), **flailed on the single-binary shell
protocol** (`bash -c` PermissionErrors, observed live — the same struggle that
sank kimi in the 2026-06-15 arena), and escalated to deepseek via escalation
memory. ON started directly at deepseek (the floor-lifted tier), skipping the
gpt-5-nano attempts. This is exactly the doomed-cheap-rung avoidance 0185 targets.

## Result (median over 2 valid both-green pairs; delta = ON − OFF)

| metric        | trial 1        | trial 2        | **median**            |
|---------------|----------------|----------------|-----------------------|
| total tokens  | −298,341 (−53%) | −67,126 (−20%) | **−182,734 (−36.8%)** |
| cost (usd)    | −$0.0365 (−23%) | +$0.0500 (+70%) | **+$0.0068 (+23.5%)** |
| rounds(calls) | 59 → 26        | 45 → 30        | **52 → 28 (−24, −46%)** |
| gate          | pass / pass    | pass / pass    | parity (all green)    |

## Reading it (ADR 0185 criterion: cost read WITH rounds)

- **Rounds: large + consistent win.** ON ~halves the api_call count in BOTH
  trials (−46% median). Fewer wasted rounds = less wall-clock, less token thrash.
- **Total tokens: −37% median**, negative in BOTH trials.
- **Dollar cost: flat.** Median +$0.0068 is **under one cent**; t1 was −23%
  (gpt-5-nano was pure waste, so skipping it saved money), t2 was +70% on a tiny
  base ($0.07→$0.12 — gpt-5-nano made *some* progress in t2, so escalating early
  cost a bit more). The % is volatile only because absolute dollars are tiny.
- **Quality: parity** — all four arms reached gate=pass.

Per ADR 0185 ("a modest cost increase is acceptable iff it buys fewer failed
rounds / higher gate-pass"), this is a **favourable** result: a large, consistent
round/token reduction at parity gate quality and flat absolute cost. The
falsification trigger (cost up with NO round reduction) did NOT fire — even the
costlier trial cut rounds.

## Caveats / honesty

- **n=2.** The 0184 lesson is ≥3 trials for a stable median. The rounds/token
  signal is consistent at n=2; the cost *direction* is trial-dependent. A 3rd
  trial (AB_TRIALS=3) would firm the cost median before flipping a production
  default.
- **Cost is task-dependent by design.** On a task where the cheap rung can make
  progress, starting higher over-pays (t2). 0185's value is concentrated on tasks
  the cheap rung *can't* do (t1) — the floor is a bet that complex-WORDED tasks
  are those. The probe's lexical floor is a heuristic; mis-tuning would show as a
  systematic cost rise with no round gain (not seen here).

## Recommendation

Graduate-supporting evidence. Recommend EITHER (a) graduate 0185 now on the
strong, consistent rounds(−46%)+tokens(−37%) efficiency signal at flat cost, OR
(b) run AB_TRIALS=3 first to firm the cost median. Graduation flips
`CHIMERA_COMPLEXITY_ROUTING` None→"1" in `chimera/config.py` (operator-gated).
