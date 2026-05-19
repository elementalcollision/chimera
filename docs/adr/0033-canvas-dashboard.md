# ADR 0033 — Canvas dashboard shell with draggable widgets (v4.11)

**Status:** Accepted (2026-05-19)

## Context

The dashboard had grown to ~13 stacked sections in a single linear
page. Operators wanted to arrange the view to their workflow, pin
always-on tiles, and reason about cost per model — none of which the
flat layout supports. The user spec was explicit: canvas-like,
drag-and-drop widgets, with token-cost as the worked example of
"quantizing" a function into widget form. Designed as a **shell**
that a separate design pass refines.

## Decision

### Library

`react-grid-layout` v1.5+ via `<Responsive>` + `WidthProvider`. It's
the well-known choice (~30 KB), supports static items, custom drag
handles, and breakpoints out of the box. MIT licensed.

### Architecture

- **`components/widgets/Widget.tsx`** — shared chrome: title bar
  with the `.widget-drag-handle` selector, body scroll, optional
  pin button.
- **`components/widgets/*.tsx`** — one component per data section.
  Each takes already-fetched data as props and is a pure pre-rendered
  server tree (Functions can't cross the server→client boundary in
  Next.js app router, so widget bodies are JSX nodes, not callbacks).
- **`components/CanvasShell.tsx`** — `"use client"` grid host.
  Reads/writes layout to `localStorage["chimera-canvas-layout-v1"]`
  and pinned state to `chimera-canvas-pinned-v1`. Drag handle is the
  header; resize handles are the grid library's defaults. Reset
  button restores the default layout.
- **`app/page.tsx`** — SSR fetches every datum once, then composes a
  `WidgetDef[]` (id, title, default layout, `body:` JSX) and hands
  them to `CanvasShell`. Old page archived at
  `app/page-legacy.tsx.bak`.

### Token-cost widget (the worked quantization example)

- New `lib/cost.ts` mirrors `chimera/providers/tiers.py` MODEL_TIERS
  prices.
- New `lib/db.ts::allApiCallTokenRows()` returns every successful
  api_calls row.
- `costByModel(rows)` aggregates per `model_id` → `{calls,
  inputTokens, outputTokens, inputCost, outputCost, totalCost}`.
- `TokenCostWidget` renders the table + grand total.

Every other widget follows the same shape: existing reader + small
pure component.

## Non-goals

- **Designer-class polish.** Spacing, colours, fonts, micro-
  interactions — refined separately via Claude designer. The shell
  is intentionally drab.
- **Per-widget settings.** A future pass adds an inline settings
  panel (refresh interval, row count, filter) per widget. Right now
  defaults are baked into props.
- **Widget marketplace / dynamic discovery.** All widgets are
  registered statically in `app/page.tsx`. A v4.12+ pass can move
  the registry to a config file or even add a "+ Add widget" menu.
- **Cost-price sync.** `lib/cost.ts` is hand-kept against
  `chimera/providers/tiers.py`. Drift is a real risk; a future
  `chimera tiers --json` exporter can autogenerate it.
- **No tests.** This is a UI shell; behaviour is observable in the
  browser and the existing Python suite is unaffected.

## How to extend (Claude designer notes)

1. Add a new widget: create `components/widgets/MyWidget.tsx`,
   accept already-fetched props, return JSX.
2. Add a reader to `lib/db.ts` or `lib/graph.ts` if you need new
   data.
3. Append `{ id, title, layout: {x,y,w,h}, body: <MyWidget … /> }`
   to the `widgets` array in `app/page.tsx`.
4. Operators see it on next page load; can drag it anywhere; layout
   persists per-browser in localStorage.

## Tests

UI shell — no automated tests added. Full Python suite still 496
passing (no Python touched).
