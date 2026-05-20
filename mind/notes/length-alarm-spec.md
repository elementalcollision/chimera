# Length-truncation alarm — spec

**Status:** proposed
**Owners:** Chimera self-maintenance
**Justification:** `mind/notes/length-truncation-cycle23.md` — 28/1024 calls
clipped at the per-tier `max_tokens` cap (2.73% baseline; 6% on recent
cycles). Today the only operator-visible signal is the `by_finish=[length=N]`
counter rendered into the next cycle's system header (`chimera/prompts/history.py`
line 50), which a human has to read and notice. We need an *automated* alarm.

## Goal

Surface a warning whenever any single `(provider, model_id)` pair hits
`finish_reason="length"` more than **N** times in the trailing **W**
minutes, via:

1. a `chimera doctor`-style CLI check, callable in CI / cron, and
2. (stretch) a row in the dashboard JSON snapshot
   (`chimera doctor --snapshot`, see `chimera/cli.py` line 325).

The alarm MUST be cheap to evaluate (one indexed SQL query) and MUST
never block a cycle — it's diagnostic.

## Data source

`state/chimera.db` → `api_calls` table. Columns already present
(`chimera/memory/store.py` lines 68–88):

- `cycle`, `provider`, `model_id`, `finish_reason`, `created_at`
- index `idx_api_calls_cycle` exists; for time-window queries we rely
  on `created_at` (ISO-8601 UTC, lexicographically sortable). If the
  alarm becomes hot, add `CREATE INDEX idx_api_calls_finish_created
  ON api_calls(finish_reason, created_at)` — *not* in v1, defer until
  the query shows up in a slow-log.

No schema migration is required for v1.

## Thresholds

| knob               | env var                              | default | rationale |
|--------------------|--------------------------------------|---------|-----------|
| Window minutes (W) | `CHIMERA_LENGTH_ALARM_WINDOW_MIN`    | `60`    | matches the "per hour" framing in the inbox task |
| Trip count (N)     | `CHIMERA_LENGTH_ALARM_MAX_PER_HOUR`  | `3`     | cycle 25–29 saw 3/cycle ≈ 3/hour at observed cadence; one clip is noise, three is a pattern |
| Warn count         | `CHIMERA_LENGTH_ALARM_WARN`          | `1`     | any clip in the window is a `warn`; ≥ N is `error` |
| Per-pair grouping  | (hardcoded)                          | on      | a single hot model shouldn't be hidden by a quiet one |

All knobs read at check time; no restart needed.

## Output shape

### CLI

New `chimera doctor` check named `length-truncation`, returning a
`CheckResult` (see `chimera/core/doctor.py`):

```
[✓] length-truncation        0 clips in last 60min
[!] length-truncation        1 clip in last 60min (claude-opus-4-7: 1)
[✗] length-truncation        7 clips in last 60min (claude-opus-4-7: 5, deepseek-v4-pro: 2) — exceeds N=3
```

Exit code:
- `ok` → no change
- `warn` → no change (doctor already returns 0 on warn)
- `error` → doctor returns 1, so CI / `chimera doctor` in a cron will fail loudly

Also expose as a standalone subcommand for non-doctor callers:

```
chimera length-alarm [--window-min 60] [--max 3] [--json]
```

`--json` emits:

```json
{
  "window_min": 60,
  "max_per_hour": 3,
  "total_clips": 7,
  "by_pair": {"anthropic/claude-opus-4-7": 5, "openrouter/deepseek-v4-pro": 2},
  "status": "error",
  "since": "2025-…",
  "until": "2025-…"
}
```

The JSON form is what the dashboard snapshot will consume.

### Dashboard snapshot

`chimera doctor --snapshot` already writes a JSON file for the
dashboard (`chimera/cli.py` line 325). Add a top-level key:

```json
"length_alarm": { …same shape as --json above… }
```

The dashboard renders a single coloured tile: green / yellow / red
matching `status`.

## Query

```sql
SELECT provider, model_id, COUNT(*) AS n
FROM api_calls
WHERE finish_reason = 'length'
  AND created_at >= :since
GROUP BY provider, model_id
ORDER BY n DESC;
```

`:since` = `(now_utc - W minutes).isoformat(timespec="seconds")`.
`now_utc` uses the same `datetime.now(timezone.utc)` convention as
`chimera/core/escalation.py` line 137 for symmetry.

Cost: with current volume (~1k rows total) this is a full scan and still
sub-millisecond. At 100× the data we add the composite index above.

## Code layout

New module `chimera/core/length_alarm.py`:

```python
@dataclass(frozen=True)
class LengthAlarm:
    window_min: int
    max_per_hour: int
    total: int
    by_pair: dict[str, int]   # "provider/model_id" -> count
    status: str               # "ok" | "warn" | "error"
    since: str
    until: str

def evaluate(conn: sqlite3.Connection, *,
             window_min: int | None = None,
             max_per_hour: int | None = None,
             warn_at: int | None = None,
             now: datetime | None = None) -> LengthAlarm: ...
```

`evaluate` is pure (takes `now` for testability). The doctor check
and the CLI subcommand both call it.

Wire-in points:

1. `chimera/core/doctor.py::run_checks` — append
   `_check_length_truncation(state_dir)` after `_check_sqlite`.
   Skip silently if `api_calls` table is missing (mirrors
   `record_failure`'s graceful no-op pattern in
   `chimera/core/escalation.py` line 146).
2. `chimera/cli.py` — register `length-alarm` subcommand next to
   `doctor` / `escalations` / `status`. Reuse `open_and_init` to get
   the connection.
3. `chimera/cli.py::doctor --snapshot` — include the `LengthAlarm`
   dataclass (as dict) in the snapshot payload.

## Tests

Add `tests/test_length_alarm.py` covering:

1. Empty table → `status=ok, total=0`.
2. One clip inside window → `status=warn` (assuming default `warn_at=1`).
3. N clips of the same `(provider, model_id)` → `status=error`,
   `by_pair` has one entry with count N.
4. Clips outside the window are excluded (parametrise `now`).
5. Mixed `finish_reason` values: only `length` is counted.
6. Missing `api_calls` table → returns `status=ok, total=0`
   (graceful, like the escalation module).

All tests use an in-memory SQLite via the existing `open_and_init`
test helper.

## Non-goals (v1)

- **Persisting alarm history.** The query is cheap; recomputing is fine.
- **Auto-paging / Slack / email.** The CI failure on `doctor` is the
  paging channel. Webhook integration is a v2 concern.
- **Treating `finish_reason="length"` as a ladder failure.** This is a
  separate, tracked item in `mind/notes/length-truncation-cycle23.md`
  §Recommendations. Doing it here would conflate "I want to know about
  truncations" with "I want truncations to trigger escalation
  retries". Keep them separate so we can tune thresholds independently.
- **Per-tier thresholds.** Opus, sonnet, haiku currently share one
  N=3. If opus clips become structurally more common we'll add
  `CHIMERA_LENGTH_ALARM_MAX_PER_HOUR_OPUS` etc. — but not in v1.

## Acceptance

- `chimera doctor` on a DB containing the cycle 25–29 history reports
  `[✗] length-truncation … exceeds N=3`.
- `chimera doctor` on a DB with the cycle 19–22 history (1/cycle)
  reports `[!] length-truncation 1 clip …`.
- `chimera doctor` on a fresh DB reports `[✓] length-truncation 0 clips`.
- `chimera length-alarm --json` round-trips through `json.loads`.
- All six tests above pass.

## Open questions

1. **Window definition under sparse runs.** If Chimera ran 18 calls in
   one minute, then nothing for 59 minutes, three of which clipped,
   the alarm trips. Is that desired? *Probably yes* — three clips is
   three clips regardless of idle time. Document this; revisit if it
   produces false positives during long sleeps.
2. **Cycle-aligned vs wall-clock window.** Going with wall-clock
   (`created_at`) because cycles are not fixed-length. If the
   dashboard prefers "last K cycles" we can add `--window-cycles` later.
3. **Should the alarm read from the graph DB instead?**
   `chimera/memory/graph.py` line 191 already projects `api_calls`
   into Kuzu with `finish_reason`. SQLite is simpler and the
   authoritative store; defer the graph version.
