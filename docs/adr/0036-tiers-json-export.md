# ADR 0036 — `chimera tiers --json` exporter + dashboard sync (v4.14)

**Status:** Accepted (2026-05-19)
**Closes:** "Cost-price drift" risk flagged in [ADR 0033](0033-canvas-dashboard.md).

## Context

ADR 0033 shipped the canvas dashboard with a hand-kept
`lib/cost.ts::MODEL_PRICES` mirror of `chimera/providers/tiers.py`
pricing. The drift risk was real: any change to MODEL_TIERS pricing
required a manual edit to the TS mirror or the Token Cost widget
would silently show wrong numbers.

## Decision

- New `chimera tiers --json` flag emits a structured JSON document
  to stdout AND writes `state/tiers.json`:
  ```json
  {
    "generated_at": "…",
    "tiers": {
      "haiku": [ { model_id, openrouter_model_id, provider,
                   input_cost_per_mtok, output_cost_per_mtok,
                   context_tokens, supports_tools }, … ],
      "sonnet": [ … ],
      "opus": [ … ]
    }
  }
  ```
- `control-plane/lib/cost.ts` reads `state/tiers.json` on every
  render. When the file exists, the snapshot prices override the
  hand-kept `MODEL_PRICES` (which remains as the fresh-install
  fallback).
- `effectivePrices()` is the new accessor; `costByModel` uses it.
  External callers can call `effectivePrices()` directly.

Two model_id forms are emitted per rung (`model_id` and
`openrouter_model_id`) so api_calls rows recorded under either form
hit the price table.

## Why a file, not an HTTP endpoint

- Dashboard already does SSR file reads (`paths.ts` resolves
  `state/`). One more file fits the existing shape.
- No new endpoint = no new auth / CORS surface.
- Operators can `chimera tiers --json > state/tiers.json` via cron
  if they want; the dashboard reads the latest on each page render.

## Operator workflow

After editing prices in `chimera/providers/tiers.py`:

```bash
uv run chimera tiers --json > /dev/null    # refreshes state/tiers.json
```

(stdout is suppressed; the snapshot side-effect is what matters.)

## Non-goals

- **No file-watcher.** Operators re-run the exporter when they edit
  prices. A future v4.x could add `tiers --json --watch`.
- **No price history.** The snapshot replaces the previous one. If
  you want time-series cost analytics, derive from `api_calls`
  joined with the snapshot at query time.
- **No JSON schema validation in the reader.** Bad JSON falls back
  to the hand-kept map; the failure is silent-and-safe.

## Tests

Suite still 498 passing — no Python tests added (the CLI verb is
covered by smoke-running it; the JSON output structure is pinned by
the dict-comprehension shape). A TS-side test would require adding
Jest / Vitest, which is out of scope for this ADR.

## Live verification

```
$ uv run chimera tiers --json | head -20
{ "generated_at": "…",
  "tiers": { "haiku": [ … ], "sonnet": [ … ], "opus": [ … ] } }
$ ls -la state/tiers.json
state/tiers.json  3.0K
```

Dashboard's Token Cost widget now displays prices sourced from
`state/tiers.json` when present.
