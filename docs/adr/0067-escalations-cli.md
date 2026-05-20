# ADR 0067 — `chimera escalations` CLI verb (v4.48)

**Status:** Accepted (2026-05-19)

## Context

v4.46 added persistent task-escalation memory. The agent reads from
it on every cycle to auto-promote tier, but operators had no surface
for inspecting it. "Why did this task start at sonnet?" and "clear
the noise from my testing" both required raw SQL.

## Decision

New `chimera escalations` verb with three sub-commands.

### `chimera escalations list [--limit N] [--grep <substr>]`

Most-recent-first dump of escalation rows. Each line shows cycle,
tier, finish_reason, rounds_used, and a task-text preview.

### `chimera escalations summary`

Aggregate counts per signature × tier. Sorted by total failures
desc. Tasks that appear at multiple tiers are the candidates for
"genuinely hard" diagnosis.

### `chimera escalations clear [--grep <substr>] [--all]`

Delete rows. Safety guard: requires `--grep` OR `--all` — no
implicit full wipe. The agent uses these to learn, so clearing them
resets that learning.

### Reader API

Three helpers in `chimera/core/escalation.py`:

- `list_escalations(conn, *, limit, signature_substring) -> list[EscalationRow]`
- `escalation_summary(conn) -> dict[signature, dict[tier, count]]`
- `clear_escalations(conn, *, signature_substring) -> int`

All return `[]` / `{}` / `0` gracefully if the v4.46 table doesn't
exist (pre-migration DBs).

## Tests

`tests/test_task_escalation.py` — 5 new tests:

- `test_list_escalations_returns_recent_first`
- `test_list_escalations_grep_filters`
- `test_escalation_summary_groups_by_signature_and_tier`
- `test_clear_escalations_with_grep`
- `test_clear_escalations_all`

Full suite: **569 passing**, 5 skipped.

## Non-goals

- **Dashboard widget.** The Tool-fanout widget already shows
  per-model parallelism — escalations are a parallel data stream
  that deserves its own widget, but not in this slice.
- **Auto-decay.** Old escalations stay forever. Pairs with the
  v4.46 non-goal of TTL/recency filtering.
