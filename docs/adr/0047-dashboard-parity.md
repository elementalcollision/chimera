# ADR 0047 — Dashboard parity for queue health + ontology audit (v4.25)

**Status:** Accepted (2026-05-19)

## Context

ADRs 0041 (v4.19 proposer recurrence) and 0043 (v4.21 ontology audit)
both shipped CLI-only observability and called out a dashboard widget
as a follow-up. With v4.24 archiving DEPRECATED entities behind the
scenes, the operator now has more reason to glance at the dashboard
than to remember CLI verbs. Time to close the loop.

## Decision

Two new server-rendered widgets reading directly from SQLite, no
Python shell-out. The Python `queue_health` and `audit_ontology`
queries are mirrored in TypeScript so the dashboard reads the same
data shape Python writes.

### Readers — [control-plane/lib/db.ts](control-plane/lib/db.ts)

- `queueHealth(): QueueHealth | null` — mirrors
  `chimera.memory.mutations.queue_health`. Defensive on the
  `recurrence_count` column for pre-v4.19 DBs (try/catch zero out).
- `ontologyAudit(opts?): OntologyAudit | null` — mirrors
  `chimera.memory.audit.audit_ontology`. Computes `current_cycle`
  from `MAX(cycle) FROM agent_activity_log` so the snapshot is always
  anchored to the latest heartbeat.

### Widgets — [control-plane/components/widgets/SimpleWidgets.tsx](control-plane/components/widgets/SimpleWidgets.tsx)

- `QueueHealthWidget` — pills for status counts, KV grid with
  oldest-pending age (humanized), recurrence max/total, applied/decided
  ratio. Footnote when duplicates have been absorbed in-place. Age
  goes warn at >1h, danger at >24h.
- `OntologyAuditWidget` — total + cycle headline, pills per KFM
  state, KV grid with stale count, dead count, re-anchor count in
  window, DEPRECATED-unarchived. Tones flip warn when stale/dead > 0
  or DEPRECATED backlog > 5.

### Wiring — [control-plane/app/page.tsx](control-plane/app/page.tsx)

Two new WidgetDef entries placed at `y=7` so they sit right under
the existing Status / Cost / Drift / Phase row. Chip toning surfaces
attention-worthy conditions:

- Queue health: chip when oldest pending > 24h.
- Ontology audit: chip when `stale_count + dead_count > 0`.

Storage key bumped to v8 to drop the previously persisted layout.

## Tests

TypeScript typecheck: clean. Python suite: 522 / 5 — unaffected (no
Python changes this slice).

## Non-goals

- **Auto-refresh hooks for these widgets specifically.** The existing
  30-second `router.refresh()` covers them.
- **Time-series.** Queue health and audit are snapshots. Trending
  `reanchor_events_in_window` over time is still on the v4.21 backlog.
- **Operator actions from the widget.** Reading only — approve /
  archive remains a CLI verb. Operator-action UI is its own ADR.
