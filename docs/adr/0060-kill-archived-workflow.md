# ADR 0060 — ARCHIVED → KILLED operator workflow (v4.39)

**Status:** Accepted (2026-05-19)

## Context

[ADR 0046](./0046-auto-archive-deprecated.md) (v4.24) shipped auto-archival of stale DEPRECATED entities
but called out `ARCHIVED → KILLED` as intentionally manual: KILLED
wipes history, ARCHIVED preserves it. There was no automated path
toward KILLED, no operator surface for "I'm ready to permanently
retire these archived entities," and no audit record of who approved
what.

The mutation queue is already the canonical "Chimera proposes,
operator disposes" channel. The right shape for kill workflow is to
queue mutations exactly like any other proposal.

## Decision

Two new functions in `chimera/memory/audit.py`:

### `propose_kill_archived(conn, *, current_cycle, archive_after_cycles=90, max_per_cycle=25, dry_run=False)`

Scans ARCHIVED entities with `state_entered_at_cycle <= current_cycle
- archive_after_cycles`. For each, enqueues a `kill_entity` mutation
with payload `{entity_id, kind, name, cycles_in_state}`. Default
threshold is 90 cycles — much longer than v4.24's 30-cycle DEPRECATED
→ ARCHIVED to give operators plenty of time to grab archived data
before it's permanently lost.

Dedup: existing `status='pending'` `kill_entity` mutations for the
same `entity_id` are not re-enqueued.

### `apply_approved_kills(conn, *, current_cycle, max_per_run=25)`

Walks `status='approved'` `kill_entity` mutations and transitions
each referenced entity `ARCHIVED → KILLED` via the K-operator (the
only operator authorised for that transition). Marks the mutation
applied on success. On transition error: `mark_failed` with the
exception text — leaves the entity untouched for operator follow-up.

### Operator workflow

```
$ chimera ontology --propose-kills          # queues N kill_entity mutations
$ chimera mutations list                    # operator reviews
$ chimera mutations approve <id>            # explicit per-row approval
$ chimera ontology --apply-kills            # actually transitions to KILLED
```

Each step is auditable, each step is opt-in, and the
`peer_trust_journal` / `entity_transitions` audit trail is
populated naturally.

## Tests

`tests/test_audit_ontology.py` — 5 new tests:

- `test_propose_kill_queues_pending_mutation` — happy path
- `test_propose_kill_skips_recent_archived` — under threshold → no-op
- `test_propose_kill_dedups_pending` — second call doesn't duplicate
- `test_apply_approved_kills_transitions_to_killed` — approved →
  K-operator → KILLED; mutation marked applied
- `test_apply_approved_kills_skips_unapproved` — pending stays put

Full suite: 543 passing, 5 skipped.

## Non-goals

- **Auto-approval.** The kill path stays human-gated end-to-end.
- **Dashboard widget.** The existing OntologyAudit widget already
  surfaces `deprecated_unarchived`. An analogous `archived_unkilled`
  counter is a small follow-up; not in this slice.
- **Soft-delete vs hard-delete.** KILLED is the existing terminal
  state and we don't reshape its semantics.
