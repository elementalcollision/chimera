# ADR 0038 — Port Chimera Canvas design (MLC brand + 14 widgets) (v4.16)

**Status:** Accepted (2026-05-19)
**Hand-off source:** `claude.ai/design` chat — full transcript in the design bundle.

## Context

The v4.11 canvas shell was intentionally drab so a design pass could
own the aesthetic. The user generated a high-fidelity HTML/CSS/JSX
prototype at claude.ai/design ("Chimera Canvas") in the MLCommons
brand language and shipped a hand-off bundle for porting. v4.16
ports that visual layer into the existing Next.js control-plane.

The designer's own caveat in the chat transcript:

> Drag/drop is a custom impl for the design mock — the real port
> should still use react-grid-layout as the handoff doc requires;
> this is the visual layer to copy.

## Decision

Visual port; keep react-grid-layout as the canvas engine.

### Assets ported

- `control-plane/public/fonts/InstrumentSans-*.ttf` — variable
  Instrument Sans (wdth + wght axes).
- `control-plane/app/tokens.css` — MLC color palette, type scale,
  spacing, radius, elevation, motion, semantic tokens. `@import`
  removed (Turbopack rejects mid-file @import after @font-face);
  Instrument Serif now loaded via `<link>` in `layout.tsx`.
- `control-plane/app/canvas-styles.css` — `.app`, `.topbar`,
  `.sidebar`, `.tile`, `.pill`, `.bar-row`, `.kv`, `.ladder`,
  `.donut-row`, `.dag-node`, plus density modes and a complete
  slate-theme override.

### Components

- `components/viz/{Sparkline,Donut,BarRow,TierLadder,Icon}.tsx` —
  five primitives ported 1:1 from `viz.jsx`. Icon set is 22 Lucide
  glyphs.
- `components/widgets/StatusWidget.tsx` — readiness numeral, tier
  ladder, KV grid (cycle / status / drift), sparkline with lockdown
  baseline.
- `components/widgets/TokenCostWidget.tsx` — donut + per-model bar
  rows. Uses MLC palette tones.
- `components/widgets/SimpleWidgets.tsx` — Phase timings, Ontology,
  API calls, Mutations, Skill assembly (witness ladder with
  base→revised deltas), Skill graph (mini DAG), Peers, Trust
  journal, Emergence, Inbox (progress bar + checkable list),
  Chronicle (Morning / Midday / Evening tonal palette), Fragmentation
  log, Drift sparkline.

### Canvas chrome

`components/CanvasShell.tsx`:

- **Top bar**: brand (mint dot + serif wordmark), reset, theme
  cycle button, tweaks panel toggle.
- **Sidebar**: widget catalogue grouped by domain (Agent state,
  Cost & calls, Skills, Federation, Mind). Click an item to add or
  hide.
- **Canvas**: react-grid-layout with `.tile__header` as the drag
  handle so the design's chrome is the affordance.
- **Tweaks panel** (popover, top-right): three-way theme
  (System / Paper / Slate), density (Compact / Cozy / Roomy),
  show-catalogue toggle.

### Theme system

- Preference stored at `chimera-canvas-theme-v1`.
- Three-way: `system` follows `prefers-color-scheme`, `light` is
  paper, `slate` is the dark override.
- Resolved theme applied as `data-theme="light|slate"` on the root.
- Density applied as `data-density="compact|cozy|spacious"`.
- Slate-theme overrides for pills, ladder rungs, bar fills, DAG
  nodes, tile chrome, dot-grid background — all present in
  canvas-styles.css.

### Persistence

| Key | Stores |
|---|---|
| `chimera-canvas-layout-v3` | per-breakpoint grid layouts |
| `chimera-canvas-pinned-v3` | per-widget pinned (static) flag |
| `chimera-canvas-theme-v1` | theme pref |
| `chimera-canvas-density-v1` | density |
| `chimera-canvas-catalogue-v1` | sidebar visibility |

Keys bumped to `-v3` for layout to avoid loading the v3.9 shape.

## Non-goals

- **Auto-refresh.** The designer flagged this as a follow-up; not in
  this ADR.
- **Cost-over-time chart.** Same — follow-up.
- **View presets.** The designer prototype had Operator / Cost /
  Debug / Federation presets; ports cleanly later, dropped from v4.16
  to keep diff focused on the visual language and widget catalogue.
- **No automated tests.** Visual port. Existing Python suite (502)
  unaffected.

## Tests

`uv run pytest -q` — 502 passing (Python only). TypeScript
typecheck clean (`npx tsc --noEmit`). Live render verified at
http://127.0.0.1:3000 with both Paper and Slate themes.

## Live verification

- Brand wordmark with mint dot + "control plane" italic ✓
- Top-bar theme cycle button (layout / moon / sun) ✓
- Sidebar widget catalogue grouped into 5 sections ✓
- Tile chrome: eyebrow + title + optional chip + pin/x menu ✓
- Status widget: 44px serif readiness numeral, tier ladder, drift
  sparkline with lockdown dashed baseline ✓
- Token Cost: 120px donut + spend-by-model legend + per-model
  Calls bars ✓
- Slate theme tokenized across pills, ladder, bars, DAG, tile
  borders, dot-grid canvas background ✓
