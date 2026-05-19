# Chimera Dashboard — Designer Hand-off

**Audience:** Claude Designer (or another design pass) picking up the
v4.11 canvas shell. **Status of the shell:** functional, drab,
intentionally un-styled beyond Tailwind defaults. Drag, resize, pin,
persist all work. **What this doc is for:** what's invariant, what's
open, the data shapes you'll be designing against, and the commands
that exercise the system.

---

## Where things live

```
control-plane/
├── app/
│   ├── page.tsx              ← SSR-fetches everything, composes WidgetDef[]
│   ├── page-legacy.tsx.bak   ← v3.9 flat layout archive (reference only)
│   ├── layout.tsx            ← root layout
│   └── globals.css           ← Tailwind base; you may extend
├── components/
│   ├── CanvasShell.tsx       ← "use client" — react-grid-layout host
│   └── widgets/
│       ├── Widget.tsx        ← shared chrome (drag handle bar + body + pin button)
│       ├── StatusWidget.tsx
│       ├── TokenCostWidget.tsx
│       └── SimpleWidgets.tsx ← 10 small widgets in one file
└── lib/
    ├── cost.ts               ← MODEL_PRICES mirror + costByModel()
    ├── db.ts                 ← SQLite readers (better-sqlite3)
    ├── graph.ts              ← filesystem JSON/JSONL readers
    ├── mind.ts               ← HEARTBEAT / trust_state
    └── paths.ts              ← env-driven path resolution
```

Two ADRs to read first:

- [`docs/adr/0033-canvas-dashboard.md`](adr/0033-canvas-dashboard.md) — design + extension recipe.
- [`docs/adr/0025-v4-stability.md`](adr/0025-v4-stability.md) — which underlying surfaces the dashboard reads from are stable.

## Run it

Dashboard is normally already running at <http://127.0.0.1:3000>. If
not:

```bash
cd control-plane
CHIMERA_STATE_DIR=/Users/dave/uberagent/state \
CHIMERA_MIND_DIR=/Users/dave/uberagent/mind \
CHIMERA_PEER_REGISTRY_DIR=/Users/dave/.chimera/peers \
npm run dev -- --port 3000
```

Turbopack is enabled (`next dev --turbopack`). Hot-reloads on save.

To populate data while you work:

```bash
uv run chimera run                 # advance a cycle (engines off: CHIMERA_ENGINES_ENABLED=0)
uv run chimera graph rebuild       # refresh state/chimera.graph.snapshot.json
uv run chimera graph export
uv run chimera fragmentation       # show v4.5 fragmentation log
uv run chimera mutations list      # what's pending / applied / failed
uv run chimera tiers               # ladder rungs + per-rung costs
```

---

## Invariants — don't break these

1. **Server-component boundary.** `app/page.tsx` is the only place
   that does I/O. Widget bodies are **pre-rendered JSX** passed as
   `body:` props — not functions. Functions can't cross the
   server→client boundary in Next.js app router.
2. **Single-source SSR.** Every datum fetched once per page render.
   No client-side `fetch` calls. If a widget wants live updates,
   wrap it in a separate client component and add a periodic
   refresh; don't pull I/O into the canvas.
3. **`react-grid-layout` controls layout math.** Use `cols`,
   `breakpoints`, `rowHeight` from `CanvasShell.tsx`. Don't compute
   positions yourself.
4. **Drag handle selector is `.widget-drag-handle`.** It's on the
   `Widget` chrome's header bar. Anything else inside a widget body
   is interactive (won't trigger drag).
5. **Layout persistence keys are versioned.** `chimera-canvas-layout-v1`
   and `chimera-canvas-pinned-v1` in localStorage. If you change the
   layout schema, bump to `-v2` so existing users get a clean default.
6. **Pinning means `static: true`** in react-grid-layout. Pinned
   widgets ignore drag/resize/compaction. Default-pinned is set per
   widget via `defaultStatic`.
7. **All data is read-only.** The dashboard observes; the operator
   acts via the CLI (`chimera mutations approve`, etc.). Don't add
   mutation triggers without an explicit ADR — the v1.2 mutation
   queue is the canonical action surface.

## What's open for design — anything else

- Colour, typography, density, breakpoints, motion, dark/light mode
  refinement.
- Replacing the emoji pin button with a proper icon.
- Per-widget headers (status pill, last-updated, filter chips).
- Adding a sidebar / drawer for widget catalogue and "+ Add widget".
- Tooltips, empty-state illustrations, error states.
- Sparklines or trend indicators on cards (Status especially).
- A real cost-over-time chart in `TokenCostWidget` (you'll need a
  chart lib — recharts and visx are good fits for v19/Next 15).
- Responsive behaviour at `sm` and `xs` breakpoints (currently
  basic; widgets shrink to 6 / 4 cols respectively).

## Data shapes you'll be designing against

All shapes are TS-typed in `lib/db.ts`, `lib/graph.ts`, `lib/mind.ts`.
Brief tour:

| Source | Type | What's in it |
|---|---|---|
| `state/chimera.db` | SQLite | `entities`, `entity_transitions`, `api_calls`, `mutations`, `ladder_outcomes`, `agent_activity_log` |
| `state/phase_timings.json` | JSON | last cycle's per-phase wall-clock ms |
| `state/chimera.graph.snapshot.json` | JSON | LadybugDB projection: skills + dep edges, provenance edges |
| `state/skill_assembly_log.jsonl` | JSONL | one row per `chimera skills assemble`, with per-tier + per-witness attempt detail |
| `state/peer_trust_journal/*.jsonl` | JSONL | per-peer ALLOW/DEGRADE/REFUSE history |
| `state/protocol_journal/*.jsonl` | JSONL | emergence observations; `remote/<host>/*.jsonl` mirrors remote peers |
| `state/fragmentation_log.jsonl` | JSONL | v4.5 compound-task failure signatures |
| `~/.chimera/peers/*.json` | JSON | filesystem peer registry |
| `mind/HEARTBEAT.md` | YAML frontmatter | cycle, trust_tier, model_usage |
| `mind/INBOX.md` | markdown checklist | open / done tasks |
| `mind/CHRONICLE.md` | markdown narrative | append-only daily narrative |

The four canvas-relevant journals (assembly, trust, emergence,
fragmentation) are all append-only JSONL — safe to display
incrementally.

## Worked example: the Token Cost widget

`TokenCostWidget` is the spec's "quantize a function into widget
form" exemplar. The full pipeline:

1. `lib/db.ts::allApiCallTokenRows()` reads `(model_id, input_tokens,
   output_tokens)` from every successful `api_calls` row.
2. `lib/cost.ts::costByModel(rows)` joins each row against
   `MODEL_PRICES` and aggregates per model: `(calls, inputTokens,
   outputTokens, inputCost, outputCost, totalCost)`.
3. `lib/cost.ts::totalCost(buckets)` rolls up to a grand total.
4. `TokenCostWidget` renders the table + grand total.

Future "quantizable functions" worth widgetizing:

- **Latency budget** — average / p95 latency per model from
  `api_calls.latency_ms`, against a target SLO.
- **Skill cost** — for each dynamic skill in the registry, what did
  it cost to assemble + validate (sum of `api_calls` where
  `task_type ∈ skill_assembly|skill_critique`).
- **Drift score sparkline** — `heartbeat.last_drift_score` over the
  last N cycles (needs SQLite query: `SELECT cycle, JSON_EXTRACT(...)`).
- **Witness agreement matrix** — across skill_assembly_log entries,
  which witness tiers agree on revisions for which task signatures.

Each of these is a `lib/<name>.ts` aggregator + a
`components/widgets/<Name>Widget.tsx` consumer + an entry in
`app/page.tsx`'s `widgets` array.

## How to add a widget (recipe)

1. Add a reader to `lib/db.ts` or a new `lib/*.ts` file.
2. Create `components/widgets/MyWidget.tsx`:

   ```tsx
   import { MyDataShape } from "@/lib/foo";
   export default function MyWidget({ data }: { data: MyDataShape }) {
     return <div>…</div>;
   }
   ```

3. In `app/page.tsx`, fetch the data and append:

   ```ts
   {
     id: "my-widget",
     title: "My Widget",
     layout: { x: 0, y: 40, w: 6, h: 4 },
     body: <MyWidget data={data} />,
   }
   ```

4. Reload — it appears at the bottom of the grid. Drag to taste.

## Constraints — non-goals (for this designer pass)

- **No mutation actions.** Approve / reject / assemble all stay on
  the CLI for now. Wiring them into the UI is a separate ADR (CSRF,
  auth, audit log). If you're tempted to add a button that POSTs
  somewhere, write the ADR first.
- **No live-streaming.** All data refresh is page-reload-driven.
  Adding a websocket / SSE channel is a real piece of work; defer.
- **No charts library bake-in.** Recharts / visx / d3 are all fine
  candidates but bundle size matters — pick one when you actually
  need it.
- **Don't fork `react-grid-layout`.** It's stable; work within its API.
- **Don't move data fetching out of `app/page.tsx`.** The server-
  fetched-once model is a feature, not a limitation.

## Open questions for the human operator

These can wait, but flag them in the design if relevant:

1. Per-widget refresh rate. Right now everything is page-reload.
   Should the Status / Token Cost widgets auto-refresh every 30s
   client-side?
2. Widget visibility toggles. Right now all 13 widgets are always
   present. Should we add a "hidden widgets" tray?
3. Multi-canvas presets ("Operator view", "Debug view", "Cost view")
   with separate layout slots in localStorage?
4. Light theme. The shell uses Tailwind dark-mode classes
   conditionally; we haven't committed to which mode is default.
5. Where do we want the **drift score** to live visually? It's the
   single highest-signal number for "is the agent OK right now" and
   currently it's just a card on the Status widget.

## Anti-pattern: what *not* to do

- **Don't add hooks to `app/page.tsx`.** It's an async server
  component. Adding `useState` / `useEffect` will break it.
- **Don't pass props that aren't JSON-serializable.** Functions,
  Maps, Sets, Dates — none of those survive the boundary.
- **Don't read SQLite from a client component.** `better-sqlite3` is
  a native module; it's server-only.
- **Don't add per-widget routes.** Keep everything on `/`. If a
  widget grows enough to warrant a detail page, that's a separate
  route + a navigation pass.

## Contact points in the code

If you need to understand a specific widget's data shape:

- Read the matching `lib/*.ts` reader.
- Run the matching `chimera` CLI verb to see the raw output.
- Look at the matching ADR (each major surface has one).

Suite is 496 tests; full pass takes ~3s; run with `uv run pytest -q`
from the repo root.

---

Good luck. The shell is honest — drab on purpose so the design pass
defines the aesthetic, not the structure. Break the chrome; keep the
data contracts.
