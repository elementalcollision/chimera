---
goal: "Add crawl_ledger.merge_rate(state_dir, since=None) — fraction of outcomes merged"
files: chimera/core/crawl_ledger.py tests/test_crawl_ledger_merge_rate.py
test: tests/test_crawl_ledger_merge_rate.py
property: "merge_rate always returns a float in [0.0, 1.0] equal to (#merged in the ts>=since window) / (#in window), rounded to 4 dp, and 0.0 when the window is empty"
base: main
done: true
---
The RUN-graduation signal in one number: add
`merge_rate(state_dir, since=None) -> float` to `chimera.core.crawl_ledger`
returning the fraction of folded outcomes whose `disposition == "merged"`
(`0.0` when there are no outcomes). Honour the same optional `since`
ISO-timestamp window as `summarize_outcomes` — only outcomes with `ts >= since`
count. Reuse `read_outcomes()`; round the result to 4 decimal places.

Acceptance: create `tests/test_crawl_ledger_merge_rate.py` (use `tmp_path` as
the state dir; build outcomes via `record_outcome` + `set_disposition`)
covering: one `merged` + one `abandoned` → `0.5`; no outcomes → `0.0`; a
`since` timestamp after all outcomes → `0.0`. Keep the change in
`chimera/core/crawl_ledger.py`. `chimera verify` (ruff + the new test) green.
