# Model-tier re-evaluation — empirical audit (2026-06-01)

Triggered by the operator: re-evaluate the tiers; several model updates exist that
would enhance the tool portfolio. All findings below are LIVE-probed against the
configured providers (Anthropic direct + OpenRouter), not assumed.

## Headline: the "empty model" failures were a max_tokens bug, not broken models

Earlier work (critic escalator, ACT self-determination soaks) hit models returning
**empty text** and concluded the cheap OpenRouter rungs were broken. That was
wrong. Re-probing with an adequate budget:

| model | max_tokens=16 | max_tokens=2048 |
|---|---|---|
| deepseek/deepseek-v4-flash | EMPTY | **OK** |
| openai/gpt-5.1-codex-max | EMPTY | **OK** |
| openai/gpt-5-codex | EMPTY | **OK** |
| openai/gpt-5-nano | EMPTY | **OK** |
| openai/o4-mini | EMPTY | **OK** |
| google/gemini-3.1-pro-preview-customtools | EMPTY | **OK** |

**Root cause:** reasoning-heavy models consume their token budget on internal
reasoning before emitting visible output; with a tiny `max_tokens` they return
empty. The ACT loop / critic call-sites use small budgets, so reasoning rungs
look broken. The fix is a token-budget floor for reasoning rungs (and using
`reasoning_optimized` to size it), NOT swapping the models out.

## Configured models — live status (Anthropic all reliable)

- claude-haiku-4-5 / sonnet-4-6 / opus-4-7 (Anthropic direct): **all OK**.
- deepseek-v4-pro (sonnet/opus rung-0): FLAKY at low tokens, OK with budget.
- `google/gemini-3-pro` (opus rung): **INVALID — 400, not a valid OpenRouter ID.**
- `openai/gpt-5-pro` (opus rung): the most EXPENSIVE gpt-5 ($15/$120); superseded.
- qwen rungs: OK.

## Catalog is stale — notable updates available (OpenRouter, live)

- **Anthropic:** `claude-opus-4.8` ($5/$25, **1M ctx**) supersedes 4.7; `claude-sonnet-4.6`
  now **1M ctx** ($3/$15); `-fast` opus variants exist.
- **OpenAI:** whole gpt-5.x line — `gpt-5.4` ($2.50/$15, 1M ctx), `gpt-5.1-codex-max`
  & `gpt-5-codex` ($1.25/$10, **code-specialized**), cheap `gpt-5-nano` ($0.05/$0.40),
  reasoning `o3`/`o4-mini`.
- **Google:** `gemini-3-pro` is gone → `gemini-3.1-pro-preview`, **`gemini-3.1-pro-preview-customtools`**
  (tool-call optimized, 1M ctx, $2/$12), `gemini-3.5-flash`.
- **Cheap reliable workhorses:** `qwen3-235b-a22b-2507` ($0.07/$0.10), `gpt-5-nano`.

## Tool-portfolio enhancers (the operator's point)

1. **Code-specialized ACT model** — `gpt-5.1-codex-max` / `gpt-5-codex` for the
   autonomous build loop (Chimera's core job). Confirmed working.
2. **Tool-optimized Gemini** — `gemini-3.1-pro-preview-customtools` for tool-heavy
   phases.
3. **1M-context Claude** (sonnet-4.6 / opus-4.8) for large-diff review / long context.
4. **Cheap reliable floor** — qwen3-235b-a22b-2507 / gpt-5-nano to replace the
   "broken" perception of the cheap rungs.

## Two distinct workstreams

A. **max_tokens floor for reasoning rungs** (the real unblock — makes the existing
   ladder actually work; directly fixes ACT/critic/soak stalls).
B. **Catalog refresh** — fix the invalid `gemini-3-pro`, retire the most-expensive
   `gpt-5-pro`, add opus-4.8 / sonnet-4.6-1M / codex / customtools / cheap workhorse,
   and re-map roles. Cost-affecting → operator sign-off on choices.

## Implemented (chip/model-tier-refresh)

Per operator decision ("Both" + a diverse ACT spread). Full suite green (2053).

- **Anthropic mirror IDs fixed** → `anthropic/claude-haiku-4.5` / `-sonnet-4.6` /
  `-opus-4.7` (the invalid date-suffix TODO resolved).
- **OpenRouter ladders rebuilt** (all live-verified tool-capable):
  - `haiku`: gpt-5-nano → qwen3-235b-a22b-2507 → claude-haiku (cheap reliable floor).
  - `sonnet` = **the ACT spread**: deepseek-v4-pro → minimax-m3 → glm-5.1 →
    qwen3.7-max → mistral-medium-3-5 → gemini-3.1-pro-preview → claude-sonnet (safety net).
  - `opus` = specialists: deepseek-v4-pro → **gpt-5.1-codex-max** (code) →
    **gemini-3.1-pro-preview-customtools** (tools) → claude-opus (safety net).
- **Retired** the broken/stale rungs: gemini-3-pro (invalid), gpt-5-pro (priciest,
  superseded), deepseek-v4-flash / qwen3.6-flash / qwen3.5-plus.
- **Downstream refs updated**: witness/cross-critique trio →
  (claude-opus-4-7, gpt-5.1-codex-max, gemini-3.1-pro-preview) — three vendors;
  witness_panel gpt-5-pro member → gpt-5.1-codex-max; cost_estimate tests recomputed.

### Deferred (next chip)
- **max_tokens floor for reasoning rungs** — the codex/gemini-customtools/o-series
  rungs need adequate output budget or they emit empty. ACT's per-tier defaults
  (8k sonnet) are OK, but low-budget callers (critic 1024-token escalator) should
  raise the floor when the rung is reasoning_optimized. (Workstream A.)
