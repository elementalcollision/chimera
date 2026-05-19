# ADR 0014 — Emergence-aware protocol journal (v2.9)

**Status:** Accepted. Anchors v2.9. Closes the last open item on the
[ADR 0005](0005-multi-agent-architecture.md) §"What v2.x will need"
roadmap.

## Context

Peer protocols (the schemas Chimera and its peers advertise to each
other) aren't fixed. As tools evolve — new params added, old ones
deprecated, schemas swapped for richer versions — peers need a way to
*notice* that and decide whether to renegotiate. Xenocomm calls this
"emergence". v2.9 ships the minimal data plumbing.

## Decision: a journal, not a negotiator

v2.9 records observations. It does NOT propose changes, vote on
upgrades, or migrate schemas. Those each warrant their own ADR when a
concrete need arises.

### Journal shape

One JSONL file per peer under ``$CHIMERA_PROTOCOL_JOURNAL_DIR``
(default: ``$CHIMERA_STATE_DIR/protocol_journal/`` or
``~/.chimera/protocol_journal/``):

```jsonl
{"peer": "chimera-alpha", "tool": "shell", "params": ["argv", "cwd", "timeout_s"], "observed_at": "2026-05-19T15:00:00+00:00"}
{"peer": "chimera-alpha", "tool": "shell", "params": ["argv", "cwd", "env", "timeout_s"], "observed_at": "2026-05-20T15:00:00+00:00"}
{"peer": "chimera-alpha", "tool": "code_exec", "params": ["code", "timeout_s"], "observed_at": "2026-05-20T15:00:00+00:00"}
```

Each line is one ``ObservationRecord``: ``(peer, tool, params, observed_at)``.
Params are the sorted top-level property names of the tool's OpenAI
schema. We deliberately don't store full schemas — params are the part
that changes most often and the part that matters for compatibility.

### Drift detection

:func:`detect_protocol_drift(peer, current_schemas=...)` compares the
peer's earliest observation per tool to "current" (either the latest
journaled observation, or a live snapshot if passed in). Classifies
each tool as:

- ``STABLE`` — params unchanged from baseline
- ``ADDED`` — tool present in current but never seen in baseline
- ``REMOVED`` — tool in baseline gone from current
- ``EVOLVED`` — tool present in both, param set differs

The ``EvolutionRecord`` also carries ``added_params`` and
``removed_params`` sets so a caller can describe the delta without
re-deriving it.

### Why per-tool baseline, not "rolling window"

A peer's protocol shouldn't drift backwards (semver-major aside).
Comparing current to the *earliest* observation makes the journal a
true changelog: anything added is permanent, anything removed is
visible, anything renamed shows up as both a removed and an added
param in the EVOLVED record. A rolling-window comparator would lose
that history. Operators who want short-term drift can read the journal
directly.

### Helpers

- :func:`record_observations_from_registry(peer, registry)` — walks
  the local registry for ``mcp-<peer>-*`` tools and records each.
  Convenient hook from any post-discovery cycle.
- :func:`forget_peer(peer)` — drop a peer's journal file.

## What v2.9 *doesn't* do

- **Doesn't negotiate.** No "let's both upgrade to v3 of shell" wire
  protocol. Negotiation is a separate ADR if/when needed.
- **Doesn't auto-record.** Callers decide when to journal an
  observation. The cycle's FLUSH phase is the natural hook, but
  wiring it there is left for the operator (or a later v2.x).
- **Doesn't sync across hosts.** The journal lives on the local
  filesystem. Cross-host journaling lands when there's a real swarm
  registry beyond the local FS.

## References

- [ADR 0005](0005-multi-agent-architecture.md) §"What v2.x will need" — original plan
- [ADR 0013](0013-alignment-ceremony.md) — schema-alignment strategy this complements
- Xenocomm SDK — EmergenceManager (the concept this is named after)
- [chimera/a2a/emergence.py](../../chimera/a2a/emergence.py)
