# ADR 0087 — Hot-signatures dashboard widget (v4.68)

**Status:** Accepted (2026-05-20)

## Context

[ADR 0073](./0073-observability-tightening.md) added the
`⚠️ HOT SIGNATURES` section to `chimera escalations summary` — task
signatures with ≥ 2 escalation failures, the inflection point where
"tier was wrong" tips into "task text needs rewriting." That ADR
explicitly listed the dashboard widget as a non-goal at the time:

> **Not extending the hot-signature alarm into the dashboard yet.**
> CLI surface lands here; a dashboard widget for hot signatures is
> a natural follow-up.

Three subsequent ADRs make the dashboard surface more valuable now:

- [ADR 0082](./0082-task-splitter.md) — `chimera split` lets the
  operator preview a model-proposed split for a hot signature.
- [ADR 0084](./0084-auto-loop-task-splitter.md) — auto-loop
  splitter fires at ≥ 3 failures; the dashboard at ≥ 2 gives the
  operator one cycle to act before the agent proposes a split.
- [ADR 0086](./0086-doctor-cost-check.md) — preflight cost-state
  in doctor; the dashboard is the operator's continuous view of
  the same data.

The widget closes the observability loop: hot signatures are
visible passively, not just on demand.

## Decision

### `control-plane/lib/db.ts` — `hotSignatures(opts)` reader

```typescript
export function hotSignatures(opts?: { threshold?: number; limit?: number }):
  HotSignatureRow[]
```

Mirrors `chimera.core.escalation.hot_signatures()` in Python. Same
SQL shape: `GROUP BY signature` with `HAVING COUNT(*) >= ?`,
ordered by `total_failures DESC, last_cycle DESC`. For each
matching signature, a follow-up query fetches the most-recent
`finish_reason` and a 120-char excerpt of the most-recent
`task_text`.

Defensive on pre-v4.46 DBs that lack `task_escalations`: the SQL
throws, caught, returns `[]`.

### `control-plane/components/widgets/HotSignaturesWidget.tsx`

Renders the rows with:

- A peach-coloured left border on each entry (matches the cost-rate
  alarm's red-band stripe vocabulary)
- `×N` failure count + tier list + cycle range + last finish_reason
- 120-char excerpt of the most-recent task_text (full text in
  hover tooltip)
- Empty state: "No hot signatures." — explicitly framed as the
  healthy state, with a one-line explanation of when the auto-loop
  splitter fires (≥ 3, ADR 0084).
- Footer: operator actions (rewrite INBOX, `chimera split`).

### `control-plane/app/page.tsx` — wire-up

```tsx
const hotSigs = hotSignatures({ threshold: 2, limit: 8 });
// …
{ id: "hot_signatures", title: "Hot signatures", eyebrow: "escalations",
  group: "agent", layout: { x: 4, y: 16, w: 8, h: 4 },
  body: <HotSignaturesWidget rows={hotSigs} /> }
```

Storage version bumped v14 → v15 (`STORAGE_LAYOUT` +
`STORAGE_PINS`) per the AGENTS.md convention.

## Tests

`tests/test_hot_signatures_sql.py` — 5 new contract tests mirroring
the TS SQL in Python (same pattern as
`test_model_utilization_sql.py`):

- Empty table → 0 rows
- Threshold filters single-failure signatures
- Same signature with 2 failures → grouped, tiers merged
- ORDER BY total_failures DESC respected
- LIMIT honored

These run in the standard pytest sweep so a schema change to
`task_escalations` that breaks the dashboard widget also breaks CI.

Existing `tests/test_hot_signatures.py` (Python helper) still
passes — same SQL shape, same row format.

Full suite after v4.68: 736 passing (was 731, +5 new SQL contract
tests).

## Non-goals

- **No alerting / desktop notification.** Same position as
  ADR 0073 §"Not auto-killing a run on red band." Widget surfaces
  the signal; operator decides. The browser-notification path
  belongs to the cost-rate alarm and finish_reason=length alarm,
  not here.
- **No drill-down on click.** The full task text is in the SQLite
  row; a future operator action could be a click → open the
  signature's escalation history. For v4.68 the excerpt-in-tooltip
  approach is enough.
- **No threshold knob in the UI.** The widget hard-codes
  `threshold=2` to match ADR 0073. Operators who want a different
  threshold can drop to the CLI (`chimera escalations summary`).
- **No history sparkline.** Hot signatures are categorical, not
  time-series. A "failures per day" graph is a follow-up only if
  operators report needing trend visibility.

## Why this shape

Why threshold 2 in the widget and 3 in the auto-splitter? Because
the widget is the operator's first chance to see the problem; the
auto-splitter is the agent's intervention. At 2 the operator
should look; at 3 the agent acts. Different audiences, different
thresholds.

Why limit 8 rows? Because the canvas widget tile is 8 columns × 4
rows tall and 8 entries with excerpts fit cleanly without
scrolling. Operators who need more can drop to the CLI. The
widget is for at-a-glance; the CLI is for deep inspection.

Why mirror the SQL contract in Python? Because the dashboard runs
the SQL against the SQLite file Python writes; if the column
names or task_escalations schema drift, both surfaces break. A
Python test that runs the same SQL catches the drift before the
dashboard does, and the existing `test_model_utilization_sql.py`
pattern is well-established.

Why a peach-coloured stripe instead of red? Because peach
(`var(--mlc-peach-500)`) is the MLC design-language warning tone;
red is reserved for the cost-rate alarm's "investigate
immediately" state. Hot signatures are "review when convenient,"
which is amber/peach territory.
