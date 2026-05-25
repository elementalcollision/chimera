# ADR 0136 — Temporal-Aware Dialectic (Proposed)

**Status:** Proposed

**Relationship:** Extends [ADR 0133 — Dialectic API](./0133-dialectic-api.md) by adding time-series belief, trust, and drift queries to the `peers ask` surface. Consumes the JSONL journals from [ADR 0132 — Observer/observed beliefs](./0132-observer-observed-beliefs.md) and the `peer_trust_journal` format established by [ADR 0128](./0128-peer-cards.md) and [ADR 0131](./0131-peers-cli-verb.md).

## Context

ADR 0133's dialectic API answers questions about a peer's *current* state — the latest peer card, the most recent trust decisions, the freshest belief snapshot. This works for "who is peer alpha right now?" but leaves a class of operational questions unanswered:

- *"Has peer alpha's drift score been climbing over the last 10 rotations?"* — the operator sees the latest score but can't tell whether it's a spike or a trend.
- *"When did Chimera first start distrusting peer gamma?"* — the trust journal has the raw data but no query surface exists across its history.
- *"Show me the belief timeline for peer beta — when did it flip from TRUSTS to NEUTRAL?"* — the JSONL is append-only but no API exposes it as a sequence.
- *"What was the KFM snapshot for peer delta on rotation 42?"* — historical snapshots are written to the JSONL `extra` field but invisible to the dialectic prompt.

Each of these requires **temporal range queries** over the append-only journals that the dialectic pipeline ignores today.

## Design variables (locked via interactive design pass)

| Variable | Choice |
|---|---|
| **Temporal data sources** | `peer_beliefs.jsonl` (belief labels + drift scores + KFM extras) · `peer_trust_journal/` (decisions + reasons + timestamps) · peer card diff log (optional, opt-in) |
| **Surface** | Extended `chimera peers ask` CLI verb with `--window` flag · same `chimera-ask` MCP tool (returns extended prompt schema) |
| **Time-window syntax** | `--window N` (last N journal entries) · `--window N:M` (slice N..M, newest-first) · `--window since:<iso8601>` (absolute wall-clock start) · default 1 (current, backwards-compatible) |
| **Drift trend shape** | Plain-prose summary: "drift has risen from 0.12 to 0.47 over 8 rotations (↑0.35)" + "on track to exceed DEGRADE threshold in ~3 cycles at current slope" — computed client-side from raw series, not LLM-inferred |
| **Belief timeline shape** | Bullet list per label flip: "`2026-05-20T14:23Z` — alpha DISTRUSTS beta (drift 0.71, source: KFM cycle 41)" |
| **Empty time window** | "No recorded data in the requested window" — same honesty discipline as ADR 0133's unknown-peer stub |
| **Additive to 0133** | Yes — all existing `peers ask` behaviour unchanged when `--window` is omitted |

## Decision

### Extended module: `chimera/a2a/dialectic.py`

New public functions, all additive (nothing in the existing 0133 surface changes):

#### `gather_temporal_context(peer_name, *, mind_dir, window=1)`

Reads historical data from the same filesystem paths the sync reader already knows:

- **`peer_beliefs.jsonl`** — calls `latest_per_pair` (window=1) or reads N entries per pair sorted by `recorded_at` descending (window=N). Defensively parses the `extra` dict to extract `cycle` and `plan_kfm_state` from earlier KFM snapshots.
- **`peer_trust_journal/`** — reads journal files in `mind/peer_trust_journal/` for the named peer (exact match) or all peers (no filter). Caps at `window` entries per file.
- **Peer card diffs** — optional: if `mind/peers/<name>.md.d/` exists with timestamped diffs, reads them in order. Opt-in because the card-overwrite path doesn't produce diffs today; populated only when `CHIMERA_PEER_CARD_DIFF_LOG=1` is set and a card-writing tool generates them.

Returns a `TemporalContext` dataclass: `peer_name`, `belief_series: list[PeerBelief]`, `trust_series: list[dict]`, `card_diff_series: list[str]`, `window_spec: str`.

#### `compute_drift_trend(belief_series) -> dict`

Pure-function computation from the drift scores in a `belief_series` sorted chronologically. Returns `{first_score, last_score, delta, slope, threshold_label, cycles_to_threshold_at_current_slope}`. No LLM involvement — mirrors the "provider-agnostic" discipline from ADR 0133 §"Core module". The slope is linear over the series length; cycles_to_threshold projects the slope forward against the DEGRADE band boundary (0.30) and the REFUSE boundary (0.60). If the slope is flat or negative, `cycles_to_threshold` is `None`.

#### `build_temporal_prompt(ctx, temporal_ctx, question)`

Extends `build_dialectic_prompt`. When `temporal_ctx.window_spec == "1"` (default), delegates entirely to the existing 0133 template — zero behaviour change. When window > 1, appends a **Temporal Context** block after the current-context block:

```
## Temporal Context (last {window} entries)

### Belief timeline for {peer_name}
{belief_timeline_bullets}

### Drift trend
{drift_summary}

### Trust-decision history
{trust_bullets}

### Questions
{question}
```

The `drift_summary` is rendered from `compute_drift_trend` output. The `belief_timeline_bullets` are rendered from the series. The `trust_bullets` are rendered from the trust journal entries with their `recorded_at` timestamps.

#### `trim_temporal_answer(text, *, word_cap=200)`

Same logic as `trim_answer` from ADR 0133 but with a higher default word cap (200 instead of 140) because temporal questions tend to have longer answers (multiple bullets, trends, projections). Still strips markdown fences and caps at threshold.

### Extended MCP tool schema

The `chimera-ask` tool (ADR 0133 §"MCP tool") gains an optional `window` parameter (integer or ISO8601-string, default `1`). The response JSON extends to:

```json
{
  "peer_name": "alpha",
  "question": "Has drift been rising?",
  "prompt": "...",
  "sources_used": ["peer_card", "trust_journal", "beliefs_jsonl"],
  "is_empty_context": false,
  "window": 8,
  "temporal_summary": {
    "drift_first": 0.12,
    "drift_last": 0.47,
    "drift_delta": 0.35,
    "slope": 0.044,
    "cycles_to_deg_threshold": 3,
    "belief_flips": [
      {"at": "2026-05-20T14:23Z", "from": "TRUSTS", "to": "NEUTRAL"}
    ]
  }
}
```

The `temporal_summary` field is `null` when `window == 1` (backwards-compatible). The prompt field continues to be what the caller feeds to their own LLM — the same cost-containment principle from ADR 0133.

### Extended CLI: `chimera peers ask --window`

```
chimera peers ask alpha "Has drift been rising?" --window 8
chimera peers ask beta "When did trust degrade?" --window since:2026-05-01
chimera peers ask gamma "Show me belief flips" --window 5:10
```

- `--window N` — last N entries from the JSONL and trust journal.
- `--window N:M` — entries N through M (newest-first, 1-indexed). Useful for paging through history.
- `--window since:<iso8601>` — all entries from that UTC timestamp forward.
- Default `1` — single most-recent entry per source, identical to ADR 0133's behaviour.
- Implies `--json` if any temporal context is present (structured data is useful for scripting across a trend). The plain-text output is the LLM's answer; the JSON output adds `temporal_summary` alongside `answer`.

### Why drift trend is computed client-side, not LLM-inferred

The locked design considered asking the LLM to "describe the trend" from raw numbers. Rejected because:

1. **LLMs hallucinate slopes.** Even with the numbers in the prompt, different models produce different trend statements for the same input. A computed `drift_delta` and `slope` are deterministic.
2. **Cost.** Putting 10 raw drift scores in the prompt costs ~40 tokens; asking the LLM to reason about them costs several hundred more. The whole point of the temporal extension is to surface *latent* information without burning sonnet tokens on arithmetic.
3. **Composability.** A computed `temporal_summary` in the JSON response means a dashboard widget or CI script can plot the trend without calling an LLM at all.

The LLM *does* get the computed trend summary in its prompt (so it can answer free-form questions like "Is this concerning?"), but the raw computation is done in Python.

## Why no graph-side temporal projection

ADR 0132 projected `latest_per_pair` into a Kuzu `BELIEVES_ABOUT` edge — but only the latest per pair. Full time-series projection would require either:

- A `BELIEVES_ABOUT_HISTORY` rel table with time-bucketed rows (schema churn, Kuzu row-count concerns), or
- An on-the-fly SQLite query against the JSONL (no schema churn but mixing Kuzu and SQLite in the same query path).

Both are heavier than reading the JSONL directly. Since the JSONL is append-only, grep-able, and typically < 1 MB, the temporal context gatherer reads it directly with Python's `json` module — same pattern as the trust journal reader. A future ADR can add a Kuzu temporal projection if query latency ever becomes a problem.

## Consequences

### Positive

- Operators can spot drift trends before they cross DEGRADE/REFUSE thresholds — a genuine operational win that the "latest only" dialectic couldn't provide.
- The `--window` flag is backwards-compatible: default 1 means zero behaviour change for existing `peers ask` users.
- `temporal_summary` in the JSON response is a machine-parseable signal that dashboards and CI can consume without parsing LLM prose.
- Compute-then-prompt separation keeps the LLM's job to *interpret* the trend, not *calculate* it — fewer hallucination risks, lower token cost.
- No new filesystem layout — the temporal reader ingests the same `peer_beliefs.jsonl` and `peer_trust_journal/` paths that already exist.

### Negative

- `gather_temporal_context(window=N)` reads N lines from the JSONL per peer — fine for N ≤ 50 but could be slow if an operator asks for `--window 10000`. Mitigated by capping N at 200 in the reader (configurable via `CHIMERA_TEMPORAL_MAX_WINDOW` env var, default 200).
- The `window since:<iso8601>` branch requires scanning the entire JSONL. Acceptable because `peer_beliefs.jsonl` is typically < 10k rows; future optimisation can binary-search the file if it grows.
- Peer card diffs are opt-in and not produced by the current card-writing path — the `CHIMERA_PEER_CARD_DIFF_LOG=1` env var and associated writer are out of scope for this ADR and deferred to a follow-up.
- Adds a second answer-cap constant (200 vs 140). The mismatch is documented in the module code and explained by the bullet-heavy shape of temporal answers.

## Out of scope (this ADR)

- Peer card diff logging — the `card_diff_series` path in `TemporalContext` is schema-ready but the writer doesn't exist yet. A follow-up ADR adds `CHIMERA_PEER_CARD_DIFF_LOG=1` and the diff-producing write path.
- Dashboard widget that visualises the drift trend — the `temporal_summary` JSON output is the dashboard contract; widget implementation is a separate chip.
- Graph-side temporal projection (Kuzu `BELIEVES_ABOUT_HISTORY`) — the JSONL direct-read approach is sufficient for the foreseeable future.
- Async-batched temporal context gathering across multiple peers — `peers ask` is single-peer; multi-peer temporal analysis is a future `peers sweep ask` surface.
- Trend forecasting beyond simple linear projection — `cycles_to_threshold` is a straight-line extrapolation. Exponential or regression-based forecasting is deferred until an operator expresses need.

## References

- [ADR 0133 — Dialectic API](./0133-dialectic-api.md) — extended by this ADR; temporal context is additive, not breaking.
- [ADR 0132 — Observer/observed belief pairs](./0132-observer-observed-beliefs.md) — JSONL belief journal consumed by `gather_temporal_context`.
- [ADR 0128 — Peer Cards](./0128-peer-cards.md) — trust journal format consumed by the temporal reader.
- [ADR 0131 — `chimera peers cards` CLI verb](./0131-peers-cli-verb.md) — the `peers ask` sibling verb that this ADR extends with `--window`.
- [ADR 0130 — Peer card narrative](./0130-peer-card-narrative.md) — word-cap discipline mirrored in `trim_temporal_answer`.
