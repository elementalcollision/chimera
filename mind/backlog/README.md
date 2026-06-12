# CRAWL backlog (ADR 0182)

Drop one Markdown task spec per file here. The picker selects the oldest
valid, not-done spec and feeds it to `real_task_soak.sh`, producing a draft
PR for batch review. One task/day to begin.

## Spec format

```markdown
---
goal: One-line task description (becomes TASK_GOAL / the INBOX line)
files: tests/test_x.py chimera/foo.py   # allowlist the change may touch
test: tests/test_x.py                    # gate target (optional; omit = full suite)
base: main                               # branch to build from (optional; default main)
done: false                              # set true to retire a spec without deleting it
---
Free-form context and acceptance notes for the agent.
```

## Rules

- **Gate-visibility (ADR 0182):** the spec's gate must be RED on `base`
  before the change. `chimera backlog next --check-gate` rejects a spec
  whose gate is already green (exit 3) — it would prove nothing. For a
  warning-only fix, make the gate red with `-W error` in the `test` target.
- **Priority:** filename order. Prefix `01-`, `02-` to control it.
- **Scope:** keep `files` tight — it is also the ruff scope and the
  commit allowlist.

## Commands

```bash
chimera backlog list        # all specs + status
chimera backlog validate    # malformed specs (nonzero exit if any)
chimera backlog next        # the next actionable spec
chimera backlog next --check-gate --json   # picker form (runner consumes JSON)
```

## WALK — GitHub issues as a source (ADR 0182 phase 2)

Beyond hand-dropped MD files, the backlog can ingest **crawl-ready GitHub
issues**: an issue labelled `crawl` whose body carries a fenced spec block
(the same fields as the frontmatter above).

```bash
chimera backlog from-issues --repo elementalcollision/chimera --dry-run
chimera backlog from-issues --repo elementalcollision/chimera   # writes specs
```

Each ingested issue becomes `mind/backlog/issue-<N>-<slug>.md` with
`issue: owner/repo#N` provenance, then flows through the same picker, the
same gate-visibility check, and the same soak as a curated MD spec. Issues
without a spec block are skipped (not every issue is a gate-visible task).
Use `.github/ISSUE_TEMPLATE/crawl-task.md` to file one.
