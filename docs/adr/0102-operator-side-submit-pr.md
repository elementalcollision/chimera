# ADR 0102 — Operator-Side `submit-pr` Verb (v4.97)

**Status**: Accepted (2026-05-22)
**Supersedes**: n/a
**Related**: ADR 0098 (loop guard), ADR 0099–0101 (escalation trust chain)

## Context

Across the v1–v9 soak series the agent has produced two `[agent]` commits
that we wanted to ship from a soak worktree into `main`:

- v6: `aeb8a56` — `detect_ping_pong` wiring (landed via cherry-pick).
- v8: agent commits produced but not shipped.

The workflow that absorbs these has been:

> agent commits to a worktree branch (per-worktree push-block set to
> `no-push://disabled-for-soak-vN`) → operator manually reviews the
> diff → operator cherry-picks files onto `main` → operator commits,
> tags, pushes.

Cherry-pick scales poorly as agent contributions become routine, and it
loses the agent's original SHA, which hurts auditability.

The natural next step is to give the agent its own credential and let
it submit a PR directly. **We explicitly choose not to do this.**

## Why NOT issue agent-side credentials

We evaluated four options:

| Option | Verdict |
| --- | --- |
| A. Operator-side `submit-pr` verb | **Accepted** |
| B. GitHub App with narrow scope + short-lived tokens | Reasonable but premature |
| C. Classic PAT in `.env` | Rejected: catastrophic blast radius |
| D. Per-worktree SSH deploy key | Premature; B is strictly better |

Reasons against C (and against any agent-held credential right now):

- **Exfiltration risk has grown.** The agent's `shell` allow-list now
  includes `cat`, `git`, `mkdir`, `python3`, `test`, `uv`, `sed`, `awk`
  (v4.86–v4.88). Any file the agent can read it can exfil via a
  prompt-injected outbound call from a tool the agent is allowed to
  invoke. A PAT sitting in `.env` is one `cat .env` from leaking.
- **Classic PAT scope = catastrophic.** A classic PAT on the operator's
  personal account grants read/write to *all* repos the account can
  touch. The scope cannot be reduced to "just the uberagent repo".
- **The agent has not earned this trust.** Across nine soaks we have
  one (1) clean agent-authored `chimera/` edit that shipped (v6).
  Soaks v7–v9 each surfaced a confident false-completion mode — the
  agent claimed success, a detector caught the gap (`fix_without_test`,
  `artifact_incomplete`, hollow investigation doc). Until the detector
  surface stabilizes we do not want unilateral push capability.
- **Token lifecycle is ops overhead.** Rotation, scope auditing,
  revocation, and incident response on a leaked PAT are work we
  haven't budgeted and that adds nothing the soak series needs today.

Option B (a narrow GitHub App that mints short-lived installation
tokens limited to one repo and labelled PRs) addresses most of the
above, but it is premature: we do not yet have the soak-completion
velocity that would make the cherry-pick step a bottleneck.

## Decision

Ship `chimera submit-pr` as v4.97. The verb is run by the **operator**,
from the repo root, and uses the operator's already-authenticated git
config to push and the operator's `gh` auth to open the PR. The agent
never holds a token.

### Behavior

1. Resolve the worktree's branch and validate it matches the soak
   pattern (`chimera-soak/vN-…`).
2. Run safety validations (any failure aborts and is logged):
   - `git status --porcelain` is empty.
   - Every commit between `main` and `HEAD` is either an `[agent]`
     commit or matches an allow-listed operator subject prefix
     (`soak …`, `post-mortem …`, `v4.…`, etc.).
   - No file in the diff matches a secret-shaped path (`.env`,
     `.envrc`, `state/trust_state.json`, `*.ssh*`, `*token*`,
     `*secret*`, `*credential*`).
   - No added line contains a high-entropy ≥40-char base64-ish run
     (heuristic for accidentally committed keys/tokens). `--allow-entropy`
     overrides.
   - The v4.92 `fix_without_test` gate applied across the full branch
     diff: any `chimera/*.py` touch must have a corresponding `tests/`
     touch.
3. Push from the **repo root** (not the worktree, which carries the
   `no-push://` block). The operator's git config supplies authority.
4. Open a draft PR via `gh pr create`. Body is auto-generated from
   the commit list, escalation summary (from the worktree's
   `state/chimera.db`), and a reviewer checklist; or supplied via
   `--body-from-postmortem <path>`.
5. Append every invocation (accept, reject, push-fail, gh-fail,
   success, dry-run) to `state/submit_pr_log.jsonl` for audit.

### Threat-model coverage

- **No agent credential.** The worktree push-block prevents the agent
  from pushing. `submit-pr` runs from repo root with operator auth.
- **Defense-in-depth on the diff.** Secret-path blocklist + entropy
  heuristic + `fix_without_test` gate provide multiple layers; even if
  the agent crafted a commit message to look like operator activity,
  the diff itself is still inspected.
- **Audit trail.** `state/submit_pr_log.jsonl` plus the PR itself
  beat cherry-pick's loss of the original agent SHA.

## What this is NOT

This is **not** a step toward agent-side credentials. If/when soak
velocity makes a true agent push capability worthwhile, the path is
Option B (a dedicated GitHub App with installation-token minting,
narrow `pull_request:write` scope, and a separate repo for agent
artifacts) — not extensions to `submit-pr`.

## Consequences

- One new CLI verb; one new dependency on `gh` being available where
  the operator runs `chimera`.
- One new on-disk artifact: `state/submit_pr_log.jsonl`. Rotated by
  hand if it grows unbounded.
- Cherry-pick remains supported (manual operator path); `submit-pr` is
  the default for any future agent-authored change that wants review.

## Tests

`tests/test_submit_pr.py` covers:

- happy path (mocked push + gh) → PR opened, audit logged
- reject: non-soak branch, dirty worktree, non-agent commit,
  `.env` modified, high-entropy diff, `fix_without_test`
- dry-run: same validations, no push/gh
- push failure: gh is not invoked
- `--no-draft` flag honored
