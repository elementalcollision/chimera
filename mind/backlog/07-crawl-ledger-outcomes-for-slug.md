---
goal: "Add crawl_ledger.outcomes_for_slug(state_dir, slug) — folded outcomes for one spec"
files: chimera/core/crawl_ledger.py tests/test_crawl_ledger_outcomes_for_slug.py
test: tests/test_crawl_ledger_outcomes_for_slug.py
base: main
done: true
---
Add `outcomes_for_slug(state_dir, slug) -> list[CrawlOutcome]` to
`chimera.core.crawl_ledger` returning the folded outcomes whose `slug` matches,
in `read_outcomes` order (first-seen). Lets a reviewer see how one spec has
fared across runs (e.g. re-dispatches, reverts). Reuse `read_outcomes()`.

Acceptance: create `tests/test_crawl_ledger_outcomes_for_slug.py` (use
`tmp_path` as the state dir; build outcomes via `record_outcome`) covering:
two outcomes for slug "a" + one for "b" → `outcomes_for_slug(sd, "a")` returns
exactly the two "a" outcomes in order; an unknown slug → `[]`. Keep the change
in `chimera/core/crawl_ledger.py`. `chimera verify` (ruff + the new test) green.
