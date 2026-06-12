---
name: CRAWL task (autonomous)
about: A small, low-risk, gate-visible maintenance task for the CRAWL loop (ADR 0182).
title: ""
labels: crawl
---

<!--
  WALK (ADR 0182 phase 2): an issue with the `crawl` label AND a fenced spec
  block below is ingested by `chimera backlog from-issues` into the CRAWL
  backlog. The task must be GATE-VISIBLE — the gate must be RED on `base`
  before the change (a failing test, or a warning under `-W error`). The
  picker rejects a spec whose gate is already green.

  Keep `files` tight: it is the allowlist, the ruff scope, and the commit
  scope. Describe the task and acceptance in prose; put the machine-readable
  spec in the block.
-->

Describe the task, why it is safe/low-risk, and the acceptance criteria.

```yaml
goal: One-line task description
files: chimera/foo.py tests/test_foo.py
test: tests/test_foo.py            # optional; can carry pytest flags, e.g. "-W error::DeprecationWarning tests/test_foo.py"
base: main
```
