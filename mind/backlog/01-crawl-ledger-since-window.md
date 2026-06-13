---
goal: "Add an optional since-timestamp window to crawl_ledger.summarize_outcomes"
files: chimera/core/crawl_ledger.py tests/test_crawl_ledger_since.py
test: tests/test_crawl_ledger_since.py
base: main
done: false
---
Dogfood the evidence tooling: `summarize_outcomes(state_dir)` currently folds
the whole ledger. As CRAWL accrues runs, windowed evidence (last 7/30 days)
becomes useful. Add an optional `since: str | None = None` parameter — when
given (an ISO timestamp), only outcomes whose `ts >= since` are counted; all
existing metrics (gate_pass_rate, revert_rate, cost_per_run, …) computed over
the window. Default None = whole-ledger, behaviour-identical to today.

Acceptance: create `tests/test_crawl_ledger_since.py` covering: (1) `since`
excludes older outcomes from `total`/`gate_pass`; (2) `since=None` is
unchanged; (3) a `since` after all outcomes yields `{"total": 0}`. Keep the
change inside crawl_ledger.py. `chimera verify` (ruff + the new test) green.
