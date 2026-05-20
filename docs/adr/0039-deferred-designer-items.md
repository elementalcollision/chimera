# ADR 0039 — Deferred designer items: view presets, auto-refresh, cost-over-time (v4.17)

**Status:** Accepted (2026-05-19)
**Builds on:** [ADR 0038](0038-mlc-canvas-design.md)

## Context

[ADR 0038](./0038-mlc-canvas-design.md) shipped the MLC canvas port and explicitly deferred three
items flagged by the designer in the hand-off chat:

1. **View presets** (Operator / Cost / Debug / Federation segmented
   control in the top bar).
2. **Auto-refresh** so the live state stays current without a
   manual reload.
3. **Cost-over-time line chart** alongside the per-model donut.

v4.17 closes all three.

## Decision

### View presets

- `WidgetDef` schema unchanged; presets live as a sibling prop on
  `CanvasShell`: `Record<string, ViewPreset>` where each preset has
  `label` + a `Record<widget-id, {x,y,w,h}>` layout map.
- Segmented control rendered in the top bar between the spacer and
  the action buttons (uses the existing `.topbar__presets` class
  from the design).
- Clicking a preset:
  1. Hides any widget not in the preset's layout map.
  2. Overrides the layout for visible widgets with the preset's
     coordinates.
  3. Persists the active preset name to
     `chimera-canvas-preset-v1`.
- "Reset canvas" clears the active preset and restores per-widget
  defaults.

Four presets defined in `app/page.tsx`, matching the designer's
prototype:

- **Operator** — Status + Cost top row; Drift + Phases; Inbox +
  Chronicle; Mutations strip. The everyday view.
- **Cost** — Cost donut and history dominate; Status sidebar; API
  calls; Phases + Fragmentation. For burn rate work.
- **Debug** — Status / Phases / Fragmentation row; Assembly +
  Graph; Mutations + API calls. For investigation.
- **Federation** — Peers + Trust; Emergence + Graph; Status strip
  bottom.

### Auto-refresh

- Toggle in the tweaks panel: "Auto-refresh every 30s".
- Off by default. State persisted to
  `chimera-canvas-autorefresh-v1`.
- When on, a top-bar "live" pill with the pulsing dot appears for
  feedback.
- Implementation: `setInterval(() => router.refresh(), 30_000)` in
  a `useEffect`. Uses Next's soft RSC refresh so the canvas layout
  doesn't flicker.

### Cost-over-time

- New `lib/cost-history.ts::costHistory(rows, hours=24)` buckets
  api_calls by hour (`created_at` ISO prefix to the `:00:00Z`),
  joins against `effectivePrices()` for $-per-hour totals, returns
  the newest N buckets.
- New `lib/db.ts::allApiCallCostHistoryRows()` returns `(model_id,
  input_tokens, output_tokens, created_at)`.
- New `CostOverTimeWidget` renders a serif total, peak-hour, last-
  hour summary plus a tall (64px) sparkline. No chart-lib bake-in;
  reuses the existing `Sparkline` primitive.
- Default placement: full-width below Status / Token cost; included
  in the Cost preset prominently.

## Non-goals

- **No per-second / sub-30s refresh.** Keep network + Provider
  rate-limits in mind; 30s is the floor we've validated.
- **No diff-only refresh.** `router.refresh()` re-renders the whole
  RSC tree. Per-widget incremental data fetch is a future pass.
- **No model-attributed cost-over-time stacked chart.** The hourly
  total is the headline; per-model breakdown can be a v4.18 toggle.
- **No preset editing in the UI.** Presets are code; ops change
  them in `app/page.tsx`.

## Tests

UI-shell additions only. Python suite unaffected (502 passing).
TypeScript clean (`npx tsc --noEmit`).

## Live verification

- Top bar segmented control renders Operator / Cost / Debug /
  Federation; clicking each immediately re-arranges the canvas and
  hides off-preset widgets.
- Tweaks panel: turning "Auto-refresh every 30s" on shows the live
  pill in the top bar; `router.refresh()` fires at 30s intervals.
- Cost-over-time widget: per-hour bucket sparkline with total /
  peak / last summary; falls back to "No cost history yet" when
  api_calls is empty.
