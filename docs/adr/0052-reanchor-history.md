# ADR 0052 — Re-anchor history widget (v4.30)

**Status:** Accepted (2026-05-19)

## Context

[ADR 0043](./0043-ontology-audit.md) (v4.21) shipped the ontology audit with a snapshot
`reanchor_events_in_window` field — useful, but only a single number.
Its non-goals called out a time-series view as the next sprint:
"Trending reanchor_events_in_window over time is a worthwhile v4.2x
sprint." With v4.24's auto-archive now writing K-operator transitions
behind the scenes too, the operator wants a trend, not just a count.

## Decision

`reanchor_history(conn, *, current_cycle, bucket_size=10, n_buckets=12)`
in `chimera/memory/audit.py` returns ``n_buckets`` contiguous,
oldest-first buckets of width ``bucket_size`` cycles. Each bucket
counts ``STABLE → DEPRECATED`` transitions written by the K-operator
within ``[start_cycle, end_cycle)``. The newest bucket ends at
``current_cycle + 1`` so the live cycle is included.

Defaults: 12 buckets × 10 cycles = 120 cycles of trend (covers the
50-cycle audit window plus headroom).

### Dashboard

- `control-plane/lib/db.ts::reanchorHistory()` mirrors the Python
  reader; `current_cycle` resolved from
  `MAX(cycle) FROM agent_activity_log`.
- New `ReanchorHistoryWidget` in `SimpleWidgets.tsx`: serif total
  headline, amber sparkline of bucket counts, peak-per-bucket
  footnote. Includes a heuristic trend pill (last third sum vs first
  third sum) — warn on rising, ok on falling.
- Wired into `app/page.tsx` at `y=11` (group: agent), 12 cols wide.
  Storage key bumped to v9.

## Tests

`tests/test_audit_ontology.py`:

- empty DB → all zeros, correct contiguous boundaries
- known demotions bucketed correctly (cycles 5, 12, 13, 21, 33, 47 →
  counts [1, 2, 1, 1, 1])
- non-K transitions ignored
- degenerate inputs (`bucket_size=0`, `n_buckets=0`) return []

TypeScript typecheck clean. Full suite: 530 passing.
