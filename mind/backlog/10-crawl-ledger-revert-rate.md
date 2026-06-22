---
goal: "Add crawl_ledger.revert_rate(state_dir, since=None) — fraction of outcomes reverted"
files: chimera/core/crawl_ledger.py tests/test_crawl_ledger_revert_rate.py
test: tests/test_crawl_ledger_revert_rate.py
property: "revert_rate always returns a float in [0.0, 1.0] equal to (#reverted in the ts>=since window) / (#in window), rounded to 4 dp, and 0.0 when the window is empty"
base: main
done: true
---
The safety counterpart to `merge_rate` (a high revert rate means landed CRAWL
changes are not holding — the strongest signal against auto-merge graduation).
Add `revert_rate(state_dir, since=None) -> float` to
`chimera.core.crawl_ledger` returning the fraction of folded outcomes whose
`disposition == "reverted"` (`0.0` when there are no outcomes). Honour the same
optional `since` ISO-timestamp window as `summarize_outcomes` (only outcomes
with `ts >= since` count). Reuse `read_outcomes()`; round to 4 decimal places.

(If spec 06 `merge_rate` has landed, mirror its shape/`since` handling exactly.)

Acceptance: create `tests/test_crawl_ledger_revert_rate.py` (use `tmp_path`;
build outcomes via `record_outcome` + `set_disposition`) covering: one
`reverted` + one `merged` → `0.5`; no outcomes → `0.0`; a `since` after all
outcomes → `0.0`. Keep the change in `chimera/core/crawl_ledger.py`.
`chimera verify` (ruff + the new test) green.
